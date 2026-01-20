from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, BackgroundTasks
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import List
from app.core.database import engine
from app.models.vm import VM
from app.models.user import User, Role
from app.models.audit import AuditLog
from app.schemas import VMRead, VMUpdate
from app.routers.auth import get_current_active_user, get_session
from app.services.vm_service import vm_service
import datetime
import os
import asyncio

router = APIRouter(prefix="/vms", tags=["vms"])

def log_action(user_id: int, action: str, vm_id: int, details: str = None):
    with Session(engine) as session:
        log = AuditLog(user_id=user_id, action=action, vm_id=vm_id, details=details, timestamp=datetime.datetime.utcnow())
        session.add(log)
        session.commit()

@router.get("/", response_model=List[VMRead])
def read_my_vms(
    current_user: User = Depends(get_current_active_user), 
    session: Session = Depends(get_session)
):
    # Admins can see all, regular users only see their assigned VMs
    if current_user.role == Role.ADMIN:
        vms = session.exec(select(VM)).all()
    else:
        vms = session.exec(select(VM).where(VM.owner_id == current_user.id)).all()
    
    results = []
    # Optimization: Get running VMs once
    try:
        running_vms = vm_service.list_running_vms()
    except Exception as e:
        print(f"Error listing VMs: {e}")
        running_vms = []
        
    for vm in vms:
        # Check if path is in running list
        # Normalize path for comparison as running_vms are lowercased and normalized
        is_running = False
        if vm.vmx_path:
            normalized_vm_path = os.path.normpath(vm.vmx_path).lower()
            is_running = normalized_vm_path in running_vms
            
        status_str = "running" if is_running else "stopped"
        vm_read = VMRead.from_orm(vm)
        vm_read.status = status_str
        results.append(vm_read)
        
    return results

