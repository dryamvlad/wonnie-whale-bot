import datetime
from typing import Annotated, Optional

from sqlalchemy import func
from sqlalchemy.orm import mapped_column


intpk = Annotated[int, mapped_column(primary_key=True)]
created_at = Annotated[datetime.datetime, mapped_column(default=func.now())]
updated_at = Annotated[
    datetime.datetime, mapped_column(default=func.now(), onupdate=func.now())
]
