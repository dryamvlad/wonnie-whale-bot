import asyncio
import logging
from aiogram import Dispatcher
from aiogram.exceptions import (
    TelegramAPIError,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram_tonconnect.handlers import AiogramTonConnectHandlers
from aiogram_tonconnect.middleware import AiogramTonConnectMiddleware
from aiogram_tonconnect.tonconnect.storage.base import ATCMemoryStorage
from aiogram_tonconnect.utils.qrcode import QRUrlProvider

from aiohttp.client_exceptions import ClientPayloadError

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.middlewares.throttling import ThrottlingMiddleware
from bot.handlers import router
from bot.config import settings
from bot.prepare import bot, util_middleware, EXCLUDE_WALLETS
from bot.tasks import task_update_users


def exception_handler(loop, context):
    if "exception" not in context:
        return
    exception = context["exception"]
    message = context["message"]
    if exception.__class__.__name__ != "IncompleteReadError":
        logging.error(f"Task failed, msg={message}, exception={exception}")


async def start_bot():
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.update.middleware.register(ThrottlingMiddleware())
    dp.update.middleware.register(util_middleware)
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

    await dp.start_polling(bot)


async def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        task_update_users, trigger="interval", seconds=settings.REFRESH_TIMEOUT
    )
    scheduler.start()


async def main():
    await asyncio.gather(start_bot(), start_scheduler())


if __name__ == "__main__" or __name__ == "bot.__main__":
    loop = asyncio.new_event_loop()
    loop.set_exception_handler(exception_handler)
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except ConnectionError:
        pass
    except ClientPayloadError:
        pass
    except TelegramAPIError as e:
        logging.error(
            f"TelegramAPIError:{e.method.__class__.__name__}({e.method}) — {e.message}"
        )
    except asyncio.exceptions.TimeoutError as e:
        logging.error("TimeoutError")
