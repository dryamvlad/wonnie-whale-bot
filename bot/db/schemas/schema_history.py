from pydantic import BaseModel
from sqlalchemy import BigInteger


class HistorySchemaAdd(BaseModel):
    user_id: int
    balance_delta: int
    price: float
    wallet: str

    class Config:
        from_attributes = True


class UserSchema(HistorySchemaAdd):
    id: int
