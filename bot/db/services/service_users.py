from bot.db.schemas.schema_users import UserSchema, UserSchemaAdd
from bot.db.schemas.schema_history import HistorySchemaAdd

from bot.db.utils.unitofwork import IUnitOfWork


class UsersService:
    async def add_user(self, uow: IUnitOfWork, user: UserSchemaAdd):
        user_dict = user.model_dump()
        async with uow:
            user_id = await uow.users.add_one(user_dict)
            await uow.commit()
            return user_id

    async def get_users(self, uow: IUnitOfWork) -> list[UserSchema]:
        async with uow:
            users = await uow.users.find_all()
            users = [
                UserSchema.model_validate(user, from_attributes=True) for user in users
            ]
            return users

    async def get_user(self, uow: IUnitOfWork, user_id: int):
        async with uow:
            user = await uow.users.find_one(id=user_id)
            user = UserSchema.model_validate(user, from_attributes=True)
            return user

    async def get_user_by_tg_id(self, uow: IUnitOfWork, tg_user_id: int):
        async with uow:
            user = await uow.users.find_one(tg_user_id=tg_user_id)
            user = UserSchema.model_validate(user, from_attributes=True)
            return user

    async def edit_user(
        self,
        uow: IUnitOfWork,
        user_id: int,
        user: UserSchema,
        history_entry: HistorySchemaAdd = None,
    ):
        user_dict = user.model_dump()
        async with uow:
            await uow.users.edit_one(user_id, user_dict)
            if isinstance(history_entry, HistorySchemaAdd):
                await uow.history.add_one(history_entry.model_dump())
            await uow.commit()
