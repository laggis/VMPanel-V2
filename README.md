# VM Control Panel

A comprehensive web-based control panel for managing VMware Workstation VMs. Built with FastAPI, SQLModel, and Bootstrap.

## Features

- **Dashboard**: View all your assigned VMs in one place.
- **VM Management**:
  - Start, Stop, Restart VMs.
  - View real-time status (Running/Stopped).
  - View Guest IP Address.
  - Take Screenshots of running VMs.
  - Manage Snapshots (Create, Revert, Delete).
  - RDP Integration: Download configured `.rdp` files.
- **Admin Panel**:
  - **System Monitor**: Real-time CPU, RAM, Disk, and Network usage stats.
  - **User Management**: Create, Update, Delete users. Assign Roles (Admin/User).
  - **VM Management**: Register VMs by path, Assign owners, Configure RDP settings.
  - **Audit Logs**: Track all critical actions (Login, VM Start/Stop, etc.).
- **Security**:
  - JWT Authentication.
  - Role-based Access Control (RBAC).
  - Secure Password Hashing.

## Prerequisites

- **Python 3.8+**
- **VMware Workstation** (installed with `vmrun.exe`).
- **MySQL** (Optional, defaults to SQLite if configured, but currently set for MySQL).

## Installation

1.  **Clone the repository** (or extract files).
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure Environment**:
    - The application uses `app/core/config.py`.
    - By default, it looks for a MySQL database. Update `DATABASE_URL` in `app/core/config.py` or create a `.env` file if needed.
    - Ensure `VMRUN_PATH` points to your `vmrun.exe` location.
4.  **Database Setup**:
    - The application automatically creates tables on startup if they don't exist.

## Usage

1.  **Start the Server**:
    ```bash
    python run.py
    ```
    The server will start on `http://0.0.0.0:8083`.

2.  **Login**:
    - Open your browser and navigate to `http://localhost:8083`.
    - **Default Admin Credentials**:
      - Username: `admin`
      - Password: `admin`
    - *Note: Please change the admin password immediately after logging in.*

## Project Structure

- `app/`: Main application code.
  - `routers/`: API endpoints (Admin, Auth, VM).
  - `models/`: Database models (User, VM, AuditLog).
  - `templates/`: HTML templates (Jinja2).
  - `services/`: Business logic (VMService wrapper for vmrun).
- `run.py`: Entry point script.
- `requirements.txt`: Python dependencies.

## Troubleshooting

- **vmrun not found**: Check `VMRUN_PATH` in `app/core/config.py`.
- **Database errors**: Ensure your MySQL server is running and the credentials in `DATABASE_URL` are correct.
- **VMs not listing**: Use the "Scan VMs" feature in the Admin Panel to find `.vmx` files on your disk.

## License

Private / Custom.
