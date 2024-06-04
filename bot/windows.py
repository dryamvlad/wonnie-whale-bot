import asyncio
import logging
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
from bot.keyboards import kb_buy_won

from bot.config import Settings

from pytoniq_core import Address

from bot.util_middleware import TonApiHelper, DeDustHelper


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
    dedust_helper: DeDustHelper,
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

    bot: Bot = _["bots"][0]
    user_chat = _["event_context"].chat

    with open("ogs.txt", "r") as file:
        ogs = file.readlines()
    ogs = [line.strip().lower() for line in ogs]
    if user_chat.username:
        is_og = user_chat.username.lower() in ogs
    else:
        is_og = False

    if is_og:
        threshold_balance = settings.OG_THRESHOLD_BALANCE
    else:
        threshold_balance = settings.THRESHOLD_BALANCE

    existing_member = await bot.get_chat_member(
        chat_id=settings.CHAT_ID, user_id=user_chat.id
    )
    channel_existing_member = await bot.get_chat_member(
        chat_id=settings.CHANNEL_ID, user_id=user_chat.id
    )

    invite_link_text = (
        f"Мало WON на балансе. Надо не меньше {markdown.hcode(threshold_balance)}\n\n"
    )
    channel_invite_link_text = invite_link_text

    wallet = Address(account_wallet.address.hex_address).to_str()
    won_balance = await ton_api_helper.get_jetton_balance(
        account_wallet.address, settings.WON_ADDR
    )
    won_lp_balance = await ton_api_helper.get_jetton_balance(
        wallet, settings.WON_LP_ADDR
    )
    if won_balance:
        won_balance = (won_balance + won_lp_balance) if won_lp_balance else won_balance
        # print(
        #     f"__user: {user_chat.id} wallet: {wallet} with balance {won_balance} connected\n"
        # )
        await bot.send_message(
            chat_id=settings.ADMIN_CHAT_ID,
            text=f"___User CONNECTED \nog: {is_og}\n\n @{user_chat.username}\n{markdown.hcode(wallet)}",
        )
        await asyncio.sleep(1)

    if isinstance(existing_member, ChatMemberMember) and isinstance(
        channel_existing_member, ChatMemberMember
    ):
        invite_link_text = "Вы уже вступили в чат\n\n"
        channel_invite_link_text = "Вы уже подписаны на канал\n\n"
    elif won_balance and won_balance >= threshold_balance:
        invite_link_name = f"{user_chat.first_name} {user_chat.last_name}"
        username = user_chat.username if user_chat.username else invite_link_name
        invite_link = await bot.create_chat_invite_link(
            chat_id=settings.CHAT_ID, name=invite_link_name, member_limit=1
        )
        channel_invite_link = await bot.create_chat_invite_link(
            chat_id=settings.CHANNEL_ID, name=invite_link_name, member_limit=1
        )
        invite_link_text = f"Вступить в чат: {invite_link.invite_link}\n\n"
        channel_invite_link_text = (
            f"Подписаться на канал: {channel_invite_link.invite_link}\n\n"
        )

        try:
            user_id = await UsersService().add_user(
                uow=uow,
                user=UserSchemaAdd(
                    username=username,
                    balance=won_balance,
                    blacklisted=False,
                    entry_balance=won_balance,
                    banned=False,
                    invite_link=invite_link.invite_link,
                    wallet=wallet,
                    tg_user_id=user_chat.id,
                    og=is_og,
                ),
            )
        except IntegrityError:  # User is already in the database
            user = await UsersService().get_user_by_tg_id(
                uow=uow, tg_user_id=user_chat.id
            )
            if not user.blacklisted:
                user.wallet = wallet
                user.og = is_og
                history_entry = HistorySchemaAdd(
                    user_id=user.id,
                    balance_delta=0,
                    price=-1.0,
                    wallet=wallet,
                )
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )
            else:
                invite_link_text = "Вам запрещен вход в коммьюнити.\n\n"

    text = (
        f"Подключенный кошелек {app_wallet.name}:\n\n"
        f"{markdown.hcode(wallet)}\n\n"
        f"Баланс: {won_balance} WON\n\n"
        f"{invite_link_text}\n"
        f"{channel_invite_link_text}"
    )

    # Create inline keyboard with disconnect option
    # send_amount_ton_text = "Отправить TON" if atc_manager.user.language_code == "ru" else "Send TON"
    disconnect_text = (
        "Отключиться" if atc_manager.user.language_code == "ru" else "Disconnect"
    )
    price = await dedust_helper.get_jetton_price(settings.WON_ADDR)
    kb = await kb_buy_won(settings=settings, price=price, disconnect=True)

    # Sending the message and updating user state
    await bot.send_message(text, reply_markup=kb)
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
