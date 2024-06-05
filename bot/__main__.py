import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.utils import markdown
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramAPIError,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram_tonconnect.handlers import AiogramTonConnectHandlers
from aiogram_tonconnect.middleware import AiogramTonConnectMiddleware
from aiogram_tonconnect.tonconnect.storage.base import ATCMemoryStorage
from aiogram_tonconnect.utils.qrcode import QRUrlProvider

from aiohttp.client_exceptions import ClientPayloadError
from asyncio.exceptions import IncompleteReadError

from pytonapi import Tonapi
from pytonapi.exceptions import TONAPIError
from pytoniq import LiteBalancer
from pytoniq.liteclient import LiteServerError

import aiocron

from .handlers import router
from .throttling import ThrottlingMiddleware
from .util_middleware import (
    AdminNotifier,
    UtilMiddleware,
    TonApiHelper,
    DeDustHelper,
    ListChecker,
)
from bot.config import settings
from bot.db.utils.unitofwork import UnitOfWork
from bot.db.services.service_users import UsersService
from bot.db.schemas.schema_users import UserSchema
from bot.db.schemas.schema_history import HistorySchemaAdd
from bot.keyboards import kb_buy_won

# List of wallets to exclude
EXCLUDE_WALLETS = []

print("-----BOT STARTED-----")


async def task_update_users(
    bot: Bot,
    uow: UnitOfWork,
    ton_api_helper: TonApiHelper,
    dedust_helper: DeDustHelper,
    list_checker: ListChecker,
    admin_notifier: AdminNotifier,
):
    try:
        users: list[UserSchema] = await UsersService().get_users(uow=uow)
        counter = 0

        price = await dedust_helper.get_jetton_price(settings.WON_ADDR)

        for user in users:
            is_blacklisted = list_checker.check_blacklist(user.username)
            if user.blacklisted:
                continue
            if is_blacklisted:
                user.blacklisted = True
                await UsersService().edit_user(uow=uow, user_id=user.id, user=user)
                await admin_notifier.notify_admin(type="blacklist", user=user)
                continue

            won_lp_balance = await ton_api_helper.get_jetton_balance(
                user.wallet, settings.WON_LP_ADDR
            )
            won_balance = await ton_api_helper.get_jetton_balance(
                user.wallet, settings.WON_ADDR
            )

            if not won_balance:
                continue

            won_balance = (
                won_balance + won_lp_balance if won_lp_balance else won_balance
            )
            balance_delta = won_balance - user.balance

            if user.og:
                threshold_balance = settings.OG_THRESHOLD_BALANCE
            else:
                threshold_balance = settings.THRESHOLD_BALANCE

            history_entry = HistorySchemaAdd(
                user_id=user.id,
                balance_delta=balance_delta,
                price=price,
                wallet=user.wallet,
            )

            if won_balance < threshold_balance and not user.banned:
                user.banned = True
                user.balance = won_balance
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )

                ban_chat_res = await bot.ban_chat_member(
                    chat_id=settings.CHAT_ID, user_id=user.tg_user_id
                )
                ban_chan_res = await bot.ban_chat_member(
                    chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
                )
                revoke_chat_res = await bot.revoke_chat_invite_link(
                    settings.CHAT_ID, user.invite_link
                )
                if user.channel_invite_link:
                    revoke_chan_res = await bot.revoke_chat_invite_link(
                        settings.CHANNEL_ID, user.channel_invite_link
                    )

                message_text = (
                    f"Мало WON на кошельке {markdown.hcode(user.wallet)}\n\n"
                    f"Убрали вас из коммьюнити.\n\n"
                    f"Пополните баланс чтобы вернуться. Надо не меньше {markdown.hcode(str(threshold_balance))} WON"
                )
                reply_markup = await kb_buy_won(settings=settings, price=price)
                await bot.send_message(
                    chat_id=user.tg_user_id,
                    text=message_text,
                    reply_markup=reply_markup,
                )
                await admin_notifier.notify_admin(type="ban", user=user)
            elif user.banned and won_balance >= threshold_balance:
                chat_unban_res = await bot.unban_chat_member(
                    chat_id=settings.CHAT_ID, user_id=user.tg_user_id
                )
                chan_unban_res = await bot.unban_chat_member(
                    chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
                )
                invite_link = await bot.create_chat_invite_link(
                    chat_id=settings.CHAT_ID, name=user.username, member_limit=1
                )
                channel_invite_link = await bot.create_chat_invite_link(
                    chat_id=settings.CHANNEL_ID, name=user.username, member_limit=1
                )

                message_text = (
                    f"Кошелек {markdown.hcode(user.wallet)} пополнен, вы можете вернуться в коммьюнити!\n\n"
                    f"Ссылка для вступления в чат: {invite_link.invite_link}\n\n"
                    f"Ссылка для подписки на канал: {channel_invite_link.invite_link}"
                )
                await bot.send_message(chat_id=user.tg_user_id, text=message_text)
                await admin_notifier.notify_admin(type="unban", user=user)

                user.banned = False
                user.balance = won_balance
                user.invite_link = invite_link.invite_link
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )
            elif (
                won_balance != user.balance and not user.banned and not user.blacklisted
            ):
                buy_sell = "buy" if balance_delta > 0 else "sell"
                await admin_notifier.notify_admin(type=buy_sell, user=user)
                user.balance = won_balance
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )

            counter = counter + 1
            if counter % 99 == 0:
                await asyncio.sleep(1)  # to avoid TonApi rate limit
    except LiteServerError:
        pass
    except TONAPIError as e:
        logging.error(f"TONAPIError")
    except TimeoutError as e:
        logging.error("TimeoutError")
    except TelegramAPIError as e:
        logging.error(
            f"TelegramAPIError:{e.method.__class__.__name__}({e.method}) — {e.message}"
        )


