import asyncio
import os
import sys
from pathlib import Path

# Ensure `app` package is importable and uses a throwaway SQLite DB for tests.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
_TEST_DB = BACKEND_ROOT / "test_trades.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB.as_posix()}")

# On Windows the default ProactorEventLoop is incompatible with Twisted's
# asyncioreactor (which app.main installs at import time).  Switch to
# SelectorEventLoop before the first import of app code.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine, init_db

# Rebuild the throwaway test schema from the CURRENT models every session.
# create_all never ALTERs an existing table, so a persistent test_trades.db left
# over from an earlier schema would silently shadow newly-added columns (e.g. a
# new alarms column) and fail unrelated tests. drop_all + create_all keeps the
# SQLite test schema in lockstep with the models. (Alembic owns Postgres.)
Base.metadata.drop_all(bind=engine)
init_db()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def auth_client():
    """TestClient with a logged-in session.

    Creates a throwaway user in the test DB, logs in via POST /api/auth/login,
    and returns the client (session cookie is maintained automatically by
    TestClient).  The ``auth_headers`` name from the plan sketch maps to this
    because the app uses session-cookie auth, not Bearer tokens.
    """
    from app.database import SessionLocal
    from app.core.models import User
    from app.core.security import hash_password

    EMAIL = "testuser_alarm@example.com"
    PASSWORD = "testpassword123"

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == EMAIL).first()
        if user is None:
            user = User(email=EMAIL, password_hash=hash_password(PASSWORD), name="Test User")
            db.add(user)
            db.commit()
    finally:
        db.close()

    tc = TestClient(app)
    resp = tc.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return tc


