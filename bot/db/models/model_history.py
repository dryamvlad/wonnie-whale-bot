from sqlalchemy import BigInteger, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.db import Base
from bot.db.models._common import *


class HistoryORM(Base):
    __tablename__ = "history"

    id: Mapped[intpk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    balance_delta: Mapped[int]
    volume: Mapped[Optional[int]]
    price: Mapped[float]
    wallet: Mapped[Optional[str]]

    user: Mapped["UsersORM"] = relationship(
        back_populates="history",
    )

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]
