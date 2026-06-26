import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.security import hash_password


@pytest.fixture(autouse=True)
def _db():
    init_db()
    db = SessionLocal(); db.query(User).delete(); db.commit()
    db.add(User(email="a@x.com", password_hash=hash_password("pw123")))
    db.commit(); db.close()


def test_login_success_sets_session():
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "a@x.com", "password": "pw123"})
    assert r.status_code == 200 and r.json()["email"] == "a@x.com"
    assert c.get("/api/auth/me").status_code == 200


def test_login_wrong_password_401():
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": "a@x.com", "password": "nope"}).status_code == 401


def test_login_unknown_email_401():
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": "ghost@x.com", "password": "pw123"}).status_code == 401


def test_logout_clears_session():
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "a@x.com", "password": "pw123"})
    assert c.get("/api/auth/me").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401
