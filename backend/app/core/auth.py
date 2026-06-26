from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.models import User
from app.core.deps import get_current_user
from app.core.security import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str


class ProfileBody(BaseModel):
    name: str | None = None


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


class SetupBody(BaseModel):
    email: str
    password: str


def _user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "avatar_url": u.avatar_url}


@router.get("/needs-setup")
def needs_setup(db: Session = Depends(get_db)):
    return {"needs_setup": db.query(User).count() == 0}


@router.post("/setup")
def setup(body: SetupBody, request: Request, db: Session = Depends(get_db)):
    if db.query(User).count() > 0:
        raise HTTPException(status_code=409, detail="Account already exists")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user = User(email=body.email.strip().lower(), password_hash=hash_password(body.password))
    db.add(user); db.commit(); db.refresh(user)
    request.session["user_id"] = user.id
    return _user_out(user)


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    request.session["user_id"] = user.id
    return _user_out(user)


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_out(user)


@router.put("/me")
def update_me(body: ProfileBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.name is not None:
        user.name = body.name.strip() or None
    db.commit(); db.refresh(user)
    return _user_out(user)


@router.post("/change-password")
def change_password(body: ChangePasswordBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}
