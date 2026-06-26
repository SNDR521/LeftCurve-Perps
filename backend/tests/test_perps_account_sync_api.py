import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db, Base, make_engine
from sqlalchemy.orm import Session
from app.core.deps import get_current_user
from app.core.models import User
from app.core.security import hash_password


@pytest.fixture()
def client(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("x"))
    s.add(u); s.commit()
    app.dependency_overrides[get_db] = lambda: s
    app.dependency_overrides[get_current_user] = lambda: u
    yield TestClient(app)
    app.dependency_overrides.clear(); s.close()


def test_create_bybit_account_stores_creds_but_never_returns_them(client):
    r = client.post("/api/perps/accounts", json={
        "venue": "BYBIT", "label": "Main", "api_key": "k", "api_secret": "sEcReT"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_credentials"] is True
    assert "api_secret" not in body and "sEcReT" not in r.text

    lst = client.get("/api/perps/accounts").json()
    assert lst[0]["has_credentials"] is True


def test_sync_requires_bybit_with_credentials(client):
    acc = client.post("/api/perps/accounts", json={"venue": "BYBIT", "label": "NoKeys"}).json()
    r = client.post(f"/api/perps/accounts/{acc['id']}/sync")
    assert r.status_code == 400   # no credentials
