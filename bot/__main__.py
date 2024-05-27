from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram_tonconnect.handlers import AiogramTonConnectHandlers
from aiogram_tonconnect.middleware import AiogramTonConnectMiddleware
from aiogram_tonconnect.tonconnect.storage.base import ATCMemoryStorage
from aiogram_tonconnect.utils.qrcode import QRUrlProvider

from .handlers import router
from .throttling import ThrottlingMiddleware

from .util_middleware import UtilMiddleware

from bot.config import settings

# List of wallets to exclude
# Example:
# EXCLUDE_WALLETS = ["mytonwallet"]
EXCLUDE_WALLETS = []


async def main():
    # Initializing the storage for FSM (Finite State Machine)
    # storage = RedisStorage.from_url(os.environ.get("REDIS_DSN", REDIS_DSN))
    storage = MemoryStorage()

    # Creating a bot object with the token and HTML parsing mode
    bot = Bot(settings.BOT_TOKEN, parse_mode="HTML")

    # Creating a dispatcher object using the specified storage
    dp = Dispatcher(storage=storage)

    dp.update.middleware.register(ThrottlingMiddleware())
    dp.update.middleware.register(UtilMiddleware(api_key=settings.TON_API_KEY))
    # Registering middleware for TON Connect processing
    dp.update.middleware.register(
        AiogramTonConnectMiddleware(
            # storage=ATCRedisStorage(storage.redis),
            storage=ATCMemoryStorage(),
            manifest_url=settings.MANIFEST_URL,
            exclude_wallets=EXCLUDE_WALLETS,
            qrcode_provider=QRUrlProvider(),
        )
    )

    # Registering TON Connect handlers
    AiogramTonConnectHandlers().register(dp)

    # Including the router
    dp.include_router(router)

    # Starting the bot using long polling
    await dp.start_polling(bot)


if __name__ == "bot.__main__" or __name__ == "__main__":
    import asyncio

    asyncio.run(main())
