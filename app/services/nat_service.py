import os
import subprocess
import logging
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

NAT_CONF_PATH = r"C:\ProgramData\VMware\vmnetnat.conf"
SERVICE_NAME = "VMware NAT Service"

class NatService:
    def __init__(self, config_path: str = NAT_CONF_PATH):
        self.config_path = config_path

    def _read_lines(self) -> List[str]:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"NAT config not found at {self.config_path}")
        with open(self.config_path, 'r') as f:
            return f.readlines()

    def _write_lines(self, lines: List[str]):
        with open(self.config_path, 'w') as f:
            f.writelines(lines)

    def get_rules(self) -> Dict[str, List[Dict]]:
        """
        Returns a dict with 'tcp' and 'udp' lists.
        Each item: {'host_port': int, 'guest_ip': str, 'guest_port': int, 'description': str}
        """
        lines = self._read_lines()
        rules = {"tcp": [], "udp": []}
        current_section = None
        
        # Regex for rule: 8888 = 192.168.1.5:80
        rule_pattern = re.compile(r"^\s*(\d+)\s*=\s*([0-9\.]+):(\d+)")

        for line in lines:
            stripped = line.strip()
            if stripped == "[incomingtcp]":
                current_section = "tcp"
            elif stripped == "[incomingudp]":
                current_section = "udp"
            elif stripped.startswith("["):
                current_section = None
            
            if current_section and "=" in stripped:
                match = rule_pattern.match(stripped)
                if match:
                    host_port, guest_ip, guest_port = match.groups()
                    rules[current_section].append({
                        "host_port": int(host_port),
                        "guest_ip": guest_ip,
                        "guest_port": int(guest_port)
                    })
        return rules

    def add_forwarding_rule(self, protocol: str, host_port: int, guest_ip: str, guest_port: int):
        """
        Adds a port forwarding rule.
        protocol: 'tcp' or 'udp'
        """
        if protocol not in ['tcp', 'udp']:
            raise ValueError("Protocol must be 'tcp' or 'udp'")
            
        lines = self._read_lines()
        section_header = f"[incoming{protocol}]"
        new_lines = []
        in_section = False
        inserted = False
        
        # Check if port already used
        rule_pattern = re.compile(r"^\s*(\d+)\s*=")
        
        for line in lines:
            stripped = line.strip()
            if stripped == section_header:
                in_section = True
                new_lines.append(line)
                continue
            elif stripped.startswith("[") and in_section:
                # End of our section, insert here if not already
                if not inserted:
                    new_lines.append(f"{host_port} = {guest_ip}:{guest_port}\n")
                    inserted = True
                in_section = False
            
            if in_section:
                match = rule_pattern.match(stripped)
                if match and int(match.group(1)) == host_port:
                    # Update existing rule
                    new_lines.append(f"{host_port} = {guest_ip}:{guest_port}\n")
                    inserted = True
                    continue
            
            new_lines.append(line)
            
        # If section was at the end or we missed it
        if not inserted:
            if in_section:
                 # EOF while in section
                 new_lines.append(f"{host_port} = {guest_ip}:{guest_port}\n")
            else:
                 # Section might not exist? (Unlikely for vmnetnat.conf)
                 pass

        self._write_lines(new_lines)
        self.restart_nat_service()

    def delete_forwarding_rule(self, protocol: str, host_port: int):
        if protocol not in ['tcp', 'udp']:
            raise ValueError("Protocol must be 'tcp' or 'udp'")
            
        lines = self._read_lines()
        section_header = f"[incoming{protocol}]"
        new_lines = []
        in_section = False
        
        rule_pattern = re.compile(r"^\s*(\d+)\s*=")
        
        for line in lines:
            stripped = line.strip()
            if stripped == section_header:
                in_section = True
                new_lines.append(line)
                continue
            elif stripped.startswith("[") and in_section:
                in_section = False
            
            if in_section:
                match = rule_pattern.match(stripped)
                if match and int(match.group(1)) == host_port:
                    # Skip this line to delete
                    continue
            
            new_lines.append(line)

        self._write_lines(new_lines)
        self.restart_nat_service()

    def restart_nat_service(self):
        try:
            logger.info(f"Restarting {SERVICE_NAME}...")
            # Use PowerShell to restart service
            cmd = ["powershell", "-Command", f"Restart-Service -Name '{SERVICE_NAME}' -Force"]
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info("Service restarted successfully.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to restart service: {e}")
            raise Exception("Failed to apply NAT settings (Service Restart Failed)")

nat_service = NatService()
