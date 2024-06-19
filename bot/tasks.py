import asyncio
import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.utils import markdown
from pytonapi.exceptions import TONAPIError
from pytoniq.liteclient import LiteServerError

from bot.config import settings
from bot.db.schemas.schema_history import HistorySchemaAdd
from bot.db.schemas.schema_users import UserSchema
from bot.db.services.service_users import UsersService
from bot.db.utils.unitofwork import UnitOfWork
from bot.keyboards import kb_buy_won
from bot.prepare import bot, util_middleware
from bot.utils.user_manager import UserManager

from .middlewares.util_middleware import (
    AdminNotifier,
    DeDustHelper,
    ListChecker,
    TonApiHelper,
)


async def task_update_users():
    uow: UnitOfWork = util_middleware.uow
    ton_api_helper: TonApiHelper = util_middleware.ton_api_helper
    dedust_helper: DeDustHelper = util_middleware.dedust_helper
    list_checker: ListChecker = util_middleware.list_checker
    admin_notifier: AdminNotifier = util_middleware.admin_notifier
    user_manager: UserManager = util_middleware.user_manager

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
                user = await user_manager.revoke_user_invite_links(user)
                await user_manager.ban_user(
                    user=user,
                    history_entry=HistorySchemaAdd(
                        user_id=user.id, balance_delta=0, price=0, wallet=user.wallet
                    ),
                    notification_type="blacklist",
                )
                continue

            won_lp_balance = await ton_api_helper.get_jetton_balance(
                user.wallet, settings.WON_LP_ADDR
            )
            won_balance = await ton_api_helper.get_jetton_balance(
                user.wallet, settings.WON_ADDR
            )

            if won_balance < 0 or won_lp_balance < 0:
                continue

            won_balance += won_lp_balance
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

            # user has low balance and not banned? ban and notify both users and admins
            if won_balance < threshold_balance and not user.banned:
                user.balance = won_balance
                logging.error("USER: %s, balance: %s", user.username, won_balance)
                user = await user_manager.ban_user(
                    user=user, history_entry=history_entry
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
            # user is banned and has enough balance? unban and notify both user and admins
            elif user.banned and won_balance >= threshold_balance:
                user.balance = won_balance
                user = await user_manager.unban_user(
                    user=user, history_entry=history_entry
                )

                message_text = (
                    f"Кошелек {markdown.hcode(user.wallet)} пополнен, вы можете вернуться в коммьюнити!\n\n"
                    f"Ссылка для вступления в чат: {user.invite_link}\n\n"
                    f"Ссылка для подписки на канал: {user.channel_invite_link}"
                )
                await bot.send_message(chat_id=user.tg_user_id, text=message_text)
            # user is not banned/blacklisted but balance changed? send buy/sell notification to admins
            elif won_balance != user.balance and not user.banned:
                buy_sell = "buy" if balance_delta > 0 else "sell"
                user.balance = won_balance
                await admin_notifier.notify_admin(
                    type_=buy_sell, user=user, sum_=balance_delta
                )
                await UsersService().edit_user(
                    uow=uow, user_id=user.id, user=user, history_entry=history_entry
                )
            # user is not banned/blacklisted and has enough balance? revoke old invite links
            elif (
                not user.banned
                and not user.blacklisted
                and won_balance >= threshold_balance
            ):
                await user_manager.revoke_old_user_invite_links(user)

            counter = counter + 1
            if counter % 99 == 0:
                await asyncio.sleep(1)  # to avoid TonApi rate limit
    except LiteServerError:
        pass
    except TONAPIError:
        logging.error("TONAPIError in task_update_users()")
    except TimeoutError:
        logging.error("TimeoutError")
    except TelegramAPIError as e:
        logging.error(
            "TelegramAPIError:%s(%s) — %s",
            e.method.__class__.__name__,
            e.method,
            e.message,
        )
    except Exception as e:
        logging.exception("Exception in task_update_users(): %s", e)
