import subprocess
import logging
import os
import psutil
import base64
from app.core.config import settings

logger = logging.getLogger(__name__)

class VMService:
    def __init__(self):
        self.vmrun_path = settings.VMRUN_PATH
        # Basic check if vmrun exists
        if not os.path.exists(self.vmrun_path):
            logger.warning(f"vmrun not found at {self.vmrun_path}. VM operations will fail.")

    def _decode_output(self, data: bytes) -> str:
        """Helper to decode bytes using multiple encodings (UTF-8, OEM, MBCS)."""
        if not data:
            return ""
        # Try UTF-8 first (standard)
        # Then OEM (likely for console apps like vmrun on Windows)
        # Then MBCS (ANSI, system default)
        for encoding in ['utf-8', 'oem', 'mbcs']:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode('utf-8', errors='replace')

    def _run_command(self, command: str, vmx_path: str = None, params: list = None, guest_user: str = None, guest_pass: str = None):
        cmd = [self.vmrun_path, "-T", "ws"] # -T ws for Workstation
        
        # Add guest credentials if provided
        if guest_user and guest_pass is not None:
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
            # Capture as bytes (text=False) to handle encoding manually
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=False, 
                check=True
            )
            return self._decode_output(result.stdout).strip()
        except subprocess.CalledProcessError as e:
            # Decode stderr/stdout for logging
            stderr_str = self._decode_output(e.stderr)
            stdout_str = self._decode_output(e.stdout)
            
            logger.error(f"Error running vmrun {command}: {stderr_str}")
            if stdout_str:
                logger.error(f"Stdout: {stdout_str}")
            # Clean error message
            err_msg = stderr_str.strip() if stderr_str else (stdout_str.strip() if stdout_str else "Unknown error")
            raise Exception(f"VM Operation Failed: {err_msg}")
        except FileNotFoundError:
             raise Exception(f"vmrun executable not found at {self.vmrun_path}")

    def start_vm(self, vmx_path: str):
        # nogui starts it headless.
        # Changed to gui to see if it fixes the black screen issue.
        # Reverted to nogui because gui blocks on dialogs and we have autoAnswer enabled now.
        return self._run_command("start", vmx_path, ["nogui"])

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

    def get_vm_stats(self, vmx_path: str):
        """
        Returns a dict with 'cpu_percent' and 'memory_mb' for the VM process.
        Returns None if VM process is not found.
        """
        target_vmx = os.path.normpath(vmx_path).lower()
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and 'vmware-vmx' in proc.info['name'].lower():
                        cmdline = proc.info.get('cmdline', [])
                        if not cmdline:
                            continue
                            
                        # Check if this process belongs to the requested VMX
                        for arg in cmdline:
                            if arg.lower().endswith('.vmx'):
                                if os.path.normpath(arg).lower() == target_vmx:
                                    # Found it!
                                    p = psutil.Process(proc.info['pid'])
                                    # Interval 1.5s to get a meaningful CPU reading
                                    # cpu_percent returns usage across all cores.
                                    # e.g. 200% = 2 cores fully used.
                                    # To scale to "System CPU %", divide by cpu_count.
                                    cpu_raw = p.cpu_percent(interval=1.5)
                                    cpu_system = cpu_raw / psutil.cpu_count()
                                    
                                    mem_mb = p.memory_info().rss / (1024 * 1024)
                                    
                                    return {
                                        "cpu_percent": round(cpu_system, 2),
                                        "memory_mb": round(mem_mb, 0)
                                    }
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception as e:
            logger.error(f"Error getting VM stats: {e}")
            
        return None

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
        # We removed -wait to avoid blocking.
        try:
            return self._run_command("getGuestIPAddress", vmx_path, [], guest_user=guest_user, guest_pass=guest_pass)
        except Exception as e:
            # If it fails, it might be because tools aren't ready or installed.
            # logger.warning(f"Failed to get IP for {vmx_path}: {e}") # Reduce log noise during polling
            return None

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

    def delete_vm(self, vmx_path: str):
        """
        Deletes the VM and its files.
        """
        return self._run_command("deleteVM", vmx_path)

    def get_vm_specs(self, vmx_path: str) -> dict:
        """
        Reads the .vmx file and returns CPU/RAM specs.
        """
        if not os.path.exists(vmx_path):
            return {"cpu_count": 2, "memory_mb": 4096} # Default fallback

        specs = {"cpu_count": 2, "memory_mb": 4096}
        try:
            with open(vmx_path, 'r') as f:
                for line in f:
                    line = line.strip().lower()
                    if line.startswith("numvcpus"):
                        parts = line.split("=")
                        if len(parts) > 1:
                            specs["cpu_count"] = int(parts[1].strip().strip('"'))
                    elif line.startswith("memsize"):
                        parts = line.split("=")
                        if len(parts) > 1:
                            specs["memory_mb"] = int(parts[1].strip().strip('"'))
        except Exception as e:
            logger.error(f"Failed to read VM specs from {vmx_path}: {e}")
        
        return specs

    def clone_vm(self, source_vmx: str, dest_vmx: str, clone_name: str, clone_type: str = "full", snapshot_name: str = None):
        """
        Clones a VM.
        clone_type: 'full' or 'linked'
        snapshot_name: Required for linked clones.
        """
        # Ensure dest directory exists
        os.makedirs(os.path.dirname(dest_vmx), exist_ok=True)
        
        # vmrun clone <source> <dest> <full|linked> -snapshot=<name> -cloneName=<name>
        params = [dest_vmx, clone_type]
        if snapshot_name:
            params.append(f"-snapshot={snapshot_name}")
        params.append(f"-cloneName={clone_name}")
        
        return self._run_command("clone", source_vmx, params)

    def enable_vnc(self, vmx_path: str, port: int, password: str = None):
        """
        Enables VNC in the .vmx file.
        Note: Requires VM restart to take effect.
        """
        if not os.path.exists(vmx_path):
            raise Exception("VMX file not found")
            
        with open(vmx_path, 'r') as f:
            lines = f.readlines()
            
        new_lines = []
        # Remove existing VNC config
        for line in lines:
            if not line.strip().lower().startswith("remotedisplay.vnc"):
                new_lines.append(line)
        
        # Add new VNC config
        new_lines.append('RemoteDisplay.vnc.enabled = "TRUE"\n')
        new_lines.append(f'RemoteDisplay.vnc.port = "{port}"\n')
        if password:
            new_lines.append(f'RemoteDisplay.vnc.password = "{password}"\n')
            
        with open(vmx_path, 'w') as f:
            f.writelines(new_lines)

    def update_specs(self, vmx_path: str, cpu_count: int = None, memory_mb: int = None):
        """
        Updates the CPU and Memory settings in the .vmx file.
        vmx_path: Path to the .vmx file
        cpu_count: Number of cores (optional)
        memory_mb: RAM in MB (optional)
        """
        if not os.path.exists(vmx_path):
            raise Exception("VMX file not found")
            
        with open(vmx_path, 'r') as f:
            lines = f.readlines()
            
        new_lines = []
        for line in lines:
            key = line.split('=')[0].strip().lower()
            if cpu_count and (key == "numvcpus" or key == "cpuid.corespersocket"):
                continue # Skip existing CPU lines
            if memory_mb and key == "memsize":
                continue # Skip existing Memory lines
            new_lines.append(line)
            
        # Ensure the last line ends with a newline
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'

        # Append new settings
        if cpu_count:
            # Set total cores
            new_lines.append(f'numvcpus = "{cpu_count}"\n')
            # For simplicity, 1 socket, N cores
            new_lines.append(f'cpuid.coresPerSocket = "{cpu_count}"\n')
            
        if memory_mb:
            new_lines.append(f'memsize = "{memory_mb}"\n')
            
        # Add Automation Hacks to prevent blocking dialogs
        # Check if they exist first to avoid duplicates (though we didn't filter them out above, VMX usually takes last)
        # Better to filter them out in the loop above? 
        # For safety, let's just append them. VMware usually rewrites the file on start anyway.
        new_lines.append('msg.autoAnswer = "TRUE"\n')
        new_lines.append('uuid.action = "keep"\n')
        new_lines.append('ui.microsem.mouse.tooltip = "FALSE"\n') # Disable annoying tooltips
            
        with open(vmx_path, 'w') as f:
            f.writelines(new_lines)

    def revert_to_snapshot(self, vmx_path: str, snapshot_name: str):
        """
        Reverts the VM to a named snapshot.
        """
        return self._run_command("revertToSnapshot", vmx_path, [snapshot_name])

    def list_snapshots(self, vmx_path: str) -> list:
        """
        Lists all snapshots for a VM.
        Returns a list of snapshot names.
        """
        output = self._run_command("listSnapshots", vmx_path)
        # Output format:
        # Total snapshots: 1
        # SnapshotName
        lines = output.splitlines()
        snapshots = []
        if len(lines) > 1:
            for line in lines[1:]:
                name = line.strip()
                if name:
                    snapshots.append(name)
        return snapshots

    def run_script_in_guest(self, vmx_path: str, username: str, password: str, script_text: str, interpreter: str = "powershell"):
        """
        Runs a script in the guest OS.
        interpreter: 'powershell' or 'cmd' or 'bash'
        """
        # Save script to a temp file on host? 
        # vmrun runScriptInGuest <path to vmx> <interpreter path> <script text>
        
        # Use full path for PowerShell to avoid "A file was not found" errors
        interp_path = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
        if interpreter == "cmd":
             interp_path = "C:\\Windows\\System32\\cmd.exe"
        elif interpreter == "bash":
             interp_path = "/bin/bash"
        
        return self._run_command(
            "runScriptInGuest",
            vmx_path,
            [interp_path, script_text],
            guest_user=username,
            guest_pass=password
        )

    def change_guest_password(self, vmx_path: str, username: str, new_password: str, current_user: str, current_pass: str):
        """
        Changes the password of a user inside the guest OS.
        Currently supports Windows guests via 'net user'.
        Requires valid current guest credentials (current_user, current_pass).
        """
        # Command: net user <username> <new_password>
        # We use runProgramInGuest to execute net.exe directly
        # Use interactive=False to avoid "user must be logged in" errors (runs in session 0)
        return self.run_program_in_guest(
            vmx_path, 
            current_user, 
            current_pass,
            "C:\\Windows\\System32\\net.exe", 
            ["user", username, new_password],
            interactive=False
        )

    def set_account_lockout_policy(self, vmx_path: str, threshold: int, duration_minutes: int, reset_window_minutes: int, current_user: str, current_pass: str):
        try:
            return self.run_program_in_guest(
                vmx_path,
                current_user,
                current_pass,
                "C:\\Windows\\System32\\net.exe",
                ["accounts", f"/lockoutthreshold:{threshold}", f"/lockoutduration:{duration_minutes}", f"/lockoutwindow:{reset_window_minutes}"],
                interactive=False
            )
        except Exception as e:
            msg = str(e).lower()
            if "invalid user name or password" not in msg:
                raise
            variants = [current_user, f".\\{current_user}"]
            if current_user.lower() != "administrator":
                variants.extend(["Administrator", ".\\Administrator"])
            last_err = e
            for user_variant in variants:
                try:
                    return self.run_program_in_guest(
                        vmx_path,
                        user_variant,
                        current_pass,
                        "C:\\Windows\\System32\\net.exe",
                        ["accounts", f"/lockoutthreshold:{threshold}", f"/lockoutduration:{duration_minutes}", f"/lockoutwindow:{reset_window_minutes}"],
                        interactive=False
                    )
                except Exception as e2:
                    last_err = e2
                    if "invalid user name or password" not in str(e2).lower():
                        raise
            raise last_err

    def get_vm_mac(self, vmx_path: str) -> str:
        """
        Reads the .vmx file and returns the generated MAC address.
        """
        if not os.path.exists(vmx_path):
            return None

        mac = None
        try:
            with open(vmx_path, 'r') as f:
                for line in f:
                    line = line.strip().lower()
                    # Check for exact matches on keys to avoid matching "ethernet0.addresstype"
                    if line.startswith("ethernet0.generatedaddress") or line.startswith("ethernet0.address"):
                         # Split by first =
                        parts = line.split("=", 1)
                        if len(parts) > 1:
                            key = parts[0].strip()
                            value = parts[1].strip().strip('"')
                            
                            # Double check the key to ensure it's not addressType
                            if key == "ethernet0.generatedaddress" or key == "ethernet0.address":
                                mac = value
                                break 

        except Exception as e:
            logger.error(f"Failed to read MAC from {vmx_path}: {e}")
        
        return mac

    def configure_static_ip(self, vmx_path: str, ip: str, subnet: str, gateway: str, dns: list, current_user: str, current_pass: str):
        """
        Configures a static IP address.
        Strategy: Host-Side DHCP Reservation (Robust) + Guest-Side DHCP Reset (Just in case).
        """
        # 1. Get MAC Address
        mac = self.get_vm_mac(vmx_path)
        if not mac:
            raise Exception("Could not find MAC address in .vmx file")
            
        # 2. Add Reservation to Host DHCP
        from app.services.dhcp_service import dhcp_service
        vm_name = os.path.splitext(os.path.basename(vmx_path))[0]
        dhcp_service.add_reservation(vm_name, mac, ip)
        
        # 3. Force Guest to Static IP (GUI Update via netsh)
        # Only if VM is running
        if self.is_running(vmx_path):
            logger.info("VM is running. Executing Guest-Side 'netsh' configuration for GUI persistence...")
            
            # Safe DNS handling
            dns1 = dns[0] if len(dns) > 0 else "8.8.8.8"
            dns2 = dns[1] if len(dns) > 1 else "1.1.1.1"
            
            script = f"""
            $ErrorActionPreference = 'Continue'
            try {{
                Start-Transcript -Path "C:\\Windows\\Temp\\static_ip_debug.log" -Append
            }} catch {{
                Write-Output "Could not start transcript"
            }}
            
            $IP = "{ip}"
            $Subnet = "{subnet}"
            $Gateway = "{gateway}"
            $DNS1 = "{dns1}"
            $DNS2 = "{dns2}"
            
            Write-Output "Configuring Static IP: $IP"
            
            # 1. Find Adapter
            $adapter = Get-NetAdapter | Where-Object {{ $_.Status -eq 'Up' }} | Select-Object -First 1
            if (-not $adapter) {{ 
                Write-Error "No active network adapter found"
                exit 1
            }}
            $InterfaceName = $adapter.Name
            
            Write-Output "Adapter found: $InterfaceName"
            
            # 2. Configure via netsh (Legacy/Robust for GUI)
            # We use netsh because it forces the GUI to update to 'Use the following IP address'
            # which satisfies user verification.
            
            # Set IP/Subnet/Gateway
            # netsh interface ip set address "Ethernet0" static 192.168.x.x ...
            $netshCmd = 'netsh interface ip set address name="' + $InterfaceName + '" static ' + $IP + ' ' + $Subnet + ' ' + $Gateway
            Write-Output "Executing: $netshCmd"
            cmd /c $netshCmd
            
            # Set DNS 1
            $dnsCmd1 = 'netsh interface ip set dns name="' + $InterfaceName + '" static ' + $DNS1
            Write-Output "Executing: $dnsCmd1"
            cmd /c $dnsCmd1
            
            # Set DNS 2
            $dnsCmd2 = 'netsh interface ip add dns name="' + $InterfaceName + '" ' + $DNS2 + ' index=2'
            Write-Output "Executing: $dnsCmd2"
            cmd /c $dnsCmd2
            
            Write-Output "Configuration Complete"
            Stop-Transcript
            """
            
            try:
                 # Run with elevated privileges (Administrator user is required)
                 self.run_script_in_guest(vmx_path, current_user, current_pass, script)
            except Exception as e:
                logger.warning(f"Failed to run Static IP script in guest: {e}")
        else:
            logger.info("VM is not running, skipping guest Static IP script (Host reservation applied).")





    def copy_file_to_guest(self, vmx_path: str, host_path: str, guest_path: str, guest_user: str, guest_pass: str):
        """
        Copies a file from the host to the guest.
        """
        return self._run_command(
            "copyFileFromHostToGuest",
            vmx_path,
            [host_path, guest_path],
            guest_user=guest_user,
            guest_pass=guest_pass
        )

    def run_program_in_guest(self, vmx_path: str, username: str, password: str, program_path: str, program_args: str, interactive: bool = True):
        """
        Runs a program in the guest OS.
        interactive: If True, requires a logged-in user and runs in their session. If False, runs in session 0 (background).
        """
        # vmrun -gu <user> -gp <pass> runProgramInGuest <vmx> [-noWait] [-activeWindow] [-interactive] <program> [args]
        
        final_args = []
        if interactive:
            final_args.append("-activeWindow")
            final_args.append("-interactive")
        
        final_args.append(program_path)
        
        if program_args:
            if isinstance(program_args, list):
                final_args.extend(program_args)
            else:
                final_args.append(program_args)

        return self._run_command(
            "runProgramInGuest",
            vmx_path,
            final_args,
            guest_user=username,
            guest_pass=password
        )



vm_service = VMService()
