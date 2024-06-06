import logging
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode


from pytonapi import Tonapi
from pytoniq import LiteBalancer

from .middlewares.util_middleware import (
    AdminNotifier,
    UtilMiddleware,
    TonApiHelper,
    DeDustHelper,
    ListChecker,
)
from bot.config import settings
from bot.db.utils.unitofwork import UnitOfWork

# List of wallets to exclude
EXCLUDE_WALLETS = []

print("-----BOT STARTED-----")

bot = Bot(settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
provider = LiteBalancer.from_mainnet_config(1)

logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def setup_util_middleware() -> UtilMiddleware:
    uow = UnitOfWork()
    ton_api = Tonapi(settings.TON_API_KEY)
    ton_api_helper = TonApiHelper(ton_api=ton_api)
    dedust_helper = DeDustHelper(provider=provider)
    list_checker = ListChecker()
    admin_notifier = AdminNotifier(bot=bot, settings=settings)
    return UtilMiddleware(
        ton_api_helper=ton_api_helper,
        dedust_helper=dedust_helper,
        uow=uow,
        settings=settings,
        list_checker=list_checker,
        admin_notifier=admin_notifier,
    )


util_middleware = setup_util_middleware()
