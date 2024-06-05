from typing import Optional
from pydantic import BaseModel
from sqlalchemy import BigInteger


class UserSchemaAdd(BaseModel):
    username: str
    balance: int
    blacklisted: bool
    banned: bool
    invite_link: str
    channel_invite_link: Optional[str] = None
    wallet: str
    tg_user_id: int
    entry_balance: int
    og: bool

    class Config:
        from_attributes = True


class UserSchema(UserSchemaAdd):
    id: int
