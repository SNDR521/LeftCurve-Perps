"""POST /api/perps/positions/close — validation, scoping, error mapping."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.database import get_db, Base, make_engine
from app.core.deps import get_current_user
from app.core.models import User
from app.core.security import hash_password
from app.perps.routers import trade as trade_router
from app.perps.services import venue_trade


@pytest.fixture()
def ctx(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("x"))
    s.add(u); s.commit()
    app.dependency_overrides[get_db] = lambda: s
    app.dependency_overrides[get_current_user] = lambda: u
    client = TestClient(app)
    acc_id = client.post("/api/perps/accounts", json={
        "venue": "BYBIT", "label": "Main", "api_key": "k", "api_secret": "s"}).json()["id"]
    yield client, s, acc_id
    app.dependency_overrides.clear(); s.close()


def test_close_requires_exactly_one_of_fraction_qty(ctx):
    client, _, acc_id = ctx
    r = client.post("/api/perps/positions/close",
                    json={"account_id": acc_id, "symbol": "ETHUSDT"})
    assert r.status_code == 422
    r = client.post("/api/perps/positions/close",
                    json={"account_id": acc_id, "symbol": "ETHUSDT",
                          "fraction": 0.5, "qty": 1.0})
    assert r.status_code == 422


def test_close_unknown_or_foreign_account_404(ctx):
    client, s, acc_id = ctx
    r = client.post("/api/perps/positions/close",
                    json={"account_id": 99999, "symbol": "ETHUSDT", "fraction": 0.5})
    assert r.status_code == 404
    # another user's account is invisible to the current user
    other = User(email="b@b.c", password_hash=hash_password("x"))
    s.add(other); s.commit()
    app.dependency_overrides[get_current_user] = lambda: other
    r = client.post("/api/perps/positions/close",
                    json={"account_id": acc_id, "symbol": "ETHUSDT", "fraction": 0.5})
    assert r.status_code == 404


def test_close_happy_path_returns_result_and_kicks_sync(ctx, monkeypatch):
    client, _, acc_id = ctx
    calls = {}
    monkeypatch.setattr(trade_router.venue_trade, "close_position",
                        lambda db, acc, symbol, fraction=None, qty=None:
                        {"status": "accepted", "order_id": "oid",
                         "requested_qty": "1", "venue": "BYBIT"})
    monkeypatch.setattr(trade_router, "_kick_sync",
                        lambda account_id: calls.setdefault("sync", account_id))
    r = client.post("/api/perps/positions/close",
                    json={"account_id": acc_id, "symbol": "ETHUSDT", "fraction": 0.5})
    assert r.status_code == 200
    assert r.json()["order_id"] == "oid"
    assert calls["sync"] == acc_id


def test_close_error_codes_map_to_http_status(ctx, monkeypatch):
    client, _, acc_id = ctx
    cases = {"permission": 403, "no_position": 409, "qty_too_small": 422,
             "unsupported": 400, "venue_rejected": 502}
    for code, status in cases.items():
        def _raise(db, acc, symbol, fraction=None, qty=None, _c=code):
            raise venue_trade.CloseError(_c, f"{_c} message")
        monkeypatch.setattr(trade_router.venue_trade, "close_position", _raise)
        r = client.post("/api/perps/positions/close",
                        json={"account_id": acc_id, "symbol": "ETHUSDT", "fraction": 0.5})
        assert r.status_code == status, code
        assert f"{code} message" in r.json()["detail"]
