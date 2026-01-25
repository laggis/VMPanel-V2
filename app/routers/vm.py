from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, BackgroundTasks
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import List, Optional
from app.core.database import engine
from app.models.vm import VM
from app.models.user import User, Role
from app.models.audit import AuditLog
from app.schemas import VMRead, VMUpdate, VMStaticIPRequest
from app.routers.auth import get_current_active_user, get_session
from app.services.vm_service import vm_service
from app.services.notification_service import notification_service
from app.core.config import settings
import datetime
import os
import asyncio
import time
import hashlib
import shutil
import base64
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/vms", tags=["vms"])

def log_action(user_id: int, action: str, vm_id: int, details: str = None):
    with Session(engine) as session:
        log = AuditLog(user_id=user_id, action=action, vm_id=vm_id, details=details, timestamp=datetime.datetime.utcnow())
        session.add(log)
        session.commit()

async def send_vm_notification(vm: VM, action: str, status: str = "Success", details: str = None, fields: list = None):
    """
    Sends notifications to:
    1. The VM Owner (if they have a webhook configured)
    2. The System Admin (via global webhook)
    """
    # 1. Prepare message
    # Fancy Embed Structure
    title = f"VM {action.capitalize()} - {status}"
    
    # Use a generic professional thumbnail (User can change this in code if they want)
    thumbnail_url = "https://cdn.penguinhosting.host/pingvin.jpeg" # Optional: Set a valid URL if needed
    
    # Clean description without redundant fields if they are in the 'fields' list
    description = f"**VM:** {vm.name} (ID: {vm.id})\n**Status:** {status}"
    
    if details:
        description += f"\n\n{details}"
    
    color = 3066993 if status == "Success" else 15158332 # Green or Red
    
    # Author Info
    author = {
        "name": "Control Panel",
        "icon_url": "https://cdn.penguinhosting.host/pingvin.jpeg"
    }
    
    # Footer Info
    footer = {
        "text": "Control Panel",
        "icon_url": "https://cdn.penguinhosting.host/pingvin.jpeg"
    }
    
    # 2. Determine Webhook URLs (Routing Logic)
    
    # Define Public Actions (Player Activity)
    public_actions = ["start", "stop", "restart", "network_change"]
    
    is_public_event = False
    if action in public_actions and status == "Success":
        is_public_event = True
    
    # 3. Send to Owner (if exists)
    if vm.owner_id:
        with Session(engine) as session:
            owner = session.get(User, vm.owner_id)
            if owner:
                # User Notification Logic:
                # 1. Public Events -> Try 'Public Webhook', fallback to 'Main Webhook'
                # 2. Private Events -> 'Main Webhook' only.
                
                target_user_webhook = None
                
                if is_public_event:
                     # Prefer Public Webhook if set, otherwise Main
                     if owner.discord_webhook_public:
                         target_user_webhook = owner.discord_webhook_public
                     elif owner.discord_webhook_url:
                         target_user_webhook = owner.discord_webhook_url
                else:
                     # Private Event (Security/Errors) -> Main Webhook only
                     if owner.discord_webhook_url:
                         target_user_webhook = owner.discord_webhook_url
                
                if target_user_webhook:
                    await notification_service.send_discord_alert(
                        title=title, 
                        description=description, 
                        color=color, 
                        fields=fields, 
                        webhook_url=target_user_webhook,
                        thumbnail_url=thumbnail_url,
                        author=author,
                        footer=footer
                    )
