from sqlmodel import SQLModel, Field
from typing import Optional
from enum import Enum

class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=255)
    hashed_password: str
    role: Role = Field(default=Role.USER)
    is_active: bool = Field(default=True)
    discord_webhook_url: Optional[str] = Field(default=None, max_length=512)
    discord_webhook_public: Optional[str] = Field(default=None, max_length=512)
