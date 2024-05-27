from sqlalchemy import BigInteger, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.db import Base
from bot.db.models._common import *


class UsersORM(Base):
    __tablename__ = "users"

    id: Mapped[intpk]
    username: Mapped[Optional[str]]
    chat_id = mapped_column(BigInteger, unique=True)
    balance: Mapped[int]
    blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_link: Mapped[Optional[str]]
    wallet: Mapped[str]

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]
