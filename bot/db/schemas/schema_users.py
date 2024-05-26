from pydantic import BaseModel
from sqlalchemy import BigInteger


class UserSchemaAdd(BaseModel):
    username: str
    chat_id: int
    username: str
    chat_id: int
    balance: int
    blacklisted: bool
    banned: bool
    invite_link: str

    class Config:
        from_attributes = True


class UserSchema(UserSchemaAdd):
    id: int