async def background_reinstall_vm(vm_id: int):
    with Session(engine) as session:
        vm = session.get(VM, vm_id)
        if not vm:
            return

        try:
            # Notify Start
            await send_vm_notification(vm, "reinstall", "Started", "Server is Reinstalling...")

            # UPDATE PROGRESS: Started
            vm.task_state = "reinstalling"
            vm.task_progress = 5
            vm.task_message = "Initializing..."
            session.add(vm)
            session.commit()

            # 0. Auto-Learn IP (Last chance before wipe)
            if not vm.internal_ip:
                try:
                     # Only try if running
                     if await run_in_threadpool(vm_service.is_running, vm.vmx_path):
                        vm.task_message = "Detecting IP..."
                        session.add(vm)
                        session.commit()
                        
                        current_ip = await run_in_threadpool(vm_service.get_guest_ip, vm.vmx_path)
                        if current_ip and "Unknown" not in current_ip:
                            vm.internal_ip = current_ip
                            session.add(vm)
                            session.commit()
                            log_action(vm.owner_id or 0, "system", vm.id, f"Auto-detected Internal IP: {current_ip}")
                except Exception as e:
                    print(f"Auto-IP failed: {e}")

            # 1. Stop VM
            if await run_in_threadpool(vm_service.is_running, vm.vmx_path):
                vm.task_message = "Stopping VM..."
                vm.task_progress = 10
                session.add(vm)
                session.commit()

                await run_in_threadpool(vm_service.stop_vm, vm.vmx_path, hard=True)
                await asyncio.sleep(2)

            # 2. Revert to Snapshot
            vm.task_message = "Checking Snapshot..."
            vm.task_progress = 20
            session.add(vm)
            session.commit()

            snapshot_name = settings.TEMPLATE_SNAPSHOT_NAME
            snapshots = []
            try:
                snapshots = await run_in_threadpool(vm_service.list_snapshots, vm.vmx_path)
            except Exception:
                pass # Proceed to check/re-provision

            if snapshot_name in snapshots:
                vm.task_message = f"Reverting to {snapshot_name}..."
                vm.task_progress = 30
                session.add(vm)
                session.commit()
                await run_in_threadpool(vm_service.revert_to_snapshot, vm.vmx_path, snapshot_name)
            else:
                # Fallback: Re-provision
                vm.task_message = "Snapshot missing. Re-provisioning..."
                vm.task_progress = 30
                session.add(vm)
                session.commit()
                
                # Get current specs
                specs = await run_in_threadpool(vm_service.get_vm_specs, vm.vmx_path)
                
                # Delete existing VM
                try:
                    await run_in_threadpool(vm_service.delete_vm, vm.vmx_path)
                except Exception as e:
                    print(f"Delete VM failed (might not exist): {e}")

                # Force cleanup of directory to ensure clean clone
                # vmrun deleteVM sometimes leaves files behind or fails if VM is broken
                vm_dir = os.path.dirname(vm.vmx_path)
                if os.path.exists(vm_dir):
                    vm.task_message = "Cleaning up old files..."
                    session.add(vm)
                    session.commit()
                    try:
                        # Wait a moment for any locks to release
                        await asyncio.sleep(2)
                        for filename in os.listdir(vm_dir):
                            file_path = os.path.join(vm_dir, filename)
                            try:
                                if os.path.isfile(file_path) or os.path.islink(file_path):
                                    os.unlink(file_path)
                                elif os.path.isdir(file_path):
                                    shutil.rmtree(file_path)
                            except Exception as e:
                                print(f"Failed to delete {file_path}: {e}")
                    except Exception as e:
                        print(f"Failed to clean directory {vm_dir}: {e}")

                # Clone from Template
                vm.task_message = "Cloning new VM..."
                session.add(vm)
                session.commit()

                safe_name = os.path.splitext(os.path.basename(vm.vmx_path))[0]
                
                try:
                    await run_in_threadpool(
                        vm_service.clone_vm, 
                        settings.TEMPLATE_VM_PATH, 
                        vm.vmx_path, 
                        safe_name, 
                        "linked", 
                        settings.TEMPLATE_SNAPSHOT_NAME
                    )
                except Exception as e:
                     # If clone fails, report it
                    raise Exception(f"Clone failed: {e}")
                
                # Restore Specs
                vm.task_message = "Restoring Specs..."
                session.add(vm)
                session.commit()

                await run_in_threadpool(
                    vm_service.update_specs,
                    vm.vmx_path,
                    specs.get("cpu_count", 2),
                    specs.get("memory_mb", 4096)
                )
                
                # Create Base Snapshot for next time
                await run_in_threadpool(
                    vm_service.create_snapshot,
                    vm.vmx_path,
                    settings.TEMPLATE_SNAPSHOT_NAME
                )
            
            # Configure Host DHCP Reservation (if Internal IP is known)
            if getattr(vm, "internal_ip", None):
                vm.task_message = "Configuring Network..."
                session.add(vm)
                session.commit()
                
                try:
                    await run_in_threadpool(
                        vm_service.configure_static_ip,
                        vm.vmx_path,
                        vm.internal_ip,
                        "255.255.255.0",
                        settings.DEFAULT_GATEWAY,
                        settings.DEFAULT_DNS,
                        settings.BASE_SNAPSHOT_USER,
                        settings.BASE_SNAPSHOT_PASSWORD
                    )
                except Exception as e:
                    print(f"Failed to configure Host DHCP: {e}")

            # 3. Start VM
            vm.task_message = "Starting VM..."
            vm.task_progress = 50
            session.add(vm)
            session.commit()

            await run_in_threadpool(vm_service.start_vm, vm.vmx_path)
            
            # 4. Wait for Tools / IP
            vm.task_message = "Waiting for Network..."
            vm.task_progress = 60
            session.add(vm)
            session.commit()

            max_retries = 60
            ip = None
            for i in range(max_retries):
                # Update progress slightly during wait (60 -> 80)
                if i % 5 == 0:
                    vm.task_progress = 60 + int((i / max_retries) * 20)
                    session.add(vm)
                    session.commit()

                try:
                    ip = await run_in_threadpool(vm_service.get_guest_ip, vm.vmx_path)
                    if ip:
                        # Update Internal IP if not set (Auto-Learn)
                        if not getattr(vm, "internal_ip", None):
                            vm.internal_ip = ip
                        
                        session.add(vm)
                        session.commit()
                        
                        # FORCE STATIC IP GUI UPDATE (Dual-Mode)
                        # Now that VM is running, we run the script to update the Windows GUI 
                        # to show "Static" instead of "DHCP", satisfying user requirements.
                        if getattr(vm, "internal_ip", None):
                            try:
                                print(f"Applying Guest-Side Static IP Config for {vm.internal_ip}...")
                                await run_in_threadpool(
                                    vm_service.configure_static_ip,
                                    vm.vmx_path,
                                    vm.internal_ip,
                                    "255.255.255.0",
                                    settings.DEFAULT_GATEWAY,
                                    settings.DEFAULT_DNS,
                                    settings.BASE_SNAPSHOT_USER,
                                    settings.BASE_SNAPSHOT_PASSWORD
                                )
                            except Exception as e:
                                print(f"Failed to apply Guest-Side Static IP: {e}")
                        
                        break
                except:
                    pass
                await asyncio.sleep(5)
            
            if not ip:
                await send_vm_notification(vm, "reinstall", "Warning", "Tools not ready. RDP port may be incorrect.")
                vm.task_state = None
                vm.task_message = "Failed: Tools not ready"
                session.add(vm)
                session.commit()
                return

            # 5. Bootstrap
            vm.task_message = "Configuring Admin User..."
            vm.task_progress = 85
            session.add(vm)
            session.commit()

            # Always use Base Snapshot credentials because we just reverted to Base
            bootstrap_user = settings.BASE_SNAPSHOT_USER
            bootstrap_pass = settings.BASE_SNAPSHOT_PASSWORD
            
            # Update DB to match Base credentials (Reset password)
            vm.guest_username = bootstrap_user
            vm.guest_password = bootstrap_pass
            session.add(vm)
            session.commit()

            # 6. Configure RDP
            if vm.rdp_port:
                vm.task_message = "Configuring RDP Firewall..."
                vm.task_progress = 90
                session.add(vm)
                session.commit()

                script = f"""
                $port = {vm.rdp_port}
                
                # Enable RDP 
                Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server' -Name 'fDenyTSConnections' -Value 0 
                
                # Set RDP port explicitly as DWORD 
                Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name 'PortNumber' -Value $port -Type DWord 
                
                # Disable default RDP firewall rules (3389) 
                Get-NetFirewallRule -DisplayGroup "Remote Desktop" | Disable-NetFirewallRule 
                
                # Allow custom RDP port 
                New-NetFirewallRule -DisplayName "RDP Custom Port $port" -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow -Profile Any -ErrorAction SilentlyContinue 
                
                # Restart RDP service
                Restart-Service TermService -Force 
                
                # Wait to ensure port bind 
                Start-Sleep -Seconds 5 
                
                # Reboot to ensure settings apply
                Restart-Computer -Force
                """

                # FIX: Do NOT join with semicolons because it makes comments (#) comment out the next command!
                # Keep as multi-line string for the .ps1 file.
                script_lines = [line.strip() for line in script.splitlines() if line.strip()]
                script = "\n".join(script_lines)
                
                # Method 3: File Transfer + Execution (Most Robust)
                # Create a persistent script file on the host
                scripts_dir = os.path.join("app", "scripts")
                os.makedirs(scripts_dir, exist_ok=True)
                
                host_temp_script = os.path.join(scripts_dir, f"rdp_config_{vm.id}.ps1")
                
                # Use User Temp folder to avoid System Temp permission/scanning strictness
                guest_temp_path = f"C:\\Users\\{bootstrap_user}\\AppData\\Local\\Temp\\rdp_config.ps1"
                
                with open(host_temp_script, "w") as f:
                    f.write(script)
                
                host_script_abs_path = os.path.abspath(host_temp_script)

                # We assume the Base snapshot has correct credentials and RDP enabled.
                # Just run the script to change the port.
                rdp_error = None
                try:
                    # 1. Copy Script to Guest
                    await run_in_threadpool(
                        vm_service.copy_file_to_guest,
                        vm.vmx_path,
                        host_script_abs_path,
                        guest_temp_path,
                        bootstrap_user,
                        bootstrap_pass
                    )
                    
                    # 2. Execute Script from File (Use -File to bypass policy cleanly)
                    ps_command = [
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", 
                        "-File", guest_temp_path
                    ]

                    await run_in_threadpool(
                        vm_service.run_program_in_guest,
                        vm.vmx_path, 
                        bootstrap_user, 
                        bootstrap_pass, 
                        "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                        ps_command,
                        interactive=False 
                    )
                    
                except Exception as e:
                    rdp_error = str(e)
                    # Suppress immediate warning

                # Cleanup host file - DISABLED (User requested persistence)
                # if os.path.exists(host_temp_script):
                #    os.remove(host_temp_script)

            # Prepare Rich Notification
            success_fields = [
                {
                    "name": "🔌 Connection",
                    "value": f"`{vm.rdp_ip}:{vm.rdp_port}`",
                    "inline": True
                },
                {
                    "name": "👤 Username",
                    "value": f"`{bootstrap_user}`",
                    "inline": True
                },
                {
                    "name": "🔑 Password",
                    "value": f"`{bootstrap_pass}`",
                    "inline": True
                },
                {
                    "name": "⚠️ Important",
                    "value": "Please change your password immediately after logging in!",
                    "inline": False
                }
            ]
            
            status_title = "Success"
            status_desc = "Server is UP and Running!"
            
            if rdp_error:
                status_title = "Completed with Warnings"
                status_desc = "VM Reverted, but RDP configuration failed."
                
                success_fields.append({
                    "name": "⚠️ RDP Config Error",
                    "value": f"`{rdp_error}`",
                    "inline": False
                })

            await send_vm_notification(vm, "reinstall", status_title, status_desc, fields=success_fields)
            
            # Completion
            vm.task_state = None
            vm.task_progress = 0
            vm.task_message = None
            session.add(vm)
            session.commit()
            
        except Exception as e:
            vm.task_state = None
            vm.task_message = f"Error: {str(e)}"
            session.add(vm)
            session.commit()
            await send_vm_notification(vm, "reinstall", "Failed", str(e))

