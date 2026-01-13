import os
import shutil
import psutil
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List
from app.core.database import engine
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
    new_user = User(username=user.username, hashed_password=hashed_pwd, role=user.role, is_active=user.is_active)
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
