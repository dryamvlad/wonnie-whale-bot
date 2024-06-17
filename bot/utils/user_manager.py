import time
from aiogram import Bot

from bot.config import settings
from bot.db.services.service_users import UsersService
from bot.db.utils.unitofwork import UnitOfWork
from bot.db.schemas.schema_users import UserSchema
from bot.db.schemas.schema_history import HistorySchemaAdd


class UserManager:
    def __init__(self, bot: Bot, admin_notifier: "AdminNotifier", uow: UnitOfWork):
        self.bot: Bot = bot
        self.admin_notifier: "AdminNotifier" = admin_notifier
        self.uow: UnitOfWork = uow

    async def ban_user(
        self,
        user: UserSchema,
        history_entry: HistorySchemaAdd,
        notify_admin: bool = True,
        notification_type: str = "ban",
    ) -> UserSchema:
        await self.bot.ban_chat_member(
            chat_id=settings.CHAT_ID, user_id=user.tg_user_id
        )
        await self.bot.ban_chat_member(
            chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
        )
        await self.bot.revoke_chat_invite_link(settings.CHAT_ID, user.invite_link)
        if user.channel_invite_link:
            await self.bot.revoke_chat_invite_link(
                settings.CHANNEL_ID, user.channel_invite_link
            )

        user.banned = True
        user.invite_link = None
        user.channel_invite_link = None
        await UsersService().edit_user(
            uow=self.uow, user_id=user.id, user=user, history_entry=history_entry
        )

        if notify_admin:
            await self.admin_notifier.notify_admin(type=notification_type, user=user)

        return user

    async def unban_user(
        self,
        user: UserSchema,
        history_entry: HistorySchemaAdd,
        notify_admin: bool = True,
        notification_type: str = "unban",
    ) -> UserSchema:
        user.banned = False
        expire_date = int(time.time()) + 86400  # +1 day from current unix timestamp
        await self.bot.unban_chat_member(
            chat_id=settings.CHAT_ID, user_id=user.tg_user_id
        )
        await self.bot.unban_chat_member(
            chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
        )
        if user.invite_link:
            await self.bot.revoke_chat_invite_link(settings.CHAT_ID, user.invite_link)
        if user.channel_invite_link:
            await self.bot.revoke_chat_invite_link(
                settings.CHANNEL_ID, user.channel_invite_link
            )
        if not user.invite_link:
            invite = await self.bot.create_chat_invite_link(
                chat_id=settings.CHAT_ID,
                name=user.username,
                member_limit=1,
                expire_date=expire_date,
            )
            user.invite_link = invite.invite_link
        if not user.channel_invite_link:
            invite_channel = await self.bot.create_chat_invite_link(
                chat_id=settings.CHANNEL_ID,
                name=user.username,
                member_limit=1,
                expire_date=expire_date,
            )
            user.channel_invite_link = invite_channel.invite_link

        await UsersService().edit_user(
            uow=self.uow, user_id=user.id, user=user, history_entry=history_entry
        )

        if notify_admin:
            await self.admin_notifier.notify_admin(type=notification_type, user=user)
