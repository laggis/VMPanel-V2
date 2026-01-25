from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from app.models.user import Role

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class UserBase(BaseModel):
    username: str
    is_active: bool = True
    role: Role = Role.USER
    discord_webhook_url: Optional[str] = None
    discord_webhook_public: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserRead(UserBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[Role] = None
    discord_webhook_url: Optional[str] = None
    discord_webhook_public: Optional[str] = None

class VMBase(BaseModel):
    name: str
    vmx_path: str
    owner_id: Optional[int] = None

class VMCreate(VMBase):
    pass

class VMRead(VMBase):
    id: int
    status: Optional[str] = "unknown"
    rdp_ip: str = "remotedesktop.penguinhosting.host"
    rdp_port: int = 3389
    rdp_username: Optional[str] = "Administrator"
    internal_ip: Optional[str] = None
    guest_username: Optional[str] = None
    # Do not return guest_password for security reasons usually, but user needs to see if it's set? 
    # Or maybe return it if they are the owner. For now let's return it so they can edit it.
    guest_password: Optional[str] = None
    expiration_date: Optional[datetime] = None
    
    # Task Tracking
    task_state: Optional[str] = None
    task_progress: int = 0
    task_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class VMUpdate(BaseModel):
    name: Optional[str] = None
    vmx_path: Optional[str] = None
    owner_id: Optional[int] = None
    rdp_ip: Optional[str] = None
    rdp_port: Optional[int] = None
    rdp_username: Optional[str] = None
    internal_ip: Optional[str] = None
    guest_username: Optional[str] = None
    guest_password: Optional[str] = None
    expiration_date: Optional[datetime] = None

class VMStaticIPRequest(BaseModel):
    ip: str
    gateway: str
    dns: List[str] = ["1.1.1.1", "1.0.0.1"]
