import os
import shutil
import psutil
import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List
from pydantic import BaseModel
from fastapi.concurrency import run_in_threadpool
from app.core.database import engine
from app.core.config import settings
from app.services.vm_service import vm_service
from app.models.user import User, Role
from app.models.vm import VM
from app.models.audit import AuditLog
from app.schemas import UserCreate, UserRead, UserUpdate, VMCreate, VMRead, VMUpdate
from app.core.security import get_password_hash
from app.routers.auth import get_current_admin_user, get_session

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_admin_user)])

@router.get("/stats")
async def get_system_stats():
    """
    Returns system statistics (CPU, RAM, Disk).
    """
    cpu_percent = psutil.cpu_percent(interval=None)
    
    # RAM
    mem = psutil.virtual_memory()
    ram_total_gb = round(mem.total / (1024**3), 2)
    ram_used_gb = round(mem.used / (1024**3), 2)
    ram_percent = mem.percent
    
    # Disk (Usage of the drive where CWD is)
    disk = psutil.disk_usage('.')
    disk_total_gb = round(disk.total / (1024**3), 2)
    disk_used_gb = round(disk.used / (1024**3), 2)
    disk_percent = disk.percent
    
    # Network
    net = psutil.net_io_counters()
    
    return {
        "cpu": cpu_percent,
        "ram": {
            "total": ram_total_gb,
            "used": ram_used_gb,
            "percent": ram_percent
        },
        "disk": {
            "total": disk_total_gb,
            "used": disk_used_gb,
            "percent": disk_percent
        },
        "net": {
            "sent": net.bytes_sent,
            "recv": net.bytes_recv
        }
    }

@router.get("/audit_logs", response_model=List[AuditLog])
async def read_audit_logs(session: Session = Depends(get_session)):
    logs = session.exec(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(100)).all()
    return logs

@router.get("/scan_vms")
async def scan_vms():
    """
    Scans common directories for .vmx files.
    """
    # Common directories to search
    search_roots = [
        r"C:\Virtual Machines",
        os.path.expanduser(r"~\Documents\Virtual Machines"),
        r"D:\Virtual Machines"
    ]
    
    found_vms = []
    
    for root_dir in search_roots:
        if os.path.exists(root_dir):
            for root, dirs, files in os.walk(root_dir):
                for file in files:
                    if file.lower().endswith(".vmx"):
                        found_vms.append(os.path.join(root, file))
    
    # Remove duplicates and sort
    return {"paths": sorted(list(set(found_vms)))}

# Users
@router.post("/users", response_model=UserRead)
async def create_user(user: UserCreate, session: Session = Depends(get_session)):
    db_user = session.exec(select(User).where(User.username == user.username)).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_pwd = get_password_hash(user.password)
    new_user = User(
        username=user.username, 
        hashed_password=hashed_pwd, 
        role=user.role, 
        is_active=user.is_active,
        discord_webhook_url=user.discord_webhook_url
    )
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    return new_user