@router.post("/{vm_id}/start")
def start_vm(
    vm_id: int, 
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
         raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        # Ensure VNC is configured
        if not vm.vnc_port:
            vm.vnc_port = 5900 + vm.id
            vm.vnc_enabled = True
            # No password for now to keep it simple, or generate one
            # vm.vnc_password = "password" 
            session.add(vm)
            session.commit()
            
        # Apply to VMX (only updates file, needs restart to take effect if changed)
        vm_service.enable_vnc(vm.vmx_path, vm.vnc_port, vm.vnc_password)

        vm_service.start_vm(vm.vmx_path)
        log_action(current_user.id, "start", vm_id)
        return {"message": "VM started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/stop")
def stop_vm(
    vm_id: int, 
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
         raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        vm_service.stop_vm(vm.vmx_path)
        log_action(current_user.id, "stop", vm_id)
        return {"message": "VM stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/restart")
def restart_vm(
    vm_id: int, 
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
         raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        vm_service.restart_vm(vm.vmx_path)
        log_action(current_user.id, "restart", vm_id)
        return {"message": "VM restarted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{vm_id}/ip")
def get_vm_ip(
    vm_id: int, 
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check if running
    if not vm_service.is_running(vm.vmx_path):
        return {"ip": "VM is stopped"}

    try:
        ip = vm_service.get_guest_ip(
            vm.vmx_path, 
            guest_user=vm.guest_username,
            guest_pass=vm.guest_password
        )
        return {"ip": ip}
    except Exception as e:
        return {"ip": "Error fetching IP"}

@router.get("/{vm_id}/screenshot")
def get_vm_screenshot(
    vm_id: int, 
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check if running
    if not vm_service.is_running(vm.vmx_path):
        raise HTTPException(status_code=400, detail="VM is not running")

    try:
        # Define path for screenshot
        # Use timestamp to avoid caching issues in browser if we re-request
        import os
        from fastapi.responses import FileResponse
        
        filename = f"vm_{vm_id}_screenshot.png"
        file_path = os.path.join("app", "static", "screenshots", filename)
        
        # Capture
        try:
            vm_service.capture_screen(
                vm.vmx_path, 
                os.path.abspath(file_path),
                guest_user=vm.guest_username,
                guest_pass=vm.guest_password
            )
            return FileResponse(file_path, media_type="image/png")
        except Exception as e:
            # If capture fails (e.g. no guest tools), return a placeholder or specific error
            # For now, let's log it and raise a more friendly error
            print(f"Screenshot failed: {e}")
            detail_msg = "Screenshot failed. Ensure VMware Tools are installed and VM is fully booted."
            if "Anonymous guest operations are not allowed" in str(e):
                detail_msg = "Guest credentials required. Please update them in Settings."
            elif "Invalid user name or password" in str(e):
                detail_msg = "Invalid Guest Credentials. Please verify username and password in Settings."
            
            raise HTTPException(status_code=503, detail=detail_msg)
            
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/rdp")
def update_rdp_settings(
    vm_id: int, 
    vm_update: VMUpdate,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if vm_update.rdp_ip is not None:
        vm.rdp_ip = vm_update.rdp_ip
    if vm_update.rdp_port is not None:
        vm.rdp_port = vm_update.rdp_port
    if vm_update.rdp_username is not None:
        vm.rdp_username = vm_update.rdp_username
    if vm_update.guest_username is not None:
        vm.guest_username = vm_update.guest_username
    if vm_update.guest_password is not None:
        vm.guest_password = vm_update.guest_password
        
    session.add(vm)
    session.commit()
    session.refresh(vm)
    return {"message": "Settings updated"}

@router.get("/{vm_id}/rdp/download")
def download_rdp(
    vm_id: int, 
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Generate RDP content
    rdp_content = f"""
full address:s:{vm.rdp_ip}:{vm.rdp_port}
username:s:{vm.rdp_username or 'Administrator'}
screen mode id:i:2
session bpp:i:32
compression:i:1
keyboardhook:i:2
audiomode:i:0
redirectclipboard:i:1
redirectprinters:i:0
redirectcomports:i:0
redirectsmartcards:i:0
displayconnectionbar:i:1
autoreconnection enabled:i:1
authentication level:i:2
prompt for credentials:i:1
negotiate security layer:i:1
remoteapplicationmode:i:0
alternate shell:s:
shell working directory:s:
disable wallpaper:i:0
disable full window drag:i:0
allow desktop composition:i:0
allow font smoothing:i:0
disable menu anims:i:0
disable themes:i:0
disable cursor setting:i:0
bitmapcachepersistenable:i:1
winposstr:s:0,1,0,0,800,600
    """.strip()
    
    headers = {
        'Content-Disposition': f'attachment; filename="{vm.name}.rdp"'
    }
    return Response(content=rdp_content, media_type='application/x-rdp', headers=headers)

@router.get("/{vm_id}/snapshots")
def list_snapshots(
    vm_id: int, 
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    try:
        snapshots = vm_service.list_snapshots(vm.vmx_path)
        return snapshots
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/snapshots")
def create_snapshot(
    vm_id: int, 
    name: str,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    try:
        vm_service.create_snapshot(vm.vmx_path, name)
        log_action(current_user.id, "snapshot_create", vm_id, f"Created snapshot: {name}")
        return {"message": "Snapshot created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/snapshots/revert")
def revert_snapshot(
    vm_id: int, 
    name: str,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    try:
        vm_service.revert_snapshot(vm.vmx_path, name)
        log_action(current_user.id, "snapshot_revert", vm_id, f"Reverted to snapshot: {name}")
        return {"message": "Reverted to snapshot"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{vm_id}/snapshots")
def delete_snapshot(
    vm_id: int, 
    name: str,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    try:
        vm_service.delete_snapshot(vm.vmx_path, name)
        log_action(current_user.id, "snapshot_delete", vm_id, f"Deleted snapshot: {name}")
        return {"message": "Snapshot deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ChangePasswordRequest(BaseModel):
    new_password: str

@router.post("/{vm_id}/change_password")
def change_guest_password(
    vm_id: int, 
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check if VM is running
    if not vm_service.is_running(vm.vmx_path):
         raise HTTPException(status_code=400, detail="VM must be running to change password")

    # Check if we have current credentials
    if not vm.guest_username or not vm.guest_password:
        raise HTTPException(status_code=400, detail="Current guest credentials (username/password) are missing in Settings. Please set them first.")

    try:
        # Change password in Guest
        vm_service.change_guest_password(
            vm.vmx_path, 
            vm.guest_username, 
            payload.new_password, 
            vm.guest_username, 
            vm.guest_password
        )
        
        # Update DB with new password
        vm.guest_password = payload.new_password
        session.add(vm)
        session.commit()
        
        log_action(current_user.id, "change_password", vm_id, "Changed guest password")
        return {"message": "Password changed successfully in VM and database"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/{vm_id}/vnc")
async def vnc_proxy(
    websocket: WebSocket,
    vm_id: int,
    session: Session = Depends(get_session),
):
    await websocket.accept()

    vm = session.get(VM, vm_id)
    if not vm or not vm.vnc_port:
        await websocket.close(code=1000)
        return

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", vm.vnc_port)
    except Exception as e:
        print(f"Failed to connect to VNC: {e}")
        await websocket.close(code=1011)
        return

    async def forward_client_to_vnc():
        try:
            while True:
                data = await websocket.receive_bytes()
                writer.write(data)
                await writer.drain()
        except Exception:
            pass

    async def forward_vnc_to_client():
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass

    try:
        await asyncio.gather(forward_client_to_vnc(), forward_vnc_to_client())
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
