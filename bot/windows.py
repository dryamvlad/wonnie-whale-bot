import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Chat, ChatMemberMember, User
from aiogram.utils import markdown
from aiogram_tonconnect import ATCManager
from aiogram_tonconnect.tonconnect.models import AccountWallet, AppWallet
from pytoniq_core import Address
from sqlalchemy.exc import NoResultFound

from bot.config import Settings
from bot.db.schemas.schema_history import HistorySchemaAdd
from bot.db.schemas.schema_users import UserSchemaAdd
from bot.db.services.service_users import UsersService
from bot.db.utils.unitofwork import UnitOfWork
from bot.keyboards import kb_buy_won
from bot.middlewares.util_middleware import (
    AdminNotifier,
    DeDustHelper,
    ListChecker,
    TonApiHelper,
)
from bot.utils.user_manager import UserManager


# Define a state group for the user with two states
class UserState(StatesGroup):
    main_menu = State()


async def empty_window(event_from_user: User, atc_manager: ATCManager, **_) -> None:
    pass


async def main_menu_window(
    atc_manager: ATCManager,
    app_wallet: AppWallet,
    account_wallet: AccountWallet,
    ton_api_helper: TonApiHelper,
    uow: UnitOfWork,
    settings: Settings,
    dedust_helper: DeDustHelper,
    list_checker: ListChecker,
    admin_notifier: AdminNotifier,
    user_manager: UserManager,
    **_,
) -> None:
    """
    Displays the main menu window.

    :param atc_manager: ATCManager instance for managing TON Connect integration.
    :param app_wallet: AppWallet instance representing the connected wallet application.
    :param account_wallet: AccountWallet instance representing the connected wallet account.
    :param ton_api_helper: TonApiHelper instance for interacting with the TON blockchain.
    :param uow: UnitOfWork instance for interacting with the database.
    :param settings: Settings instance for accessing the bot's settings.
    :param dedust_helper: DeDustHelper instance for interacting with the DeDust API.
    :param list_checker: ListChecker instance for checking user special lists.
    :param admin_notifier: AdminNotifier instance for notifying the admin channel.
    :param _: Unused data from the middleware.
    :return: None
    """

    bot: Bot = _["bots"][0]
    user_chat: Chat = _["event_context"].chat

    try:
        # delete ton connect message window
        state_data = await atc_manager.state.get_data()
        await bot.delete_message(
            message_id=state_data.get("message_id"), chat_id=user_chat.id
        )

        price = await dedust_helper.get_jetton_price(settings.WON_ADDR)

        invite_link_name = f"{user_chat.first_name} {user_chat.last_name if user_chat.last_name else ''}"
        username = user_chat.username if user_chat.username else invite_link_name

        wallet = Address(account_wallet.address.hex_address).to_str()
        won_balance = await ton_api_helper.get_jetton_balance(wallet, settings.WON_ADDR)
        won_lp_balance = await ton_api_helper.get_jetton_balance(
            wallet, settings.WON_LP_ADDR
        )
        won_balance = won_balance + won_lp_balance

        existing_member = await bot.get_chat_member(
            chat_id=settings.CHAT_ID, user_id=user_chat.id
        )
        channel_existing_member = await bot.get_chat_member(
            chat_id=settings.CHANNEL_ID, user_id=user_chat.id
        )
        is_in_chat = isinstance(existing_member, ChatMemberMember)
        is_in_channel = isinstance(channel_existing_member, ChatMemberMember)

        history_entry = HistorySchemaAdd(
            user_id=0,
            balance_delta=0,
            price=-1.0,
            wallet=wallet,
        )

        try:
            user = await UsersService().get_user_by_tg_id(
                uow=uow, tg_user_id=user_chat.id
            )
            is_new_user = False
            user.balance = won_balance
            history_entry.user_id = user.id
            history_entry.balance_delta = won_balance - user.balance
        except NoResultFound:
            user = UserSchemaAdd(
                username=username,
                balance=won_balance,
                blacklisted=list_checker.check_blacklist(user_chat.username),
                og=list_checker.check_og(user_chat.username),
                entry_balance=won_balance,
                banned=False,
                wallet=wallet,
                tg_user_id=user_chat.id,
                invite_link="",
                channel_invite_link="",
            )
            is_new_user = True

        await admin_notifier.notify_admin(type="connect", user=user)

        if user.og:
            threshold_balance = settings.OG_THRESHOLD_BALANCE
        else:
            threshold_balance = settings.THRESHOLD_BALANCE

        invite_link_text = f"Мало WON на балансе. Надо не меньше {markdown.hcode(threshold_balance)}\n\n"
        channel_invite_link_text = ""

        if won_balance >= threshold_balance:
            invite_link_text = "Вы уже в чате.\n\n"
            channel_invite_link_text = "Вы уже подписаны на канал.\n\n"

            if not user.blacklisted:
                expire_date = (
                    int(time.time()) + 86400
                )  # +1 day from current unix timestamp
                if not is_in_chat:
                    invite_link = await bot.create_chat_invite_link(
                        chat_id=settings.CHAT_ID,
                        name=invite_link_name,
                        member_limit=1,
                        expire_date=expire_date,
                    )
                    invite_link_text = f"Вступить в чат: {invite_link.invite_link}\n"
                    user.invite_link = invite_link.invite_link
                if not is_in_channel:
                    channel_invite_link = await bot.create_chat_invite_link(
                        chat_id=settings.CHANNEL_ID,
                        name=invite_link_name,
                        member_limit=1,
                        expire_date=expire_date,
                    )
                    channel_invite_link_text = (
                        f"Подписаться на канал: {channel_invite_link.invite_link}\n"
                    )
                    user.channel_invite_link = channel_invite_link.invite_link
            else:
                invite_link_text = "Вам запрещен вход в коммьюнити.\n\n"
                channel_invite_link_text = ""

            if is_new_user:
                await UsersService().add_user(
                    uow=uow,
                    user=user,
                )
            else:  # User reportedly has changed wallet with enough balance
                if not user.blacklisted:
                    if user.wallet != wallet:
                        notification_type = "change_wallet_high"
                        user.wallet = wallet
                    else:
                        notification_type = "unban"
                        history_entry = None

                    await user_manager.revoke_user_invite_links(user)
                    user.invite_link = invite_link.invite_link
                    user.channel_invite_link = channel_invite_link.invite_link
                    await user_manager.unban_user(
                        user=user,
                        history_entry=history_entry,
                        notification_type=notification_type,
                        generate_new_invites=False,
                    )
                else:
                    invite_link_text = "Вам запрещен вход в коммьюнити.\n\n"
        # User has changed wallet with insufficient balance
        elif not is_new_user:
            if user.wallet != wallet:
                notification_type = "change_wallet_low"
                user.wallet = wallet
            else:
                notification_type = "ban"
                history_entry = None

            await user_manager.ban_user(
                user=user,
                history_entry=history_entry,
                notification_type=notification_type,
            )

        text = (
            f"Подключенный кошелек {app_wallet.name}:\n\n"
            f"{markdown.hcode(wallet)}\n\n"
            f"Баланс: {won_balance} WON\n\n"
            f"{invite_link_text}\n"
            f"{channel_invite_link_text}"
        )
        kb = await kb_buy_won(settings=settings, price=price, disconnect=True)

        await bot.send_message(chat_id=user_chat.id, text=text, reply_markup=kb)
        await atc_manager.state.set_state(UserState.main_menu)
    except TelegramAPIError as e:
        logging.error(
            "TelegramAPIError:%s(%s) — %s",
            e.method.__class__.__name__,
            e.method,
            e.message,
        )
