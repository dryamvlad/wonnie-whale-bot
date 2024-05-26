from bot.db.models.model_users import UsersORM
from bot.db.utils.repository import SQLAlchemyRepository


class UsersRepository(SQLAlchemyRepository):
    model = UsersORM
