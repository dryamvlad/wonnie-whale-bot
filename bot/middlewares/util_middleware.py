import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject
from aiogram.utils import markdown
from dedust import Asset, Factory, PoolType
from pytonapi import Tonapi
from pytonapi.exceptions import TONAPIError
from pytoniq import LiteBalancer
from pytoniq.liteclient import LiteServerError
from pytoniq_core import Address

from bot.config import Settings
from bot.db.schemas.schema_users import UserSchema
from bot.db.utils.unitofwork import UnitOfWork
from bot.utils.user_manager import UserManager


class TonApiHelper:
    def __init__(self, ton_api: Tonapi):
        self.ton_api = ton_api

    async def get_jetton_balance(self, wallet: str, jetton_addr: str) -> int:
        try:
            jettons_balances = self.ton_api.accounts.get_jettons_balances(wallet)
        except TONAPIError:
            logging.error("TONAPIError get_jettons_balances()")
            return -1

        for balance in jettons_balances.balances:
            curr_jetton_addr = Address(balance.jetton.address()).to_str()
            jetton_balance = int(balance.balance) / (10**balance.jetton.decimals)

            if curr_jetton_addr == jetton_addr:
                return int(jetton_balance)

        return 0


class ListChecker:
    def check_og(self, username: str) -> bool:
        with open("ogs.txt", "r") as file:
            ogs = file.readlines()
        ogs = [line.strip().lower() for line in ogs]
        if username:
            return username.lower() in ogs
        return False

    def check_blacklist(self, username: str) -> bool:
        with open("blacklist.txt", "r") as file:
            blacklist = file.readlines()
        blacklist = [line.strip().lower() for line in blacklist]
        if username:
            return username.lower() in blacklist
        return False


class AdminNotifier:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self.types = {
            "connect": "🔗 ПОДКЛЮЧЕНИЕ",
            "change_wallet_low": "🔄❌ ЗАМЕНА КОШЕЛЬКА",
            "change_wallet_high": "🔄✅ ЗАМЕНА КОШЕЛЬКА",
            "ban": "❌ БАН",
            "unban": "✅ РАЗБАН",
            "buy": "🟢 ПОКУПКА",
            "sell": "🔴 ПРОДАЖА",
            "blacklist": "🚫 ЧС",
        }
        self.bot = bot
        self.settings = settings

    async def notify_admin(self, type_: str, user: UserSchema, sum_: int = None):
        if user.tg_user_id == 123671021:
            return

        bool_switch = {
            True: "➕",
            False: "➖",
        }
        sum_str = f"Сумма: {sum_} WON" if type_ in ["buy", "sell"] else ""
        admin_message = (
            f"{self.types[type_]} \n\n"
            f"C пресейла: {bool_switch[user.og]}\n"
            f"В ЧС: {bool_switch[user.blacklisted]}\n"
            f"Пользователь: @{user.username}\n"
            f"Кошелек: {markdown.hcode(user.wallet)}\n"
            f"Баланс: {user.balance} WON\n"
            f"{sum_str}"
        )
        await self.bot.send_message(
            chat_id=self.settings.ADMIN_CHANNEL_ID, text=admin_message
        )


class DeDustHelper:
    def __init__(self, provider: LiteBalancer) -> None:
        self.provider = provider

    async def get_jetton_price(self, jetton_addr: str):
        await self.provider.start_up()

        TON = Asset.native()
        WON = Asset.jetton(jetton_addr)
        while True:
            try:
                pool = await Factory.get_pool(
                    pool_type=PoolType.VOLATILE,
                    assets=[TON, WON],
                    provider=self.provider,
                )
                price = (
                    await pool.get_estimated_swap_out(
                        asset_in=WON, amount_in=int(1 * 1e9), provider=self.provider
                    )
                )["amount_out"]
                await self.provider.close_all()
                return price / 1e9
            except LiteServerError:
                await asyncio.sleep(1)
                continue
            except Exception:
                logging.error("DeDust: 0 price")
                return 0


class UtilMiddleware(BaseMiddleware):
    def __init__(
        self,
        ton_api_helper: TonApiHelper,
        uow: UnitOfWork,
        settings: Settings,
        dedust_helper: DeDustHelper,
        list_checker: ListChecker,
        admin_notifier: AdminNotifier,
        user_manager: UserManager,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.ton_api_helper = ton_api_helper
        self.dedust_helper = dedust_helper
        self.list_checker = list_checker
        self.admin_notifier = admin_notifier
        self.user_manager = user_manager

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
        data["list_checker"] = self.list_checker
        data["admin_notifier"] = self.admin_notifier
        data["user_manager"] = self.user_manager
        return await handler(event, data)
