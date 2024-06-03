import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.utils import markdown
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
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
from .util_middleware import UtilMiddleware, TonApiHelper, DeDustHelper
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
    bot: Bot, uow: UnitOfWork, ton_api_helper: TonApiHelper, dedust_helper: DeDustHelper
):
    try:
        # print("@ Update users task started")
        users: list[UserSchema] = await UsersService().get_users(uow=uow)
        counter = 0

        price = await dedust_helper.get_jetton_price(settings.WON_ADDR)

        for user in users:
            if user.blacklisted:
                continue
            # print(f"### Checking user with id {user.id}")
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
                # print(
                #     f"--- User with id {user.id} and wallet {user.wallet} has low balance"
                # )
                user.banned = True
                user.balance = won_balance
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )

                try:
                    await bot.ban_chat_member(
                        chat_id=settings.CHAT_ID, user_id=user.tg_user_id
                    )
                    await bot.revoke_chat_invite_link(
                        settings.CHAT_ID, user.invite_link
                    )
                except TelegramBadRequest:
                    pass

                message_text = (
                    f"Мало WON на кошельке {markdown.hcode(user.wallet)}\n\n"
                    f"Убрали вас из чата.\n\n"
                    f"Пополните баланс чтобы вернуться. Надо не меньше {markdown.hcode(str(threshold_balance))} WON"
                )
                reply_markup = await kb_buy_won(settings=settings, price=price)
                await bot.send_message(
                    chat_id=user.tg_user_id,
                    text=message_text,
                    reply_markup=reply_markup,
                )
                await bot.send_message(
                    chat_id=settings.ADMIN_CHAT_ID,
                    text=f"--- User BANNED \n\n@{user.username} \n{markdown.hcode(user.wallet)}",
                )
            elif user.banned and won_balance >= threshold_balance:
                # print(
                #     f"+++ User with id {user.id} and wallet {user.wallet} has enough balance and unbanned"
                # )

                invite_link = await bot.create_chat_invite_link(
                    chat_id=settings.CHAT_ID, name=user.username, member_limit=1
                )

                message_text = (
                    f"Кошелек {markdown.hcode(user.wallet)} пополнен, вы можете вернуться в чат!\n\n"
                    f"Ссылка для вступления: {invite_link.invite_link}"
                )
                await bot.send_message(chat_id=user.tg_user_id, text=message_text)
                await bot.send_message(
                    chat_id=settings.ADMIN_CHAT_ID,
                    text=f"+++ User UNBANNED \n\n@{user.username} \n{markdown.hcode(user.wallet)}",
                )

                user.banned = False
                user.balance = won_balance
                user.invite_link = invite_link.invite_link
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )
            elif (
                won_balance != user.balance and not user.banned and not user.blacklisted
            ):
                # print(
                #     f"*** User with id {user.id} and wallet {user.wallet} has new balance={won_balance} with delta={balance_delta}"
                # )
                await bot.send_message(
                    chat_id=settings.ADMIN_CHAT_ID,
                    text=f"*** NEW BALANCE \n\n@{user.username}\n{markdown.hcode(user.wallet)}\n\nbalance={won_balance}\ndelta={balance_delta}",
                )
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
        logging.error(f"TONAPIError: {e}")
    except TimeoutError as e:
        logging.error("TimeoutError")


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

    dp = Dispatcher(storage=storage)

    dp.update.middleware.register(ThrottlingMiddleware())
    dp.update.middleware.register(
        UtilMiddleware(
            ton_api_helper=ton_api_helper,
            dedust_helper=dedust_helper,
            uow=uow,
            settings=settings,
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
        args=(bot, uow, ton_api_helper, dedust_helper),
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
    except TelegramBadRequest as e:
        logging.error(f"TelegramBadRequest: {e.message}")
    except TelegramForbiddenError as e:
        logging.error(f"TelegramForbiddenError: {e.message}")
    except asyncio.exceptions.TimeoutError as e:
        logging.error("TimeoutError")
