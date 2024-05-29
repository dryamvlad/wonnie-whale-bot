from aiogram import Bot
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import User, ChatMemberMember
from aiogram.types import InlineKeyboardButton as Button
from aiogram.types import InlineKeyboardMarkup as Markup
from aiogram.utils import markdown

from aiogram_tonconnect import ATCManager
from aiogram_tonconnect.tonconnect.models import AccountWallet, AppWallet

from sqlalchemy.exc import IntegrityError

from bot.db.schemas.schema_users import UserSchema, UserSchemaAdd
from bot.db.schemas.schema_history import HistorySchemaAdd
from bot.db.services.service_users import UsersService
from bot.db.utils.unitofwork import UnitOfWork

from bot.config import Settings

from pytonapi import Tonapi

from pytoniq_core import Address

from bot.util_middleware import TonApiHelper


# Define a state group for the user with two states
class UserState(StatesGroup):
    select_language = State()
    main_menu = State()
    send_amount_ton = State()
    transaction_info = State()


async def empty_window(event_from_user: User, atc_manager: ATCManager, **_) -> None:
    pass


async def select_language_window(
    event_from_user: User, atc_manager: ATCManager, **_
) -> None:
    """
    Displays the language selection window.

    :param event_from_user: Telegram user object from middleware.
    :param atc_manager: ATCManager instance for managing TON Connect integration.
    :param _: Unused data from the middleware.
    :return: None
    """
    # Code for generating text based on the user's language
    text = (
        f"Привет, {markdown.hbold(event_from_user.full_name)}!\n\n" "Выберите язык:"
        if atc_manager.user.language_code == "ru"
        else f"Hello, {markdown.hbold(event_from_user.full_name)}!\n\n"
        f"Select language:"
    )

    # Code for creating inline keyboard with language options
    reply_markup = Markup(
        inline_keyboard=[
            [
                Button(text="Русский", callback_data="ru"),
                Button(text="English", callback_data="en"),
            ]
        ]
    )

    # Sending the message and updating user state
    await atc_manager._send_message(text, reply_markup=reply_markup)
    await atc_manager.state.set_state(UserState.select_language)


async def main_menu_window(
    atc_manager: ATCManager,
    app_wallet: AppWallet,
    account_wallet: AccountWallet,
    ton_api_helper: TonApiHelper,
    uow: UnitOfWork,
    settings: Settings,
    **_,
) -> None:
    """
    Displays the main menu window.

    :param atc_manager: ATCManager instance for managing TON Connect integration.
    :param app_wallet: AppWallet instance representing the connected wallet application.
    :param account_wallet: AccountWallet instance representing the connected wallet account.
    :param _: Unused data from the middleware.
    :return: None
    """

    won_balance = await ton_api_helper.get_jetton_balance(
        account_wallet.address, settings.WON_ADDR
    )

    bot: Bot = _["bots"][0]
    user_chat = _["event_context"].chat

    existing_member = await bot.get_chat_member(
        chat_id=settings.CHAT_ID, user_id=user_chat.id
    )

    invite_link_text = f"Мало WON на балансе для вступления в чат. Надо не меньше {settings.THRESHOLD_BALANCE}\n\n"

    if isinstance(existing_member, ChatMemberMember):
        invite_link_text = "Вы уже вступили в чат\n\n"
    elif won_balance >= settings.THRESHOLD_BALANCE:
        invite_link_name = f"{user_chat.first_name} {user_chat.last_name}"
        invite_link = await bot.create_chat_invite_link(
            chat_id=settings.CHAT_ID, name=invite_link_name, member_limit=1
        )
        invite_link_text = f"Вступить в чат: {invite_link.invite_link}\n\n"

        try:
            user_id = await UsersService().add_user(
                uow=uow,
                user=UserSchemaAdd(
                    username=user_chat.username,
                    balance=won_balance,
                    blacklisted=False,
                    entry_balance=won_balance,
                    banned=False,
                    invite_link=invite_link.invite_link,
                    wallet=app_wallet.name,
                    tg_user_id=user_chat.id,
                ),
            )
        except IntegrityError:
            user = await UsersService().get_user_by_tg_id(
                uow=uow, tg_user_id=user_chat.id
            )
            user.wallet = app_wallet.name
            history_entry = HistorySchemaAdd(
                user_id=user.id, balance_delta=0, price=-1.0, wallet=app_wallet.name
            )
            await UsersService().edit_user(
                uow=uow, user_id=user.id, user=user, history_entry=history_entry
            )

    text = (
        f"Подключенный кошелек {app_wallet.name}:\n\n"
        f"{markdown.hcode(account_wallet.address)}\n\n"
        f"Баланс: {won_balance} WON\n\n"
        f"{invite_link_text}"
    )

    # Create inline keyboard with disconnect option
    # send_amount_ton_text = "Отправить TON" if atc_manager.user.language_code == "ru" else "Send TON"
    disconnect_text = (
        "Отключиться" if atc_manager.user.language_code == "ru" else "Disconnect"
    )
    reply_markup = Markup(
        inline_keyboard=[
            # [Button(text=send_amount_ton_text, callback_data="send_amount_ton")],
            [Button(text=disconnect_text, callback_data="disconnect")],
        ]
    )

    # Sending the message and updating user state
    await atc_manager._send_message(text, reply_markup=reply_markup)
    await atc_manager.state.set_state(UserState.main_menu)


async def send_amount_ton_window(atc_manager: ATCManager, **_) -> None:
    """
    Displays the window for sending TON.

    :param atc_manager: ATCManager instance for managing TON Connect integration.
    :param _: Unused data from the middleware.
    :return: None
    """
    # Determine text based on user's language
    text = (
        "Сколько TON вы хотите отправить?"
        if atc_manager.user.language_code == "ru"
        else "How much TON do you want to send?"
    )
    button_text = "‹ Назад" if atc_manager.user.language_code == "ru" else "‹ Back"
    reply_markup = Markup(
        inline_keyboard=[[Button(text=button_text, callback_data="back")]]
    )

    # Send the message and update user state
    await atc_manager._send_message(text, reply_markup=reply_markup)
    await atc_manager.state.set_state(UserState.send_amount_ton)


async def transaction_info_windows(atc_manager: ATCManager, boc: str, **_) -> None:
    """
    Displays the transaction information window.

    :param atc_manager: ATCManager instance for managing TON Connect integration.
    :param boc: The BOC (Bag of Cells) representing the transaction.
    :param _: Unused data from the middleware.
    :return: None
    """
    # Determine text based on user's language and show transaction details
    text = (
        "Транзакция успешно отправлена!\n\n" f"boc:\n{boc}"
        if atc_manager.user.language_code == "ru"
        else "Transaction successfully sent!\n\n" f"boc:\n{boc}"
    )
    button_text = (
        "‹ На главную" if atc_manager.user.language_code == "ru" else "‹ Go to main"
    )
    reply_markup = Markup(
        inline_keyboard=[[Button(text=button_text, callback_data="go_to_main")]]
    )

    # Send the message and update user state
    await atc_manager._send_message(text, reply_markup=reply_markup)
    await atc_manager.state.set_state(UserState.transaction_info)
