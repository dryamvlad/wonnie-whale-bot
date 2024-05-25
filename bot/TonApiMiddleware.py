from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Dict, Any, Awaitable

from pytonapi import Tonapi


class TonApiMiddleware(BaseMiddleware):
    def __init__(self, api_key: str) -> None:
        self.ton_api = Tonapi(api_key)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["ton_api"] = self.ton_api
        return await handler(event, data)