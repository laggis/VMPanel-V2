import secrets
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "VM Control Panel"
    # Default to a local MySQL server.
    # Format: mysql+pymysql://<user>:<password>@<host>:<port>/<db_name>
    DATABASE_URL: str = "mysql+pymysql://vm_control:vm_control@localhost:3307/vm_control"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    VMRUN_PATH: str = r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
    DISCORD_WEBHOOK_URL: str = ""  # Add your Discord Webhook URL here

    class Config:
        env_file = ".env"

settings = Settings()
