# VM Control Panel

A comprehensive, modern web-based control panel for managing VMware Workstation VMs. Built with FastAPI, SQLModel, and Bootstrap.

## Features

### User Dashboard
- **Modern UI & Theming**:
  - **Dark Neumorphism Theme**: A sleek, dark-mode-first design with soft shadows and vibrant gradients.
  - **Manual Theme Toggle**: User-controlled light/dark mode persistence (saved in browser).
- **Tabbed Interface**: Organized view for each VM with dedicated tabs:
  - **Service Information**: Status, Connection Info (IP/Port/User), Expiration Date, and Download .RDP.
  - **Troubleshoot**: Tools like **Live Console** (noVNC) and **Get IP Address**.
  - **Actions**: Power controls, Snapshots, Settings, and Password management.
- **Live Resource Metrics**: Real-time monitoring of **Host CPU Load** and **Host Memory (Reserved)** for each VM.
- **Advanced Troubleshooting & Automation**:
  - **Account Lockout Reset**: Instantly reset the account lockout threshold to 0 to fix RDP login issues.
  - **RDP & Firewall Repair**: One-click enable RDP service and allow it through the Windows Firewall.
  - **NLA Toggle**: Disable Network Level Authentication (NLA) for easier legacy RDP access.
  - **Network Repair**: Reset the network adapter to DHCP and DNS defaults.
  - **ICMP/Ping**: Allow ICMP (Ping) requests through the firewall for connectivity testing.
  - **Scheduled Tasks**: Configure daily auto-reboots for VM health maintenance.
- **Enhanced Guest Support**:
  - **Flexible Authentication**: Supports non-Administrator guest accounts (e.g., custom usernames).
  - **Smart Credentials**: Automatically attempts multiple username formats (`.\User`, `User`) to ensure command success.
- **Live Monitor**: Real-time web-based VNC console (noVNC) integration. Supports keyboard interaction (including Ctrl+Alt+Del).
- **One-Click Connect**: Download pre-configured `.rdp` files for instant Remote Desktop access.
- **Power Controls**: Start, Stop, and Restart VMs directly from the main view.
- **Snapshot Management**: Create and restore snapshots with non-blocking background operations.
- **Advanced Provisioning & Reinstall**:
  - **Finalize Setup**: Automatically stops a new VM and creates a "Base" snapshot for future reverts.
  - **Reinstall**: Wipes the server by reverting to the "Base" snapshot and resetting the password to a default secure state.
  - **IP Persistence**: Automatically re-applies the assigned Static IP immediately after a reinstall.
- **Advanced Password Management**:
  - **Change Guest Password**: Update the Windows Administrator password via `vmrun`.
- **Expiration Tracking**: Clear display of service expiration dates with status indicators.

### Admin Panel
- **VM Management**:
  - Add existing VMs by `.vmx` path.
  - **Edit VM**: Update owner, RDP port, RDP username, VMX path.
  - **RDP Security**: Only Administrators can change RDP Port and Host IP to prevent hijacking.
  - **Network Configuration (Dual-Mode)**:
    - **Static IP Assignment**: Assign a permanent Static IP to any VM.
    - **Host-Side DHCP Reservation**: Automatically configures VMware's `vmnetdhcp.conf` to reserve the IP based on MAC address. This guarantees IP persistence even across reboots and reinstalls.
    - **Guest-Side GUI Sync**: Automatically updates the Windows Network Adapter settings (via `netsh`) to visually display "Static IP" instead of "Obtain Automatically", ensuring user peace of mind.
  - **Expiration Management**: Set and edit expiration dates via the Admin list.
  - Assign VMs to specific users.
- **User Management**:
  - Create, Update, Delete users.
  - Assign Roles (Admin/User).
- **Network Management**:
  - View and manage Port Forwarding rules (NAT).
- **Audit Logs**: Track user actions (Start, Stop, Password Change, etc.).

### Notifications (Dual Webhook System)
The system supports a sophisticated notification routing system:
- **System Admin**: Global alerts for all critical system events (can be configured in `config.py`).
- **Client Notifications**:
  - **Public Webhook**: For general status updates (Start, Stop, Network Changes) - ideal for public status channels.
  - **Private Webhook**: For sensitive alerts (Reinstalls, Errors, Security Warnings) - ideal for private admin channels.
  - **Smart Fallback**: If a user only sets a Private webhook, all notifications go there.

## Prerequisites

- **Python 3.10+**
- **VMware Workstation** (installed with `vmrun.exe`).
- **MySQL Database** (or MariaDB).
- **Nginx Proxy Manager** (Recommended for production/remote access to handle WebSockets).

## Installation

1.  **Clone the repository** (or extract files).
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Database Setup**:
    - Import `database_setup.sql` into your MySQL server to create the database and user.
    - Update the connection string in `app/core/config.py`.

4.  **Configuration**:
    - The application configuration is located in `app/core/config.py`.
    - **Discord Webhook**: Set `DISCORD_WEBHOOK_URL` in `app/core/config.py` for system-wide admin alerts.
    - **Important**: Ensure `VMRUN_PATH` in `app/services/vm_service.py` points to your correct `vmrun.exe` location.

## Usage

1.  **Start the Server**:
    ```bash
    python run.py
    ```
    - **Development Mode**: By default, `run.py` enables `reload=True` for hot-reloading code changes.
    - **Production**: Edit `run.py` and set `reload=False` (and optionally `workers=4`) for better performance.
    
    The server will start on `http://0.0.0.0:8082` (configurable in `run.py`).

2.  **Login**:
    - Open your browser and navigate to `http://localhost:8082`.
    - **Default Admin Credentials** (if created via `database_setup.sql` or manually):
        - Username: `admin`
        - Password: `admin`
    - *Note: Change the password immediately after first login.*

## Nginx Proxy Manager Configuration (Important)

For the **Live Monitor (noVNC)** to work correctly behind a proxy, you must enable WebSocket support.

1.  Open Nginx Proxy Manager.
2.  Edit your Proxy Host.
3.  Go to the **"Custom Locations"** or **"Details"** tab.
4.  Ensure **Websockets Support** is toggled **ON**.
5.  If adding custom locations for `/ws`:
    - Location: `/ws`
    - Scheme: `http`
    - Forward Host/Port: Your app IP and port 8084.
    - **Upgrade Connection**: Enabled (Websockets).

## Project Structure

```
app/
├── core/
│   ├── config.py       # App configuration (DB, Secrets, Paths)
│   ├── security.py     # JWT Auth & Password Hashing
├── routers/
│   ├── admin.py        # Admin-only endpoints
│   ├── auth.py         # Login/User management
│   ├── vm.py           # VM Control endpoints
├── services/
│   ├── vm_service.py   # Core logic for vmrun interactions
│   ├── dhcp_service.py # VMware DHCP Config management
├── models/             # SQLModel Database Tables
├── static/             # CSS, JS, Images
├── templates/          # Jinja2 HTML Templates
```
