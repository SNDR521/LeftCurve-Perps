from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User


def _reset():
    init_db()
    db = SessionLocal(); db.query(User).delete(); db.commit(); db.close()


def test_needs_setup_then_create_then_login():
    _reset()
    c = TestClient(app)
    assert c.get("/api/auth/needs-setup").json() == {"needs_setup": True}

    r = c.post("/api/auth/setup", json={"email": "me@x.com", "password": "password123"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "me@x.com"

    assert c.get("/api/auth/needs-setup").json() == {"needs_setup": False}

    r2 = c.post("/api/auth/setup", json={"email": "two@x.com", "password": "password123"})
    assert r2.status_code == 409

    assert c.post("/api/auth/login", json={"email": "me@x.com", "password": "password123"}).status_code == 200


def test_setup_rejects_short_password():
    _reset()
    c = TestClient(app)
    r = c.post("/api/auth/setup", json={"email": "me@x.com", "password": "short"})
    assert r.status_code == 400
