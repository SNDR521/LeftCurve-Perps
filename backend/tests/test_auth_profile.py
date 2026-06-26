import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.database import get_db, Base, make_engine
from app.core.deps import get_current_user
from app.core.models import User
from app.core.security import hash_password, verify_password


@pytest.fixture()
def ctx(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("oldpassword"), name="Old")
    s.add(u); s.commit()
    app.dependency_overrides[get_db] = lambda: s
    app.dependency_overrides[get_current_user] = lambda: u
    yield TestClient(app), s, u
    app.dependency_overrides.clear(); s.close()


def test_update_name(ctx):
    client, s, u = ctx
    r = client.put("/api/auth/me", json={"name": "New Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"
    s.refresh(u); assert u.name == "New Name"


def test_change_password_success(ctx):
    client, s, u = ctx
    r = client.post("/api/auth/change-password",
                    json={"current_password": "oldpassword", "new_password": "brandnewpass"})
    assert r.status_code == 200
    s.refresh(u)
    assert verify_password("brandnewpass", u.password_hash)
    assert not verify_password("oldpassword", u.password_hash)


def test_change_password_wrong_current(ctx):
    client, s, u = ctx
    r = client.post("/api/auth/change-password",
                    json={"current_password": "WRONG", "new_password": "brandnewpass"})
    assert r.status_code == 400


def test_change_password_too_short(ctx):
    client, s, u = ctx
    r = client.post("/api/auth/change-password",
                    json={"current_password": "oldpassword", "new_password": "short"})
    assert r.status_code == 400
