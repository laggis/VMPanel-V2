import os
import subprocess
import logging
import re

logger = logging.getLogger(__name__)

DHCP_CONFIG_PATH = r"C:\ProgramData\VMware\vmnetdhcp.conf"

class DHCPService:
    def add_reservation(self, vm_name: str, mac_address: str, ip_address: str):
        """
        Adds or updates a DHCP reservation for the given VM in vmnetdhcp.conf.
        Then restarts the VMwareDHCP service.
        """
        if not os.path.exists(DHCP_CONFIG_PATH):
            logger.error(f"DHCP config not found at {DHCP_CONFIG_PATH}")
            raise FileNotFoundError(f"DHCP config not found at {DHCP_CONFIG_PATH}")
            
        # Normalize inputs
        # vm_name should be safe for config (alphanumeric + underscores/dashes)
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', vm_name)
        
        # Read content
        try:
            with open(DHCP_CONFIG_PATH, 'r') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read DHCP config: {e}")
            raise e
            
        # Check if entry exists
        # Pattern: host <name> { ... }
        # We want to replace the whole block or append if not found.
        
        # Regex to find existing block for this specific VM name
        # We use re.DOTALL to match across lines
        block_pattern = re.compile(rf"host\s+{re.escape(safe_name)}\s*\{{.*?\}}", re.DOTALL | re.IGNORECASE)
        
        new_entry = f"""host {safe_name} {{
    hardware ethernet {mac_address};
    fixed-address {ip_address};
}}"""

        if block_pattern.search(content):
            logger.info(f"Updating existing DHCP reservation for {safe_name}")
            new_content = block_pattern.sub(new_entry, content)
        else:
            logger.info(f"Adding new DHCP reservation for {safe_name}")
            # Append before the last "# End" if it exists, otherwise just append
            if "# End" in content:
                # Insert before the last occurrence of # End
                parts = content.rsplit("# End", 1)
                new_content = parts[0] + new_entry + "\n# End" + parts[1]
            else:
                new_content = content + "\n" + new_entry

        # Write back only if changed
        if new_content != content:
            # Create backup
            backup_path = DHCP_CONFIG_PATH + ".bak"
            try:
                with open(backup_path, 'w') as f:
                    f.write(content)
            except Exception as e:
                logger.warning(f"Failed to create DHCP config backup: {e}")

            try:
                with open(DHCP_CONFIG_PATH, 'w') as f:
                    f.write(new_content)
                self.restart_dhcp_service()
            except Exception as e:
                logger.error(f"Failed to write DHCP config or restart service: {e}")
                raise e
        else:
            logger.info("DHCP configuration already up to date.")

    def restart_dhcp_service(self):
        """
        Restarts the VMnetDHCP service.
        """
        logger.info("Restarting VMwareDHCP service...")
        try:
            # Using net stop/start is reliable
            # We ignore errors on stop (service might be stopped)
            subprocess.run(["net", "stop", "VMnetDHCP"], check=False, capture_output=True)
            
            # We expect start to succeed
            result = subprocess.run(["net", "start", "VMnetDHCP"], check=True, capture_output=True, text=True)
            logger.info(f"VMwareDHCP service restarted successfully: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to restart VMwareDHCP service: {e.stderr}")
            raise Exception(f"Failed to restart VMware DHCP service: {e.stderr}")

dhcp_service = DHCPService()
