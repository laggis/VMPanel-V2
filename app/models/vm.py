from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class VM(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    vmx_path: str = Field(unique=True, max_length=512)
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    expiration_date: Optional[datetime] = Field(default=None)
    
    # RDP Settings
    rdp_ip: str = Field(default="remotedesktop.penguinhosting.host", max_length=255)
    rdp_port: int = Field(default=3389)
    rdp_username: Optional[str] = Field(default="Administrator", max_length=255)

    # Internal Network Settings
    internal_ip: Optional[str] = Field(default=None, max_length=255) # e.g. 192.168.119.151

    # Guest Credentials (for vmrun operations)
    guest_username: Optional[str] = Field(default=None, max_length=255)
    guest_password: Optional[str] = Field(default=None, max_length=255)

    # VNC Settings (for Live Console)
    vnc_port: Optional[int] = Field(default=None)
    vnc_password: Optional[str] = Field(default=None, max_length=8)
    vnc_enabled: bool = Field(default=False)

    # Task Tracking
    task_state: Optional[str] = Field(default=None) # e.g. "reinstalling", "creating_snapshot"
    task_progress: int = Field(default=0) # 0-100
    task_message: Optional[str] = Field(default=None) # e.g. "Stopping VM..."
