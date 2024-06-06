import asyncio
import logging
from aiogram.utils import markdown
from aiogram.exceptions import (
    TelegramAPIError,
)

from pytonapi.exceptions import TONAPIError
from pytoniq.liteclient import LiteServerError

from .middlewares.util_middleware import (
    AdminNotifier,
    TonApiHelper,
    DeDustHelper,
    ListChecker,
)
from bot.config import settings
from bot.db.utils.unitofwork import UnitOfWork
from bot.db.services.service_users import UsersService
from bot.db.schemas.schema_users import UserSchema
from bot.db.schemas.schema_history import HistorySchemaAdd
from bot.keyboards import kb_buy_won

from bot.prepare import bot, util_middleware


async def task_update_users():
    uow: UnitOfWork = util_middleware.uow
    ton_api_helper: TonApiHelper = util_middleware.ton_api_helper
    dedust_helper: DeDustHelper = util_middleware.dedust_helper
    list_checker: ListChecker = util_middleware.list_checker
    admin_notifier: AdminNotifier = util_middleware.admin_notifier

    logging.error("TASK UPDATE START")
    try:
        users: list[UserSchema] = await UsersService().get_users(uow=uow)
        counter = 0

        price = await dedust_helper.get_jetton_price(settings.WON_ADDR)

        for user in users:
            is_blacklisted = list_checker.check_blacklist(user.username)
            if user.blacklisted:
                continue
            if is_blacklisted:
                user.blacklisted = True
                await UsersService().edit_user(uow=uow, user_id=user.id, user=user)
                await admin_notifier.notify_admin(type="blacklist", user=user)
                continue

            won_lp_balance = await ton_api_helper.get_jetton_balance(
                user.wallet, settings.WON_LP_ADDR
            )
            won_balance = await ton_api_helper.get_jetton_balance(
                user.wallet, settings.WON_ADDR
            )

            if not won_balance:
                continue

            won_balance = (
                won_balance + won_lp_balance if won_lp_balance else won_balance
            )
            balance_delta = won_balance - user.balance

            if user.og:
                threshold_balance = settings.OG_THRESHOLD_BALANCE
            else:
                threshold_balance = settings.THRESHOLD_BALANCE

            history_entry = HistorySchemaAdd(
                user_id=user.id,
                balance_delta=balance_delta,
                price=price,
                wallet=user.wallet,
            )

            if won_balance < threshold_balance and not user.banned:
                user.banned = True
                user.balance = won_balance
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )

                ban_chat_res = await bot.ban_chat_member(
                    chat_id=settings.CHAT_ID, user_id=user.tg_user_id
                )
                ban_chan_res = await bot.ban_chat_member(
                    chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
                )
                revoke_chat_res = await bot.revoke_chat_invite_link(
                    settings.CHAT_ID, user.invite_link
                )
                if user.channel_invite_link:
                    revoke_chan_res = await bot.revoke_chat_invite_link(
                        settings.CHANNEL_ID, user.channel_invite_link
                    )

                message_text = (
                    f"Мало WON на кошельке {markdown.hcode(user.wallet)}\n\n"
                    f"Убрали вас из коммьюнити.\n\n"
                    f"Пополните баланс чтобы вернуться. Надо не меньше {markdown.hcode(str(threshold_balance))} WON"
                )
                reply_markup = await kb_buy_won(settings=settings, price=price)
                await bot.send_message(
                    chat_id=user.tg_user_id,
                    text=message_text,
                    reply_markup=reply_markup,
                )
                await admin_notifier.notify_admin(type="ban", user=user)
            elif user.banned and won_balance >= threshold_balance:
                chat_unban_res = await bot.unban_chat_member(
                    chat_id=settings.CHAT_ID, user_id=user.tg_user_id
                )
                chan_unban_res = await bot.unban_chat_member(
                    chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
                )
                invite_link = await bot.create_chat_invite_link(
                    chat_id=settings.CHAT_ID, name=user.username, member_limit=1
                )
                channel_invite_link = await bot.create_chat_invite_link(
                    chat_id=settings.CHANNEL_ID, name=user.username, member_limit=1
                )

                message_text = (
                    f"Кошелек {markdown.hcode(user.wallet)} пополнен, вы можете вернуться в коммьюнити!\n\n"
                    f"Ссылка для вступления в чат: {invite_link.invite_link}\n\n"
                    f"Ссылка для подписки на канал: {channel_invite_link.invite_link}"
                )
                await bot.send_message(chat_id=user.tg_user_id, text=message_text)
                await admin_notifier.notify_admin(type="unban", user=user)

                user.banned = False
                user.balance = won_balance
                user.invite_link = invite_link.invite_link
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )
            elif (
                won_balance != user.balance and not user.banned and not user.blacklisted
            ):
                buy_sell = "buy" if balance_delta > 0 else "sell"
                await admin_notifier.notify_admin(type=buy_sell, user=user)
                user.balance = won_balance
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )

            counter = counter + 1
            if counter % 99 == 0:
                await asyncio.sleep(1)  # to avoid TonApi rate limit
    except LiteServerError:
        pass
    except TONAPIError as e:
        logging.error(f"TONAPIError")
    except TimeoutError as e:
        logging.error("TimeoutError")
    except TelegramAPIError as e:
        logging.error(
            f"TelegramAPIError:{e.method.__class__.__name__}({e.method}) — {e.message}"
        )
