from bot.db.models.model_history import HistoryORM
from bot.db.utils.repository import SQLAlchemyRepository


class HistoryRepository(SQLAlchemyRepository):
    model = HistoryORM
