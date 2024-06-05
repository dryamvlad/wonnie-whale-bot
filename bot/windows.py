import asyncio
import logging
from aiogram import Bot
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import User, ChatMemberMember, Chat
from aiogram.types import InlineKeyboardButton as Button
from aiogram.types import InlineKeyboardMarkup as Markup
from aiogram.utils import markdown
from aiogram.exceptions import TelegramAPIError

from aiogram_tonconnect import ATCManager
from aiogram_tonconnect.tonconnect.models import AccountWallet, AppWallet

from sqlalchemy.exc import IntegrityError, NoResultFound

from bot.db.schemas.schema_users import UserSchema, UserSchemaAdd
from bot.db.schemas.schema_history import HistorySchemaAdd
from bot.db.services.service_users import UsersService
from bot.db.utils.unitofwork import UnitOfWork
from bot.keyboards import kb_buy_won

from pytoniq.liteclient import LiteServerError

from bot.config import Settings

from pytoniq_core import Address

from bot.util_middleware import AdminNotifier, ListChecker, TonApiHelper, DeDustHelper


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
    list_checker: ListChecker,
    admin_notifier: AdminNotifier,
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

        is_og = list_checker.check_og(user_chat.username)
        is_blacklisted = list_checker.check_blacklist(user_chat.username)

        if is_og:
            threshold_balance = settings.OG_THRESHOLD_BALANCE
        else:
            threshold_balance = settings.THRESHOLD_BALANCE

        invite_link_text = f"Мало WON на балансе. Надо не меньше {markdown.hcode(threshold_balance)}\n\n"
        channel_invite_link_text = ""

        invite_link_name = f"{user_chat.first_name} {user_chat.last_name}"
        username = user_chat.username if user_chat.username else invite_link_name

        wallet = Address(account_wallet.address.hex_address).to_str()
        won_balance = await ton_api_helper.get_jetton_balance(
            account_wallet.address, settings.WON_ADDR
        )
        won_lp_balance = await ton_api_helper.get_jetton_balance(
            wallet, settings.WON_LP_ADDR
        )

        new_user = UserSchemaAdd(
            username=username,
            balance=won_balance,
            blacklisted=is_blacklisted,
            og=is_og,
            entry_balance=won_balance,
            banned=False,
            wallet=wallet,
            tg_user_id=user_chat.id,
            invite_link="",
            channel_invite_link="",
        )

        if won_balance:
            won_balance = (
                (won_balance + won_lp_balance) if won_lp_balance else won_balance
            )
            await admin_notifier.notify_admin(type="connect", user=new_user)

        existing_member = await bot.get_chat_member(
            chat_id=settings.CHAT_ID, user_id=user_chat.id
        )
        channel_existing_member = await bot.get_chat_member(
            chat_id=settings.CHANNEL_ID, user_id=user_chat.id
        )
        is_in_chat = isinstance(existing_member, ChatMemberMember)
        is_in_channel = isinstance(channel_existing_member, ChatMemberMember)

        try:
            user = await UsersService().get_user_by_tg_id(
                uow=uow, tg_user_id=user_chat.id
            )
        except NoResultFound:
            user = None

        if won_balance and won_balance >= threshold_balance:
            invite_link_text = "Вы уже в чате.\n\n"
            channel_invite_link_text = "Вы уже подписаны на канал.\n\n"
            if not is_blacklisted:
                if not is_in_chat:
                    invite_link = await bot.create_chat_invite_link(
                        chat_id=settings.CHAT_ID, name=invite_link_name, member_limit=1
                    )
                    invite_link_text = f"Вступить в чат: {invite_link.invite_link}\n\n"
                if not is_in_channel:
                    channel_invite_link = await bot.create_chat_invite_link(
                        chat_id=settings.CHANNEL_ID,
                        name=invite_link_name,
                        member_limit=1,
                    )
                    channel_invite_link_text = (
                        f"Подписаться на канал: {channel_invite_link.invite_link}\n\n"
                    )
            else:
                invite_link_text = "Вам запрещен вход в коммьюнити.\n\n"
                channel_invite_link_text = ""

            if not user:
                new_user.invite_link = (
                    invite_link.invite_link if not is_blacklisted else ""
                )
                new_user.channel_invite_link = (
                    channel_invite_link.invite_link if not is_blacklisted else ""
                )
                await UsersService().add_user(
                    uow=uow,
                    user=new_user,
                )
            else:  # User reportedly has changed wallet with enough balance
                if not user.blacklisted:
                    if user.wallet != wallet:
                        notification_type = "change_wallet_low"
                        user.wallet = wallet
                    else:
                        notification_type = "unban"
                    await admin_notifier.notify_admin(
                        type=notification_type,
                        user=user,
                    )

                    user.wallet = wallet
                    user.og = is_og
                    user.blacklisted = is_blacklisted
                    user.balance = won_balance
                    user.banned = False
                    user.invite_link = invite_link.invite_link
                    user.channel_invite_link = channel_invite_link.invite_link
                    history_entry = HistorySchemaAdd(
                        user_id=user.id,
                        balance_delta=0,
                        price=-1.0,
                        wallet=wallet,
                    )
                    await UsersService().edit_user(
                        uow=uow, user_id=user.id, user=user, history_entry=history_entry
                    )
                    await bot.unban_chat_member(
                        chat_id=settings.CHAT_ID, user_id=user.tg_user_id
                    )
                    await bot.unban_chat_member(
                        chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
                    )
                else:
                    invite_link_text = "Вам запрещен вход в коммьюнити.\n\n"
        # User has changed wallet with insufficient balance
        elif user:
            if user.wallet != wallet:
                notification_type = "change_wallet_low"
                user.wallet = wallet
            else:
                notification_type = "ban"
            await admin_notifier.notify_admin(
                type=notification_type,
                user=user,
            )

            user.balance = won_balance
            user.banned = True
            user.og = is_og
            user.blacklisted = is_blacklisted
            history_entry = HistorySchemaAdd(
                user_id=user.id,
                balance_delta=won_balance - user.balance,
                price=-1.0,
                wallet=wallet,
            )
            await UsersService().edit_user(
                uow=uow, user_id=user.id, user=user, history_entry=history_entry
            )
            await bot.ban_chat_member(chat_id=settings.CHAT_ID, user_id=user.tg_user_id)
            await bot.ban_chat_member(
                chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
            )
            await bot.revoke_chat_invite_link(settings.CHAT_ID, user.invite_link)
            if user.channel_invite_link:
                await bot.revoke_chat_invite_link(
                    settings.CHANNEL_ID, user.channel_invite_link
                )

        text = (
            f"Подключенный кошелек {app_wallet.name}:\n\n"
            f"{markdown.hcode(wallet)}\n\n"
            f"Баланс: {won_balance} WON\n\n"
            f"{invite_link_text}\n"
            f"{channel_invite_link_text}"
        )
        try:
            price = await dedust_helper.get_jetton_price(settings.WON_ADDR)
        except LiteServerError:
            price = 0
            logging.error("Failed to get price from dedust")

        kb = await kb_buy_won(settings=settings, price=price, disconnect=True)

        await bot.send_message(chat_id=user_chat.id, text=text, reply_markup=kb)
        await atc_manager.state.set_state(UserState.main_menu)
    except TelegramAPIError as e:
        logging.error(
            f"TelegramAPIError:{e.method.__class__.__name__}({e.method}) — {e.message}"
        )


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
