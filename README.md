# CTRL Panel v2 — Script & Bot Process Manager

Web-based control panel for Discord bots and scripts with full auth, live logs, uptime charts, and scheduling.

## What's new in v2
- 🔐 Multi-user login with roles (Admin / Operator / Viewer)
- 🌙 Dark / Light theme toggle
- 📊 Per-process uptime charts (recorded every 5 minutes)
- ⏰ Scheduled auto-restart / start / stop jobs
- 🔒 JWT auth on all API endpoints + WebSocket
- Rate limiting on login endpoint

## Quick Start

### 1. Install
```bash
cd backend
npm install
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env — change JWT_SECRET to something random!
```

### 3. Start
```bash
npm start
```

### 4. Open browser
```
http://localhost:3001/login.html
```

Default credentials: **admin / admin123** — change immediately!

---

## Roles

| Role | Can do |
|------|--------|
| **Admin** | Everything — users, add/delete scripts, start/stop/restart, view logs |
| **Operator** | Start/stop/restart, add scripts, view logs, manage schedules |
| **Viewer** | View processes and logs only |

---

## Adding Scripts

Click **+ Add Script** and fill in:
- **Type** — discord.py, discord.js, Python, Node.js, or Shell
- **Script Path** — absolute path e.g. `C:\bots\mybot\main.py`
- **Working Dir** — defaults to the script's parent folder
- **Env Vars** — `TOKEN=abc DEBUG=true` (space-separated)
- **Auto-Restart** — Always / On Failure / Never

---

## Scheduling

Select a process → click the ⏰ button or open the Schedule tab in the right panel.
Add a job: choose action (restart/start/stop), set interval (minutes/hours/days).
Jobs survive server restarts.

---

## Security Notes

- Change `JWT_SECRET` in `.env` before exposing to the internet
- Change the default `admin` password immediately after first login
- Tokens expire after 24 hours
- Login endpoint is rate-limited (20 attempts per 15 min)

---

## File Structure

```
ctrl-panel/
├── backend/
│   ├── server.js          # Express + WebSocket server
│   ├── processManager.js  # Spawn/stop/log/stats
│   ├── authManager.js     # JWT auth, bcrypt, roles
│   ├── scheduler.js       # Scheduled restart jobs
│   ├── configStore.js     # processes.json persistence
│   ├── users.json         # Auto-created on first run
│   ├── schedules.json     # Auto-created on first run
│   ├── processes.json     # Your registered scripts
│   ├── .env.example
│   └── package.json
└── frontend/
    ├── index.html         # Main dashboard
    └── login.html         # Login page
```
