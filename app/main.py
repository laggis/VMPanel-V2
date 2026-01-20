import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from app.core.database import create_db_and_tables, engine
from app.routers import auth, admin, vm
from app.models.user import User, Role
from app.models.vm import VM
from app.core.security import get_password_hash
from app.services.notification_service import notification_service
from contextlib import asynccontextmanager

async def check_expiring_vms():
    while True:
        try:
            with Session(engine) as session:
                vms = session.exec(select(VM).where(VM.expiration_date != None)).all()
                now = datetime.utcnow()
                
                for vm in vms:
                    if not vm.expiration_date:
                        continue
                        
                    days_left = (vm.expiration_date - now).days
                    
                    # Logic to determine if we should notify
                    # This is a simple implementation that checks periodically
                    # In a production system, you'd want to track "last_notification_sent" to avoid dupes
                    # For now, we'll assume this runs once a day or we accept some dupes if restarted
                    
                    # We can use a simplified logic: 
                    # If we run this loop every 24h, it's fine.
                    # But if we restart, it runs again.
                    # Let's just check specific thresholds and maybe we can't easily avoid dupes without DB changes
                    # But user asked for "massage that will notify me when the time its out like if a but 30 days"
                    
                    msg = None
                    if days_left == 30:
                        msg = f"⚠️ VM **{vm.name}** (ID: {vm.id}) expires in 30 days!"
                    elif days_left == 7:
                        msg = f"⚠️ VM **{vm.name}** (ID: {vm.id}) expires in 7 days!"
                    elif days_left == 3:
                        msg = f"⚠️ VM **{vm.name}** (ID: {vm.id}) expires in 3 days!"
                    elif days_left == 1:
                        msg = f"⚠️ VM **{vm.name}** (ID: {vm.id}) expires tomorrow!"
                    elif days_left == 0:
                        msg = f"🚨 VM **{vm.name}** (ID: {vm.id}) expires TODAY!"
                    elif days_left < 0:
                        # Maybe notify once a week for expired?
                        # For now, let's just skip if deeply expired to avoid spam
                        if days_left == -1:
                             msg = f"❌ VM **{vm.name}** (ID: {vm.id}) has EXPIRED!"
                    
                    if msg:
                        await notification_service.send_discord_alert(msg)
                        
        except Exception as e:
            print(f"Error in expiration checker: {e}")
            
        # Check every 24 hours
        await asyncio.sleep(86400)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    # Create default admin if not exists
    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == "admin")).first()
        if not user:
            hashed_pwd = get_password_hash("admin")
            admin_user = User(username="admin", hashed_password=hashed_pwd, role=Role.ADMIN)
            session.add(admin_user)
            session.commit()
            print("Default admin user created: admin / admin")
    
    # Start background task
    asyncio.create_task(check_expiring_vms())
    
    yield


app = FastAPI(title="VM Control Panel", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(vm.router)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/server/{vm_id}", response_class=HTMLResponse)
async def server_page(request: Request, vm_id: int):
    return templates.TemplateResponse("dashboard.html", {"request": request, "vm_id": vm_id})

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})
