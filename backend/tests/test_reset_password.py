import pytest

from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.security import hash_password, verify_password
from app.core.reset_password import reset_password


def _reset():
    init_db()
    db = SessionLocal(); db.query(User).delete(); db.commit(); db.close()


def test_reset_password_changes_hash():
    _reset()
    db = SessionLocal()
    u = User(email="owner@x.com", password_hash=hash_password("oldpassword1"))
    db.add(u); db.commit(); db.close()

    reset_password("owner@x.com", "newpassword1")

    db = SessionLocal()
    user = db.query(User).filter(User.email == "owner@x.com").first()
    assert user is not None
    assert verify_password("newpassword1", user.password_hash)
    assert not verify_password("oldpassword1", user.password_hash)
    db.close()


def test_reset_password_unknown_email_raises():
    _reset()
    with pytest.raises(ValueError, match="ghost@x.com"):
        reset_password("ghost@x.com", "newpassword1")
