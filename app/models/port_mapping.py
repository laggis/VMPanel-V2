from sqlmodel import SQLModel, Field
from typing import Optional

class PortMapping(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    protocol: str = Field(index=True) # 'tcp' or 'udp'
    host_port: int = Field(index=True)
    vm_id: Optional[int] = Field(default=None, foreign_key="vm.id")
    description: Optional[str] = Field(default=None, max_length=255)
