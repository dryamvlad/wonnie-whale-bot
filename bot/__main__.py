import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.utils import markdown
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram_tonconnect.handlers import AiogramTonConnectHandlers
from aiogram_tonconnect.middleware import AiogramTonConnectMiddleware
from aiogram_tonconnect.tonconnect.storage.base import ATCMemoryStorage
from aiogram_tonconnect.utils.qrcode import QRUrlProvider

from pytonapi import Tonapi
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

# List of wallets to exclude
EXCLUDE_WALLETS = []

print("-----BOT STARTED-----")


async def task_update_users(
    bot: Bot, uow: UnitOfWork, ton_api_helper: TonApiHelper, dedust_helper: DeDustHelper
):
    users: list[UserSchema] = await UsersService().get_users(uow=uow)
    counter = 0
    while True:
        try:
            price = await dedust_helper.get_jetton_price(settings.WON_ADDR)
            break
        except LiteServerError:
            await asyncio.sleep(1)
            logging.warning("Restarting dedust get price on LiteServerError")
            continue

    for user in users:
        won_balance = await ton_api_helper.get_jetton_balance(
            user.wallet, settings.WON_ADDR
        )
        if not won_balance:
            continue
        balance_delta = won_balance - user.balance

        history_entry = HistorySchemaAdd(
            user_id=user.id,
            balance_delta=balance_delta,
            price=price,
            wallet=user.wallet,
        )

        if won_balance < settings.THRESHOLD_BALANCE and not user.banned:
            print(
                f"--- User with id {user.id} and wallet {user.wallet} has low balance"
            )
            user.banned = True
            user.balance = won_balance
            await UsersService().edit_user(
                uow=uow, user_id=user.id, user=user, history_entry=history_entry
            )

            try:
                await bot.ban_chat_member(
                    chat_id=settings.CHAT_ID, user_id=user.tg_user_id
                )
                await bot.revoke_chat_invite_link(settings.CHAT_ID, user.invite_link)
            except TelegramBadRequest:
                pass

            message_text = (
                f"Мало WON на кошельке {markdown.hcode(user.wallet)}\n"
                f"Убрали вас из чата.\n\n"
                f"Пополните баланс чтобы вернуться. Надо не меньше {markdown.hcode(str(settings.THRESHOLD_BALANCE))} WON"
            )
            await bot.send_message(chat_id=user.tg_user_id, text=message_text)
            break
        elif user.banned and won_balance >= settings.THRESHOLD_BALANCE:
            print(
                f"+++ User with id {user.id} and wallet {user.wallet} has enough balance and unbanned"
            )

            invite_link = await bot.create_chat_invite_link(
                chat_id=settings.CHAT_ID, name=user.username, member_limit=1
            )

            message_text = (
                f"Кошелек {markdown.hcode(user.wallet)} пополнен, вы можете вернуться в чат!\n\n"
                f"Ссылка для вступления: {invite_link.invite_link}"
            )
            await bot.send_message(chat_id=user.tg_user_id, text=message_text)

            user.banned = False
            user.balance = won_balance
            user.invite_link = invite_link.invite_link
            await UsersService().edit_user(
                uow=uow, user_id=user.id, user=user, history_entry=history_entry
            )
            break
        elif won_balance != user.balance:
            print(
                f"*** User with id {user.id} and wallet {user.wallet} has new balance={won_balance} with delta={balance_delta}"
            )
            user.balance = won_balance
            await UsersService().edit_user(
                uow=uow, user_id=user.id, user=user, history_entry=history_entry
            )

        counter = counter + 1
        if counter % 99 == 0:
            await asyncio.sleep(1)  # to avoid TonApi rate limit


async def main():
    try:
        provider = LiteBalancer.from_mainnet_config(1)
        await provider.start_up()

        logging.basicConfig(
            level=logging.ERROR,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        storage = MemoryStorage()

        bot = Bot(settings.BOT_TOKEN, parse_mode="HTML")
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
            "* * * * * */59",
            func=task_update_users,
            args=(bot, uow, ton_api_helper, dedust_helper),
            start=True,
        )

        await dp.start_polling(bot)

        await provider.close_all()
    except ConnectionError:
        pass


if __name__ == "__main__" or __name__ == "bot.__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()
