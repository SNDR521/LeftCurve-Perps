import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.core.models import User, UserPreferences
from app.core.deps import get_current_user


def _make_user(email: str) -> User:
    db = SessionLocal()
    u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close()
    return u


def teardown_function():
    app.dependency_overrides.clear()


@pytest.fixture()
def user_client():
    """Return (TestClient, User) with get_current_user overridden."""
    import uuid
    u = _make_user(f"prefs-{uuid.uuid4().hex}@test.com")
    app.dependency_overrides[get_current_user] = lambda: u
    yield TestClient(app), u


def test_get_defaults_when_no_row(user_client):
    """GET /api/preferences returns DEFAULT_PREFS when no row exists."""
    client, user = user_client
    db = SessionLocal()
    db.query(UserPreferences).filter(UserPreferences.user_id == user.id).delete()
    db.commit(); db.close()

    r = client.get("/api/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["default_period"] == "all"
    assert body["pnl_view"] == "dollars"
    assert body["theme"]["accent"] == "#38bdf8"
    assert isinstance(body["ticker_bar"]["symbols"], list)
    assert len(body["ticker_bar"]["symbols"]) == 10


def test_put_creates_row_and_merges(user_client):
    """PUT with a partial payload creates a DB row and merges into defaults."""
    client, user = user_client
    r = client.put("/api/preferences", json={"pnl_view": "percent"})
    assert r.status_code == 200
    body = r.json()
    # Overridden key
    assert body["pnl_view"] == "percent"
    # Default keys still present
    assert body["default_period"] == "all"
    assert body["theme"]["accent"] == "#38bdf8"
    # Verify row was created in DB
    db = SessionLocal()
    row = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    db.close()
    assert row is not None
    assert row.prefs["pnl_view"] == "percent"


def test_second_put_preserves_other_keys(user_client):
    """A second PUT only updates specified keys; others survive."""
    client, _ = user_client
    client.put("/api/preferences", json={"pnl_view": "percent"})
    r = client.put("/api/preferences", json={"default_period": "1m"})
    assert r.status_code == 200
    body = r.json()
    assert body["pnl_view"] == "percent"   # set in first PUT, must still be there
    assert body["default_period"] == "1m"  # set in second PUT


def test_preferences_require_auth():
    """Unauthenticated requests return 401."""
    # No override — real auth dependency
    c = TestClient(app)
    assert c.get("/api/preferences").status_code == 401
    assert c.put("/api/preferences", json={}).status_code == 401
