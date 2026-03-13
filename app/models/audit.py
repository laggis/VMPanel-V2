from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    action: str
    vm_id: Optional[int] = Field(default=None, foreign_key="vm.id")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Optional[str] = None
