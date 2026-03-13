
        $ErrorActionPreference = 'Stop'
        $LogFile = "C:\Windows\Temp\ip_config_log.txt"
        Start-Transcript -Path $LogFile -Force
        
        try {
            Write-Output "Starting IP Configuration (NETSH Mode)..."
            Write-Output "Target IP: 192.168.119.151"
            Write-Output "Target Gateway: 192.168.119.2"
        
            # 1. Auto-detect Interface
            $adapter = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1
            if (-not $adapter) { throw "No active network adapter found" }
            
            $InterfaceAlias = $adapter.Name
            Write-Output "Configuring Adapter: $InterfaceAlias"

            # 2. Disable Duplicate Address Detection (DAD) to prevent 'Tentative' state
            # This is crucial for VMs where the network might be slow to respond or bridged.
            Write-Output "Disabling DAD..."
            try {
                Set-NetIPInterface -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -DadTransmits 0 -DadRetransmitTime 0 -ErrorAction SilentlyContinue
            } catch {
                Write-Warning "Could not disable DAD (might not be supported on this OS version), proceeding..."
            }

            # 3. Configure IP/Gateway using netsh (Atomic operation)
            # This switches from DHCP to Static in one go.
            Write-Output "Applying Static IP via netsh..."
            $netsh_ip = "netsh interface ip set address name=`"$InterfaceAlias`" static 192.168.119.151 255.255.255.0 192.168.119.2"
            Write-Output "Executing: $netsh_ip"
            Invoke-Expression $netsh_ip
            
            if ($LASTEXITCODE -ne 0) {
                throw "netsh failed to set IP configuration. Exit Code: $LASTEXITCODE"
            }

            # 4. Configure DNS via netsh
            Write-Output "Configuring DNS via netsh..."
            $dns_list = ""1.1.1.1","1.0.0.1"".Replace('"', '').Split(',')
            
            # Primary DNS
            if ($dns_list.Count -ge 1) {
                $primary = $dns_list[0]
                $netsh_dns1 = "netsh interface ip set dns name=`"$InterfaceAlias`" static $primary"
                Invoke-Expression $netsh_dns1
            }
            
            # Secondary DNS
            if ($dns_list.Count -ge 2) {
                $secondary = $dns_list[1]
                $netsh_dns2 = "netsh interface ip add dns name=`"$InterfaceAlias`" $secondary index=2"
                Invoke-Expression $netsh_dns2
            }

            Write-Output "SUCCESS: IP Configuration Complete."
            
            # Validation
            $check = Get-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4
            Write-Output "Current Configuration:"
            Write-Output $check

        } catch {
            Write-Error "CRITICAL FAILURE: $($_.Exception.Message)"
            Write-Output "Stack Trace: $($_.ScriptStackTrace)"
            exit 1
        } finally {
            Stop-Transcript
        }
        