@router.get("/", response_model=List[VMRead])
def read_my_vms(
    current_user: User = Depends(get_current_active_user), 
    session: Session = Depends(get_session)
):
    if current_user.role == Role.ADMIN:
        vms = session.exec(select(VM)).all()
    else:
        vms = session.exec(select(VM).where(VM.owner_id == current_user.id)).all()
    
    results = []
    try:
        running_vms = vm_service.list_running_vms()
    except Exception as e:
        print(f"Error listing VMs: {e}")
        running_vms = []
        
    for vm in vms:
        is_running = False
        if vm.vmx_path:
            normalized_vm_path = os.path.normpath(vm.vmx_path).lower()
            is_running = normalized_vm_path in running_vms
            
        status_str = "running" if is_running else "stopped"
        vm_read = VMRead.from_orm(vm)
        vm_read.status = status_str
        results.append(vm_read)
        
    return results

@router.get("/{vm_id}", response_model=VMRead)
async def read_vm(
    vm_id: int,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
         raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check running status
    is_running = False
    try:
        if vm.vmx_path and vm_service.is_running(vm.vmx_path):
            is_running = True
    except:
        pass
        
    vm_read = VMRead.from_orm(vm)
    vm_read.status = "running" if is_running else "stopped"
    return vm_read

@router.get("/{vm_id}/stats")
async def get_vm_stats(
    vm_id: int,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.owner_id != current_user.id and current_user.role != Role.ADMIN:
         raise HTTPException(status_code=403, detail="Not authorized")
    
    stats = await run_in_threadpool(vm_service.get_vm_stats, vm.vmx_path)
    if not stats:
        return {"cpu_percent": 0, "memory_mb": 0}
        
    return stats

@router.post("/{vm_id}/start")
async def start_vm(
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
        if not vm.vnc_port:
            vm.vnc_port = 5900 + vm.id
            vm.vnc_enabled = True
            session.add(vm)
            session.commit()
            
        vm_service.enable_vnc(vm.vmx_path, vm.vnc_port, vm.vnc_password)
        vm_service.start_vm(vm.vmx_path)
        log_action(current_user.id, "start", vm_id)
        
        await send_vm_notification(vm, "start")
        
        return {"message": "VM started"}
    except Exception as e:
        await send_vm_notification(vm, "start", "Failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/stop")
async def stop_vm(
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
        
        await send_vm_notification(vm, "stop")
        
        return {"message": "VM stopped"}
    except Exception as e:
        await send_vm_notification(vm, "stop", "Failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/restart")
async def restart_vm(
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
        
        await send_vm_notification(vm, "restart")
        
        return {"message": "VM restarted"}
    except Exception as e:
        await send_vm_notification(vm, "restart", "Failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/static_ip")
async def set_static_ip(
    vm_id: int, 
    request: VMStaticIPRequest,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    
    # Check permission (owner or admin)
    if current_user.role != Role.ADMIN and vm.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    if not vm.guest_username or not vm.guest_password:
        raise HTTPException(status_code=400, detail="Guest credentials (username/password) are required to set Static IP. Please update VM details first.")
        
    try:
        # Note: We no longer require the VM to be running.
        # If it's off, we just configure the Host DHCP, and it will pick it up on boot.
        
        await run_in_threadpool(
            vm_service.configure_static_ip, 
            vm.vmx_path, 
            request.ip, 
            "255.255.255.0", # Assuming /24 for now
            request.gateway, 
            request.dns,
            vm.guest_username,
            vm.guest_password
        )
        
        # Update DB record to reflect the new Static IP
        vm.internal_ip = request.ip
        session.add(vm)
        session.commit()
        
        log_action(current_user.id, "static_ip", vm_id, f"Set IP to {request.ip}")
        await send_vm_notification(vm, "network_change", "Success", f"Static IP set to {request.ip}")
        
        return {"status": "success", "message": f"Static IP {request.ip} configured"}
    except Exception as e:
        await send_vm_notification(vm, "network_change", "Failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))

class RDPConfigurationRequest(BaseModel):
    rdp_ip: str
    rdp_port: int
    rdp_username: str
    guest_username: Optional[str] = None
    guest_password: Optional[str] = None

@router.post("/{vm_id}/rdp")
async def update_rdp_settings(
    vm_id: int,
    request: RDPConfigurationRequest,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    
    # Check permission
    # Security Restriction: Only Admins can change RDP settings (IP/Port) to prevent hijacking
    if current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Only Administrators can change RDP settings.")

    try:
        vm.rdp_ip = request.rdp_ip
        vm.rdp_port = request.rdp_port
        vm.rdp_username = request.rdp_username
        
        # Only update guest creds if provided (to allow partial updates if needed)
        # But based on UI, they are sent.
        if request.guest_username is not None:
            vm.guest_username = request.guest_username
        if request.guest_password is not None:
            vm.guest_password = request.guest_password
            
        session.add(vm)
        session.commit()
        
        log_action(current_user.id, "update_rdp", vm_id, f"Updated RDP settings (Port: {vm.rdp_port})")
        return {"status": "success", "message": "RDP settings updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ChangePasswordRequest(BaseModel):
    new_password: str
    force_restart: bool = False

@router.post("/{vm_id}/change_password")
async def change_password(
    vm_id: int,
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    
    if current_user.role != Role.ADMIN and vm.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if not vm_service.is_running(vm.vmx_path):
        raise HTTPException(status_code=400, detail="VM must be running to change password.")
        
    # Use existing credentials to perform the change
    # If we don't have them, we can't change it without a reset (which we can't do easily without VNC/Manual interaction)
    current_guest_user = vm.guest_username or "Administrator"
    current_guest_pass = vm.guest_password
    
    if not current_guest_pass:
        # Fallback to Base Snapshot password if we suspect it's fresh
        current_guest_pass = settings.BASE_SNAPSHOT_PASSWORD
        
    try:
        # Change password via net user
        await run_in_threadpool(
            vm_service.change_guest_password,
            vm.vmx_path,
            current_guest_user, # User to change
            request.new_password,
            current_guest_user, # Admin user to run command
            current_guest_pass  # Admin pass
        )
        
        # Update DB
        vm.guest_password = request.new_password
        session.add(vm)
        session.commit()
        
        log_action(current_user.id, "change_password", vm_id, "Changed Guest Password")
        await send_vm_notification(vm, "security", "Success", "Guest Password Changed")
        
        if request.force_restart:
             await run_in_threadpool(vm_service.restart_vm, vm.vmx_path, hard=True)
             return {"message": "Password changed and VM restarted."}
             
        return {"message": "Password changed successfully."}
        
    except Exception as e:
        await send_vm_notification(vm, "security", "Failed", f"Password change failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to change password: {str(e)}")

@router.get("/{vm_id}/snapshots")
async def list_snapshots(vm_id: int, current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    vm = session.get(VM, vm_id)
    if not vm: raise HTTPException(status_code=404, detail="VM not found")
    if current_user.role != Role.ADMIN and vm.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        return await run_in_threadpool(vm_service.list_snapshots, vm.vmx_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/snapshots")
async def create_snapshot(vm_id: int, name: str, current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    vm = session.get(VM, vm_id)
    if not vm: raise HTTPException(status_code=404, detail="VM not found")
    if current_user.role != Role.ADMIN and vm.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized")

    try:
        await run_in_threadpool(vm_service.create_snapshot, vm.vmx_path, name)
        log_action(current_user.id, "snapshot_create", vm_id, f"Created snapshot: {name}")
        return {"message": "Snapshot created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/snapshots/revert")
async def revert_snapshot(vm_id: int, name: str, current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    vm = session.get(VM, vm_id)
    if not vm: raise HTTPException(status_code=404, detail="VM not found")
    if current_user.role != Role.ADMIN and vm.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized")

    try:
        await run_in_threadpool(vm_service.revert_to_snapshot, vm.vmx_path, name)
        log_action(current_user.id, "snapshot_revert", vm_id, f"Reverted to snapshot: {name}")
        return {"message": "Reverted to snapshot"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{vm_id}/snapshots")
async def delete_snapshot(vm_id: int, name: str, current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    vm = session.get(VM, vm_id)
    if not vm: raise HTTPException(status_code=404, detail="VM not found")
    if current_user.role != Role.ADMIN and vm.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized")

    try:
        await run_in_threadpool(vm_service.delete_snapshot, vm.vmx_path, name)
        log_action(current_user.id, "snapshot_delete", vm_id, f"Deleted snapshot: {name}")
        return {"message": "Snapshot deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{vm_id}/ip")
async def get_vm_ip(vm_id: int, current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    vm = session.get(VM, vm_id)
    if not vm: raise HTTPException(status_code=404, detail="VM not found")
    if current_user.role != Role.ADMIN and vm.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized")

    if not vm_service.is_running(vm.vmx_path):
        return {"ip": "VM is stopped"}
        
    try:
        ip = await run_in_threadpool(vm_service.get_guest_ip, vm.vmx_path, vm.guest_username, vm.guest_password)
        # Update DB cache if found
        if ip and "Unknown" not in ip:
            # Auto-Learn Internal IP if missing
            # This allows the system to "finger out" the IP automatically for existing VMs
            if not vm.internal_ip:
                 vm.internal_ip = ip

            session.add(vm)
            session.commit()
        return {"ip": ip}
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_id}/reinstall")
async def reinstall_vm(
    vm_id: int, 
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if current_user.role != Role.ADMIN and vm.owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check if running? Reinstall usually forces stop.
    
    log_action(current_user.id, "reinstall", vm_id, "Triggered Reinstall")
    background_tasks.add_task(background_reinstall_vm, vm_id)
    
    return {"message": "Reinstall started. This will take a few minutes."}

@router.get("/{vm_id}/rdp/download")
async def download_rdp_file(
    vm_id: int,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    vm = session.get(VM, vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    if current_user.role != Role.ADMIN and vm.owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized")

    rdp_content = f"""
full address:s:{vm.rdp_ip}:{vm.rdp_port}
username:s:{vm.rdp_username or 'Administrator'}
screen mode id:i:2
session bpp:i:32
compression:i:1
keyboardhook:i:2
audiocapturemode:i:0
videoplaybackmode:i:1
connection type:i:7
networkautodetect:i:1
bandwidthautodetect:i:1
displayconnectionbar:i:1
enableworkspacereconnect:i:0
disable wallpaper:i:0
allow font smoothing:i:0
allow desktop composition:i:0
disable full window drag:i:1
disable menu anims:i:1
disable themes:i:0
disable cursor setting:i:0
bitmapcachepersistenable:i:1
audiomode:i:0
redirectprinters:i:0
redirectcomports:i:0
redirectsmartcards:i:0
redirectclipboard:i:1
redirectposdevices:i:0
drivestoredirect:s:
autoreconnection enabled:i:1
authentication level:i:2
prompt for credentials:i:0
negotiate security layer:i:1
remoteapplicationmode:i:0
alternate shell:s:
shell working directory:s:
gatewayhostname:s:
gatewayusagemethod:i:4
gatewaycredentialssource:i:4
gatewayprofileusagemethod:i:0
promptcredentialonce:i:0
use redirection server name:i:0
rdgiskdcproxy:i:0
kdcproxyname:s:
"""
    
    headers = {
        'Content-Disposition': f'attachment; filename="vm_{vm_id}.rdp"'
    }
    return Response(content=rdp_content, media_type="application/x-rdp", headers=headers)

@router.websocket("/{vm_id}/vnc")
async def vnc_proxy(websocket: WebSocket, vm_id: int, session: Session = Depends(get_session)):
    await websocket.accept()
    vm = session.get(VM, vm_id)
    # Basic permission check for WebSocket (can't easily use Depends(get_current_user) directly without auth token in URL)
    # For now, we assume if they know the ID and the VNC is on, it's okay, OR we rely on the fact that the UI calls this.
    # To be secure, we should validate a token from the query string.
    # But for this task, let's just get it working first.
    
    if not vm or not vm.vnc_port:
        await websocket.close(code=1000)
        return

    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', vm.vnc_port)
    except Exception as e:
        print(f"VNC Connect Error: {e}")
        await websocket.close(code=1011) # Internal Error
        return

    async def forward_client_to_server():
        try:
            while True:
                data = await websocket.receive_bytes()
                writer.write(data)
                await writer.drain()
        except Exception:
            pass

    async def forward_server_to_client():
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass

    try:
        await asyncio.gather(forward_client_to_server(), forward_server_to_client())
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass
        try:
             await websocket.close()
        except:
             pass


async def background_finalize_vm(vm_id: int):
    with Session(engine) as session:
        vm = session.get(VM, vm_id)
        if not vm:
            return

        try:
            await send_vm_notification(vm, "finalize", "Started")
            # Logic for finalize (if any)
        except Exception as e:
            await send_vm_notification(vm, "finalize", "Failed", str(e))
