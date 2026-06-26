import pytest
from fastapi import FastAPI, Depends, Request
from starlette.middleware.sessions import SessionMiddleware
from fastapi.testclient import TestClient

from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user


@pytest.fixture()
def app_with_route():
    init_db()
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")

    @app.get("/whoami")
    def whoami(user: User = Depends(get_current_user)):
        return {"email": user.email}

    @app.get("/login-as/{uid}")
    def login_as(uid: int, request: Request):
        request.session["user_id"] = uid
        return {"ok": True}

    return app


def test_unauthenticated_returns_401(app_with_route):
    c = TestClient(app_with_route)
    assert c.get("/whoami").status_code == 401


def test_authenticated_returns_user(app_with_route):
    import uuid
    sub = f"sub-{uuid.uuid4().hex}"
    db = SessionLocal()
    u = User(email=f"{sub}@example.com", password_hash="x")
    db.add(u); db.commit(); db.refresh(u); uid = u.id; db.close()
    c = TestClient(app_with_route)
    c.get(f"/login-as/{uid}")
    r = c.get("/whoami")
    assert r.status_code == 200 and r.json()["email"] == f"{sub}@example.com"
