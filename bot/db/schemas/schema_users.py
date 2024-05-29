from pydantic import BaseModel
from sqlalchemy import BigInteger


class UserSchemaAdd(BaseModel):
    username: str
    balance: int
    blacklisted: bool
    banned: bool
    invite_link: str
    wallet: str
    tg_user_id: int
    entry_balance: int

    class Config:
        from_attributes = True


class UserSchema(UserSchemaAdd):
    id: int
