import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from app.core.database import create_db_and_tables, engine
from app.routers import auth, admin, vm, network
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
                    notification_data = None
                    
                    if days_left == 30:
                        notification_data = {
                            "title": "📅 Service Expiration Notice",
                            "description": f"Your service for VM **{vm.name}** is expiring in 30 days.",
                            "color": 3447003, # Blue
                            "fields": [
                                {"name": "VM ID", "value": str(vm.id), "inline": True},
                                {"name": "Expiration Date", "value": vm.expiration_date.strftime("%Y-%m-%d"), "inline": True},
                                {"name": "Status", "value": "Active", "inline": True}
                            ]
                        }
                    elif days_left == 7:
                        notification_data = {
                            "title": "⚠️ Service Expiration Warning",
                            "description": f"Your service for VM **{vm.name}** is expiring in 1 week.",
                            "color": 15105570, # Orange
                            "fields": [
                                {"name": "VM ID", "value": str(vm.id), "inline": True},
                                {"name": "Expiration Date", "value": vm.expiration_date.strftime("%Y-%m-%d"), "inline": True},
                                {"name": "Time Remaining", "value": "7 Days", "inline": True}
                            ]
                        }
                    elif days_left == 3:
                        notification_data = {
                            "title": "⚠️ Service Expiration Warning",
                            "description": f"Your service for VM **{vm.name}** is expiring in 3 days.",
                            "color": 15105570, # Orange
                            "fields": [
                                {"name": "VM ID", "value": str(vm.id), "inline": True},
                                {"name": "Expiration Date", "value": vm.expiration_date.strftime("%Y-%m-%d"), "inline": True},
                                {"name": "Time Remaining", "value": "3 Days", "inline": True}
                            ]
                        }
                    elif days_left == 1:
                        notification_data = {
                            "title": "🚨 Urgent: Service Expiring Tomorrow",
                            "description": f"Your service for VM **{vm.name}** expires tomorrow!",
                            "color": 15158332, # Red
                            "fields": [
                                {"name": "VM ID", "value": str(vm.id), "inline": True},
                                {"name": "Expiration Date", "value": vm.expiration_date.strftime("%Y-%m-%d"), "inline": True},
                                {"name": "Action Required", "value": "Please renew immediately", "inline": False}
                            ]
                        }
                    elif days_left == 0:
                        notification_data = {
                            "title": "🚨 Service Expiring Today",
                            "description": f"Your service for VM **{vm.name}** expires TODAY.",
                            "color": 15158332, # Red
                            "fields": [
                                {"name": "VM ID", "value": str(vm.id), "inline": True},
                                {"name": "Expiration Date", "value": vm.expiration_date.strftime("%Y-%m-%d"), "inline": True},
                                {"name": "Status", "value": "Expiring Now", "inline": True}
                            ]
                        }
                    elif days_left == -1:
                        notification_data = {
                            "title": "❌ Service Expired",
                            "description": f"The service for VM **{vm.name}** has EXPIRED.",
                            "color": 0, # Black
                            "fields": [
                                {"name": "VM ID", "value": str(vm.id), "inline": True},
                                {"name": "Expired On", "value": vm.expiration_date.strftime("%Y-%m-%d"), "inline": True},
                                {"name": "Status", "value": "Suspended", "inline": True}
                            ]
                        }
                    
                    if notification_data:
                        await notification_service.send_discord_alert(
                            title=notification_data["title"],
                            description=notification_data["description"],
                            color=notification_data["color"],
                            fields=notification_data["fields"]
                        )
                        
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
app.include_router(network.router)

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