async def main():
    provider = LiteBalancer.from_mainnet_config(1)
    await provider.start_up()

    logging.basicConfig(
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    storage = MemoryStorage()

    bot = Bot(
        settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    uow = UnitOfWork()
    ton_api = Tonapi(settings.TON_API_KEY)
    ton_api_helper = TonApiHelper(ton_api=ton_api)
    dedust_helper = DeDustHelper(provider=provider)
    list_checker = ListChecker()
    admin_notifier = AdminNotifier(bot=bot, settings=settings)

    dp = Dispatcher(storage=storage)

    # dp.update.middleware.register(ThrottlingMiddleware())
    dp.update.middleware.register(
        UtilMiddleware(
            ton_api_helper=ton_api_helper,
            dedust_helper=dedust_helper,
            uow=uow,
            settings=settings,
            list_checker=list_checker,
            admin_notifier=admin_notifier,
        )
    )

    dp.update.middleware.register(
        AiogramTonConnectMiddleware(
            storage=ATCMemoryStorage(),
            manifest_url=settings.MANIFEST_URL,
            exclude_wallets=EXCLUDE_WALLETS,
            qrcode_provider=QRUrlProvider(),
        )
    )

    AiogramTonConnectHandlers().register(dp)

    dp.include_router(router)

    # Schedule task_update_users to run every 59 seconds
    aiocron.crontab(
        f"* * * * * */{settings.REFRESH_TIMEOUT}",
        func=task_update_users,
        args=(bot, uow, ton_api_helper, dedust_helper, list_checker, admin_notifier),
        start=True,
    )

    await dp.start_polling(bot)

    await provider.close_all()


if __name__ == "__main__" or __name__ == "bot.__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(main())
        loop.run_forever()
    except ConnectionError:
        pass
    except ClientPayloadError:
        pass
    except asyncio.exceptions.IncompleteReadError:
        pass
    except TelegramAPIError as e:
        logging.error(
            f"TelegramAPIError:{e.method.__class__.__name__}({e.method}) — {e.message}"
        )
    except asyncio.exceptions.TimeoutError as e:
        logging.error("TimeoutError")