@router.get("/users", response_model=List[UserRead])
async def read_users(session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()
    return users

@router.put("/users/{user_id}", response_model=UserRead)
async def update_user(user_id: int, user_update: UserUpdate, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_data = user_update.dict(exclude_unset=True)
    if "username" in user_data:
        existing_user = session.exec(select(User).where(User.username == user_data["username"])).first()
        if existing_user and existing_user.id != user_id:
            raise HTTPException(status_code=400, detail="Username already registered")

    if "password" in user_data and user_data["password"]:
        user_data["hashed_password"] = get_password_hash(user_data["password"])
        del user_data["password"]
        
    for key, value in user_data.items():
        setattr(user, key, value)
    
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Unassign VMs owned by this user
    vms = session.exec(select(VM).where(VM.owner_id == user_id)).all()
    for vm in vms:
        vm.owner_id = None
        session.add(vm)
        
    session.delete(user)
    session.commit()
    return None

@router.get("/vms/{vm_id}/guest_ip")
async def get_vm_guest_ip_admin(
    vm_id: int,
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
        
    try:
        ip = await run_in_threadpool(vm_service.get_guest_ip, vm.vmx_path, vm.guest_username, vm.guest_password)
        return {"ip": ip}
    except Exception as e:
        return {"ip": ""}

# VMs
@router.post("/vms", response_model=VMRead)
async def create_vm(vm: VMCreate, session: Session = Depends(get_session)):
    db_vm = session.exec(select(VM).where(VM.vmx_path == vm.vmx_path)).first()
    if db_vm:
        raise HTTPException(status_code=400, detail="VM path already registered")
    
    new_vm = VM.from_orm(vm)
    session.add(new_vm)
    session.commit()
    session.refresh(new_vm)
    return new_vm

@router.get("/vms", response_model=List[VMRead])
async def read_all_vms(session: Session = Depends(get_session)):
    vms = session.exec(select(VM)).all()
    return vms

@router.put("/vms/{vm_id}", response_model=VMRead)
async def update_vm(vm_id: int, vm_update: VMUpdate, session: Session = Depends(get_session)):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    
    vm_data = vm_update.dict(exclude_unset=True)
    for key, value in vm_data.items():
        setattr(vm, key, value)
    
    session.add(vm)
    session.commit()
    session.refresh(vm)
    return vm

@router.delete("/vms/{vm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vm(vm_id: int, session: Session = Depends(get_session)):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    
    # Unlink audit logs before deleting VM to avoid foreign key constraint error
    audit_logs = session.exec(select(AuditLog).where(AuditLog.vm_id == vm_id)).all()
    for log in audit_logs:
        log.vm_id = None
        if log.details:
            log.details += f" (VM {vm.name} deleted)"
        else:
            log.details = f"VM {vm.name} deleted"
        session.add(log)
    
    session.delete(vm)
    session.commit()
    return None


class VMProvision(BaseModel):
    name: str
    owner_id: int
    clone_type: str = "full" # 'full' or 'linked'
    cpu_cores: int = 2
    ram_mb: int = 4096

@router.post("/vms/provision", response_model=VMRead)
async def provision_vm(
    provision: VMProvision, 
    current_user: User = Depends(get_current_admin_user),
    session: Session = Depends(get_session)
):
    # 1. Check Template
    if not os.path.exists(settings.TEMPLATE_VM_PATH):
        raise HTTPException(status_code=500, detail=f"Template VM not found at {settings.TEMPLATE_VM_PATH}")
    
    # 2. Check Owner
    owner = session.get(User, provision.owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")

    # 3. Prepare Paths
    # Sanitize name for folder
    safe_name = "".join(c for c in provision.name if c.isalnum() or c in (' ', '-', '_')).strip()
    if not safe_name:
        safe_name = "VM-New"
        
    dest_dir = os.path.join(settings.VM_STORAGE_PATH, safe_name)
    dest_vmx = os.path.join(dest_dir, f"{safe_name}.vmx")
    
    if os.path.exists(dest_vmx):
        raise HTTPException(status_code=400, detail="VM with this name/path already exists")
        
    # 4. Clone (Async/Threadpool)
    try:
        # Create storage dir if not exists
        os.makedirs(settings.VM_STORAGE_PATH, exist_ok=True)
        
        await run_in_threadpool(
            vm_service.clone_vm, 
            settings.TEMPLATE_VM_PATH, 
            dest_vmx, 
            safe_name, 
            provision.clone_type,
            settings.TEMPLATE_SNAPSHOT_NAME
        )

        # 4.5 Update Specs (CPU/RAM)
        await run_in_threadpool(
            vm_service.update_specs,
            dest_vmx,
            provision.cpu_cores,
            provision.ram_mb
        )
        
        # Create Base Snapshot for future reinstalls
        await run_in_threadpool(
            vm_service.create_snapshot,
            dest_vmx,
            settings.TEMPLATE_SNAPSHOT_NAME
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cloning failed: {e}")
        
    # 5. Register in DB
    new_vm = VM(
        name=provision.name,
        vmx_path=dest_vmx,
        owner_id=provision.owner_id,
        # status="stopped" (default in model?)
    )
    # Ensure status is set if model doesn't default
    # new_vm.status = "stopped" 
    
    session.add(new_vm)
    session.commit()
    session.refresh(new_vm)
    
    # 6. Log
    log = AuditLog(
        user_id=current_user.id,
        action="provision",
        vm_id=new_vm.id,
        details=f"Provisioned for user {owner.username} from template ({provision.clone_type})",
        timestamp=datetime.datetime.utcnow()
    )
    session.add(log)
    session.commit()
    
    return new_vm
