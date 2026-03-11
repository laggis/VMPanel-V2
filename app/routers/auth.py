from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlmodel import Session, select
from jose import JWTError, jwt
from app.core.database import engine
from app.models.user import User, Role
from app.core import security
from app.core.config import settings
from app.schemas import Token, TokenData, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

def get_session():
    with Session(engine) as session:
        yield session

async def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    user = session.exec(select(User).where(User.username == token_data.username)).first()
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_admin_user(current_user: User = Depends(get_current_active_user)):
    if current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    return current_user

@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session), request: Request = None):
    from app.models.audit import AuditLog
    user = session.exec(select(User).where(User.username == form_data.username)).first()
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        # Log failed login attempt
        try:
            ip = request.client.host if request and request.client else "unknown"
            fail_log = AuditLog(action="LOGIN_FAILED", details=f"Username: {form_data.username} | IP: {ip}")
            session.add(fail_log)
            session.commit()
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Log successful login
    try:
        ip = request.client.host if request and request.client else "unknown"
        login_log = AuditLog(user_id=user.id, action="LOGIN_SUCCESS", details=f"IP: {ip}")
        session.add(login_log)
        session.commit()
    except Exception:
        pass
    access_token = security.create_access_token(subject=user.username)
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserRead)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

from typing import Optional, List, Dict
from pydantic import BaseModel
import json

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

class ProfileUpdate(BaseModel):
    discord_webhook_url: Optional[str] = None
    discord_webhook_public: Optional[str] = None

class SubUserCreate(BaseModel):
    username: str
    password: str
    permissions: Optional[Dict[str, bool]] = None

class SubUserRead(BaseModel):
    id: int
    username: str
    is_active: bool
    permissions: Optional[Dict[str, bool]] = None

@router.patch("/me")
async def update_user_profile(
    profile: ProfileUpdate,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    # Use exclude_unset=True to distinguish between "not sent" and "sent as null"
    # This allows users to clear their webhooks by sending null
    update_data = profile.dict(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(current_user, key, value)
        
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user

@router.post("/me/password")
async def change_password(
    password_data: PasswordChange,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    if not security.verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    
    current_user.hashed_password = security.get_password_hash(password_data.new_password)
    session.add(current_user)
    session.commit()
    return {"message": "Password updated successfully"}

@router.post("/subusers", response_model=SubUserRead)
async def create_subuser(
    sub: SubUserCreate,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    existing = session.exec(select(User).where(User.username == sub.username)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_pwd = security.get_password_hash(sub.password)
    perms_json = json.dumps(sub.permissions) if sub.permissions else None
    new_user = User(
        username=sub.username,
        hashed_password=hashed_pwd,
        role=Role.USER,
        is_active=True,
        parent_id=current_user.id,
        permissions=perms_json
    )
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    perms = json.loads(new_user.permissions) if new_user.permissions else None
    return SubUserRead(id=new_user.id, username=new_user.username, is_active=new_user.is_active, permissions=perms)

@router.get("/subusers", response_model=List[SubUserRead])
async def list_subusers(
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    subs = session.exec(select(User).where(User.parent_id == current_user.id)).all()
    results: List[SubUserRead] = []
    for u in subs:
        perms = json.loads(u.permissions) if u.permissions else None
        results.append(SubUserRead(id=u.id, username=u.username, is_active=u.is_active, permissions=perms))
    return results
