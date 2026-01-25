$port = 6969
# Enable RDP
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name 'fDenyTSConnections' -Value 0
# Set RDP port explicitly as DWORD
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' -Name 'PortNumber' -Value $port -Type DWord
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