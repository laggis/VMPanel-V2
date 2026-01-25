import secrets
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "VM Control Panel"
    # Default to a local MySQL server.
    # Format: mysql+pymysql://<user>:<password>@<host>:<port>/<db_name>
    DATABASE_URL: str = "mysql+pymysql://vm_control:vm_control@localhost:3307/vm_control"
    
    # CRITICAL: This key MUST be static. If it changes, the deterministic service account passwords will change,
    # and the system will lose access to existing VMs.
    SECRET_KEY: str = ""
    
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    VMRUN_PATH: str = r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
    # Placeholder - User must update this!
    DISCORD_WEBHOOK_URL: str = ""
    
    # Base Snapshot Credentials (Used to bootstrap the VM after reinstall)
    # IMPORTANT: You must create this user/password on your "Base" snapshot!
    BASE_SNAPSHOT_USER: str = "Administrator" 
    BASE_SNAPSHOT_PASSWORD: str = "Kossa123" # Default password for the Base snapshot
    

    # Template Provisioning
    # Path to the "Master" VM to clone from
    TEMPLATE_VM_PATH: str = r"C:\Virtual Machines\Templates\Master-Windows.vmx"
    # Name of the snapshot to clone from (Required for Linked Clones)
    TEMPLATE_SNAPSHOT_NAME: str = "Base-v2"
    # Directory where new Customer VMs will be created
    VM_STORAGE_PATH: str = r"C:\Virtual Machines"

    class Config:
        env_file = ".env"

settings = Settings()
