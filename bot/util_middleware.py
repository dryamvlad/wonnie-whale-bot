import asyncio
import logging
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Dict, Any, Awaitable

from bot.db.utils.unitofwork import UnitOfWork
from bot.config import Settings

from pytonapi import Tonapi
from pytoniq_core import Address
from pytoniq import LiteBalancer
from pytoniq.liteclient import LiteServerError

from dedust import Asset, Factory, PoolType


class TonApiHelper:
    def __init__(self, ton_api: Tonapi):
        self.ton_api = ton_api

    async def get_jetton_balance(self, wallet: str, jetton_addr: str) -> int:
        jettons_balances = self.ton_api.accounts.get_jettons_balances(wallet)

        for balance in jettons_balances.balances:
            curr_jetton_addr = Address(balance.jetton.address()).to_str()
            jetton_balance = int(balance.balance) / (10**balance.jetton.decimals)

            if curr_jetton_addr == jetton_addr:
                return int(jetton_balance)

        return None


class DeDustHelper:
    def __init__(self, provider: LiteBalancer) -> None:
        self.provider = provider

    async def get_jetton_price(self, jetton_addr: str):
        TON = Asset.native()
        WON = Asset.jetton(jetton_addr)

        pool = await Factory.get_pool(
            pool_type=PoolType.VOLATILE, assets=[TON, WON], provider=self.provider
        )
        while True:
            try:
                price = (
                    await pool.get_estimated_swap_out(
                        asset_in=WON, amount_in=int(1 * 1e9), provider=self.provider
                    )
                )["amount_out"]
                return price / 1e9
            except LiteServerError:
                await asyncio.sleep(1)
                logging.warning("Restarting dedust get price on LiteServerError")
                continue


class UtilMiddleware(BaseMiddleware):
    def __init__(
        self,
        ton_api_helper: TonApiHelper,
        uow: UnitOfWork,
        settings: Settings,
        dedust_helper: DeDustHelper,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.ton_api_helper = ton_api_helper
        self.dedust_helper = dedust_helper

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["ton_api_helper"] = self.ton_api_helper
        data["dedust_helper"] = self.dedust_helper
        data["uow"] = self.uow
        data["settings"] = self.settings
        return await handler(event, data)
