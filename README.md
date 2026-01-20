# VM Control Panel

A comprehensive, modern web-based control panel for managing VMware Workstation VMs. Built with FastAPI, SQLModel, and Bootstrap.

## Features

### User Dashboard
- **Modern Interface**: Clean, tile-based dashboard with a dedicated "Single Server" view for each VM.
- **Live Monitor**: Real-time web-based VNC console (noVNC) integration. Supports keyboard interaction (including Ctrl+Alt+Del).
- **One-Click Connect**: Download pre-configured `.rdp` files for instant Remote Desktop access.
- **VM Actions**:
  - Start, Stop, Restart.
  - Real-time status indicators (Running/Stopped).
  - Snapshot Management (Create, Delete, Revert) with non-blocking background operations.
  - **Change Guest Password**: Update the Windows Administrator password directly from the panel (requires VM to be running).
- **Information**:
  - Connection details (IP, Port, RDP User).
  - Service information.
  - **Expiration Tracking**: View remaining time until service expiration.

### Admin Panel
- **VM Management**:
  - Add existing VMs by `.vmx` path.
  - **Edit VM**: Update owner, RDP port, RDP username, VMX path, and **Expiration Date**.
  - Assign VMs to specific users.
  - **Dashboard Editing**: Admins can also edit expiration dates directly from the user dashboard.
- **User Management**:
  - Create, Update, Delete users.
  - Assign Roles (Admin/User).
- **System Monitor**: View server resource usage.
- **Audit Logs**: Track user actions.

### Notifications
- **Discord Integration**: Automatic alerts sent to a configured Discord Webhook for:
  - Upcoming expirations (30 days, 7 days, 3 days, 1 day).
  - Service expiration (Day 0).
  - Overdue services (Day -1).

## Prerequisites

- **Python 3.8+**
- **VMware Workstation** (installed with `vmrun.exe`).
- **Nginx Proxy Manager** (Recommended for production/remote access to handle WebSockets).

## Installation

1.  **Clone the repository** (or extract files).
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configuration**:
    - The application configuration is located in `app/core/config.py`.
    - **Discord Webhook**: Set `DISCORD_WEBHOOK_URL` in `app/core/config.py` to receive expiration alerts.
    - Database: Defaults to SQLite (`test.db`) for easy setup.
    - **Important**: Ensure `VMRUN_PATH` in `app/services/vm_service.py` points to your correct `vmrun.exe` location.

## Usage

1.  **Start the Server**:
    ```bash
    python run.py
    ```
    The server will start on `http://0.0.0.0:8082`.

2.  **Login**:
    - Open your browser and navigate to `http://localhost:8082`.
    - **Default Admin Credentials**:
        - Username: `admin`
        - Password: `admin`
    - *Note: Change the password immediately after first login.*

## Nginx Proxy Manager Configuration (Important)

For the **Live Monitor (noVNC)** to work correctly behind a proxy, you must enable WebSocket support.

1.  Open Nginx Proxy Manager.
2.  Edit your Proxy Host.
3.  Go to the **"Custom Locations"** or **"Details"** tab (depending on version, but usually enabling "Websockets Support" in the main Details tab is sufficient for the root `/`).
4.  Ensure **Websockets Support** is toggled **ON**.
5.  If adding custom locations for `/ws`:
    - Location: `/ws`
    - Scheme: `http`
    - Forward Host/Port: Your app IP and port 8082.
    - **Upgrade Connection**: Enabled (Websockets).

## Project Structure

- `app/`: Main application code.
  - `routers/`: API endpoints (Admin, Auth, VM).
  - `models/`: Database models.
  - `templates/`: Jinja2 HTML templates (Dashboard, Admin, Login).
  - `services/`: Business logic, including `VMService` for `vmrun` interaction.
- `run.py`: Entry point script (runs Uvicorn on port 8082).

## Troubleshooting

- **"Live Console" shows "Connecting..." forever**:
  - Ensure the VM is actually running.
  - If using Nginx, ensure **Websockets Support** is enabled.
  - Check browser console for WebSocket errors (`ws://...`).
- **Snapshots not appearing immediately**:
  - Snapshot operations run in the background. The list auto-refreshes, but if it stalls, refresh the page.
- **VM commands failing**:
  - Verify the `vmrun.exe` path in the code/config matches your system installation.
