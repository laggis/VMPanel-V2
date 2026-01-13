import subprocess
import logging
import os
from app.core.config import settings

logger = logging.getLogger(__name__)

class VMService:
    def __init__(self):
        self.vmrun_path = settings.VMRUN_PATH
        # Basic check if vmrun exists
        if not os.path.exists(self.vmrun_path):
            logger.warning(f"vmrun not found at {self.vmrun_path}. VM operations will fail.")

    def _run_command(self, command: str, vmx_path: str = None, params: list = None, guest_user: str = None, guest_pass: str = None):
        cmd = [self.vmrun_path, "-T", "ws"] # -T ws for Workstation
        
        # Add guest credentials if provided
        if guest_user and guest_pass:
            cmd.extend(["-gu", guest_user, "-gp", guest_pass])
            
        cmd.append(command)
        
        if vmx_path:
            cmd.append(vmx_path)
        if params:
            cmd.extend(params)
        
        # Log command (redacting password)
        log_cmd = cmd.copy()
        if guest_pass:
            try:
                pass_idx = log_cmd.index("-gp") + 1
                if pass_idx < len(log_cmd):
                    log_cmd[pass_idx] = "******"
            except ValueError:
                pass
        
        logger.info(f"Executing: {' '.join(log_cmd)}")
        
        try:
            # shell=False is safer.
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running vmrun {command}: {e.stderr}")
            if e.stdout:
                logger.error(f"Stdout: {e.stdout}")
            # Clean error message
            err_msg = e.stderr.strip() if e.stderr else (e.stdout.strip() if e.stdout else "Unknown error")
            raise Exception(f"VM Operation Failed: {err_msg}")
        except FileNotFoundError:
             raise Exception(f"vmrun executable not found at {self.vmrun_path}")

    def start_vm(self, vmx_path: str):
        # nogui starts it headless.
        # Changed to gui to see if it fixes the black screen issue.
        return self._run_command("start", vmx_path, ["gui"])

    def stop_vm(self, vmx_path: str, hard: bool = False):
        mode = "hard" if hard else "soft"
        return self._run_command("stop", vmx_path, [mode])

    def restart_vm(self, vmx_path: str, hard: bool = False):
        mode = "hard" if hard else "soft"
        return self._run_command("reset", vmx_path, [mode])

    def list_running_vms(self):
        output = self._run_command("list")
        # Output format:
        # Total running VMs: 1
        # C:\Path\To\VM.vmx
        lines = output.splitlines()
        running_vms = []
        if len(lines) > 1:
            for line in lines[1:]:
                path = line.strip()
                if path:
                    running_vms.append(os.path.normpath(path).lower())
        return running_vms

    def is_running(self, vmx_path: str) -> bool:
        running_vms = self.list_running_vms()
        normalized_vmx = os.path.normpath(vmx_path).lower()
        return normalized_vmx in running_vms
    
    def get_vm_status(self, vmx_path: str):
        return "running" if self.is_running(vmx_path) else "stopped"

    def capture_screen(self, vmx_path: str, target_path: str, guest_user: str = None, guest_pass: str = None):
        """Captures the screen of the running VM to the target path."""
        # Ensure directory exists
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        # vmrun captureScreen often needs the user/pass if not running as the same user
        # But usually works if running in the same context.
        # It might fail if the guest tools aren't running or the display is off.
        # Let's try adding gu and gp if we have them, but for now just basic command.
        return self._run_command("captureScreen", vmx_path, [target_path], guest_user=guest_user, guest_pass=guest_pass)

    def get_guest_ip(self, vmx_path: str, guest_user: str = None, guest_pass: str = None):
        """Gets the IP address of the guest OS."""
        # vmrun -T ws getGuestIPAddress <path> [-wait]
        # Note: Requires VMware Tools to be running in the guest.
        # We can add -wait but that blocks. Default is instant but might fail if tools not ready.
        try:
            return self._run_command("getGuestIPAddress", vmx_path, ["-wait"], guest_user=guest_user, guest_pass=guest_pass)
        except Exception as e:
            # If it fails, it might be because tools aren't ready or installed.
            logger.warning(f"Failed to get IP for {vmx_path}: {e}")
            return "Unknown (Tools not ready?)"

    def list_snapshots(self, vmx_path: str):
        """Lists snapshots for a VM. 
        Returns a list of snapshot names. 
        Note: vmrun listSnapshots output is like:
        Total snapshots: 1
        Snapshot Name
        """
        output = self._run_command("listSnapshots", vmx_path)
        lines = output.splitlines()
        snapshots = []
        if len(lines) > 1:
            for line in lines[1:]:
                if line.strip():
                    snapshots.append(line.strip())
        return snapshots

    def create_snapshot(self, vmx_path: str, name: str):
        return self._run_command("snapshot", vmx_path, [name])

    def revert_snapshot(self, vmx_path: str, name: str):
        return self._run_command("revertToSnapshot", vmx_path, [name])

    def delete_snapshot(self, vmx_path: str, name: str):
        return self._run_command("deleteSnapshot", vmx_path, [name])

vm_service = VMService()
