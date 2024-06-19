import time
from aiogram import Bot
from aiogram.types import ChatMemberMember

from bot.config import settings
from bot.db.services.service_users import UsersService
from bot.db.utils.unitofwork import UnitOfWork
from bot.db.schemas.schema_users import UserSchema
from bot.db.schemas.schema_history import HistorySchemaAdd


class UserManager:
    """Class for managing user actions such as banning, unbanning, and revoking invite links."""

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
        """Bans a user and revokes their invite links."""
        await self.bot.ban_chat_member(
            chat_id=settings.CHAT_ID, user_id=user.tg_user_id
        )
        await self.bot.ban_chat_member(
            chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
        )
        user = await self.revoke_user_invite_links(user)

        user.banned = True
        await UsersService().edit_user(
            uow=self.uow, user_id=user.id, user=user, history_entry=history_entry
        )

        if notify_admin:
            await self.admin_notifier.notify_admin(type_=notification_type, user=user)

        return user

    async def revoke_old_user_invite_links(self, user: UserSchema) -> UserSchema:
        """Revokes the invite links for a user if the user is already in the chat/channel."""
        if user.invite_link:
            existing_member = await self.bot.get_chat_member(
                chat_id=settings.CHAT_ID, user_id=user.tg_user_id
            )
            if isinstance(existing_member, ChatMemberMember):
                await self.bot.revoke_chat_invite_link(
                    settings.CHAT_ID, user.invite_link
                )
                user.invite_link = None

        if user.channel_invite_link:
            existing_member = await self.bot.get_chat_member(
                chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
            )
            if isinstance(existing_member, ChatMemberMember):
                await self.bot.revoke_chat_invite_link(
                    settings.CHANNEL_ID, user.channel_invite_link
                )
                user.channel_invite_link = None

        await UsersService().edit_user(uow=self.uow, user_id=user.id, user=user)

    async def revoke_user_invite_links(self, user: UserSchema) -> UserSchema:
        """Revokes the invite links for a user if they exist."""
        if user.invite_link:
            await self.bot.revoke_chat_invite_link(settings.CHAT_ID, user.invite_link)
        if user.channel_invite_link:
            await self.bot.revoke_chat_invite_link(
                settings.CHANNEL_ID, user.channel_invite_link
            )
        user.invite_link = None
        user.channel_invite_link = None
        return user

    async def unban_user(
        self,
        user: UserSchema,
        history_entry: HistorySchemaAdd,
        notify_admin: bool = True,
        notification_type: str = "unban",
        generate_new_invites: bool = True,
    ) -> UserSchema:
        """Unbans a user and generates new invite links for them."""
        user.banned = False
        expire_date = int(time.time()) + 86400  # +1 day from current unix timestamp
        await self.bot.unban_chat_member(
            chat_id=settings.CHAT_ID, user_id=user.tg_user_id
        )
        await self.bot.unban_chat_member(
            chat_id=settings.CHANNEL_ID, user_id=user.tg_user_id
        )
        if generate_new_invites:
            await self.revoke_user_invite_links(user)
            invite = await self.bot.create_chat_invite_link(
                chat_id=settings.CHAT_ID,
                name=user.username,
                member_limit=1,
                expire_date=expire_date,
            )
            invite_channel = await self.bot.create_chat_invite_link(
                chat_id=settings.CHANNEL_ID,
                name=user.username,
                member_limit=1,
                expire_date=expire_date,
            )
            user.invite_link = invite.invite_link
            user.channel_invite_link = invite_channel.invite_link

        await UsersService().edit_user(
            uow=self.uow, user_id=user.id, user=user, history_entry=history_entry
        )

        if notify_admin:
            await self.admin_notifier.notify_admin(type_=notification_type, user=user)

        return user
