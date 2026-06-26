"""Tests for app/workflow/models.py — Playbook, PlanCard, Review."""
import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User  # noqa: F401 — needed so users table is created
from app.core.security import hash_password
from app.workflow.models import Playbook, PlanCard, Review

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    # Ensure ALL model tables (including users) are created in the tmp engine
    import app.core.models  # noqa: F401
    import app.perps.models  # noqa: F401
    import app.workflow.models  # noqa: F401
    Base.metadata.create_all(engine)
    s = Session(engine)
    u1 = User(email="alice@test.com", password_hash=hash_password("x"))
    u2 = User(email="bob@test.com", password_hash=hash_password("y"))
    s.add_all([u1, u2])
    s.commit()
    yield s, u1, u2
    s.close()


# ---------------------------------------------------------------------------
# Playbook tests
# ---------------------------------------------------------------------------

def test_playbook_roundtrip(db):
    s, u1, u2 = db
    pb = Playbook(
        user_id=u1.id,
        name="Breakout",
        context_requirements="Above 200MA",
        entry_triggers="Break of pre-market high",
        invalidation="Back below trigger",
        management="Trail to breakeven",
        notes="Best in London session",
    )
    s.add(pb)
    s.commit()
    s.refresh(pb)

    assert pb.id is not None
    assert pb.name == "Breakout"
    assert pb.context_requirements == "Above 200MA"
    assert pb.entry_triggers == "Break of pre-market high"
    assert pb.invalidation == "Back below trigger"
    assert pb.management == "Trail to breakeven"
    assert pb.notes == "Best in London session"
    assert pb.created_at is not None
    assert pb.updated_at is not None


def test_playbook_name_unique_per_user(db):
    """Same user cannot have two playbooks with the same name."""
    s, u1, u2 = db
    pb1 = Playbook(user_id=u1.id, name="Reversal")
    s.add(pb1)
    s.commit()

    pb2 = Playbook(user_id=u1.id, name="Reversal")
    s.add(pb2)
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()


def test_playbook_same_name_different_user_ok(db):
    """Two different users CAN have the same playbook name."""
    s, u1, u2 = db
    pb1 = Playbook(user_id=u1.id, name="Reversal")
    pb2 = Playbook(user_id=u2.id, name="Reversal")
    s.add_all([pb1, pb2])
    s.commit()  # must not raise

    assert pb1.id != pb2.id
    assert pb1.name == pb2.name == "Reversal"


# ---------------------------------------------------------------------------
# PlanCard tests
# ---------------------------------------------------------------------------

def test_plan_card_roundtrip(db):
    s, u1, _ = db
    today = datetime.date(2026, 6, 11)
    card = PlanCard(
        user_id=u1.id,
        date=today,
        session_start_hour=6,
        regime_snapshot={"CRYPTO": {"breadth": {"above_200ma": 0.6}}},
        shortlist=["BTCUSDT", "ETHUSDT"],
        mental_state="Calm",
        max_trades=3,
        max_daily_loss=200.0,
        r_per_trade=1.5,
        circuit_rules="Stop after 2 losses",
        key_lesson="Waited for confirmation",
        tomorrow_focus="Size down on low conviction",
    )
    s.add(card)
    s.commit()
    s.refresh(card)

    assert card.id is not None
    assert card.date == today
    assert card.session_start_hour == 6
    assert card.regime_snapshot == {"CRYPTO": {"breadth": {"above_200ma": 0.6}}}
    assert card.shortlist == ["BTCUSDT", "ETHUSDT"]
    assert card.mental_state == "Calm"
    assert card.max_trades == 3
    assert card.max_daily_loss == pytest.approx(200.0)
    assert card.r_per_trade == pytest.approx(1.5)
    assert card.circuit_rules == "Stop after 2 losses"
    assert card.key_lesson == "Waited for confirmation"
    assert card.tomorrow_focus == "Size down on low conviction"
    assert card.created_at is not None


def test_plan_card_date_unique_per_user(db):
    """Same user cannot have two plan cards for the same date."""
    s, u1, _ = db
    today = datetime.date(2026, 6, 11)
    c1 = PlanCard(user_id=u1.id, date=today)
    s.add(c1)
    s.commit()

    c2 = PlanCard(user_id=u1.id, date=today)
    s.add(c2)
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()


def test_plan_card_same_date_different_user_ok(db):
    """Two different users CAN have plan cards on the same date."""
    s, u1, u2 = db
    today = datetime.date(2026, 6, 11)
    c1 = PlanCard(user_id=u1.id, date=today)
    c2 = PlanCard(user_id=u2.id, date=today)
    s.add_all([c1, c2])
    s.commit()  # must not raise

    assert c1.id != c2.id


def test_plan_card_shortlist_json_list(db):
    """shortlist is stored and retrieved as a JSON list."""
    s, u1, _ = db
    card = PlanCard(user_id=u1.id, date=datetime.date(2026, 6, 12),
                    shortlist=["BTCUSDT", "SOLUSDT", "AVAXUSDT"])
    s.add(card)
    s.commit()
    s.refresh(card)
    assert isinstance(card.shortlist, list)
    assert card.shortlist == ["BTCUSDT", "SOLUSDT", "AVAXUSDT"]


def test_plan_card_regime_snapshot_json_dict(db):
    """regime_snapshot is stored and retrieved as a JSON dict."""
    s, u1, _ = db
    snapshot = {
        "CRYPTO": {"breadth": {"above_20ma": 0.7, "new_highs": 12}, "top_themes": []},
        "EQUITY": {"breadth": {"above_20ma": 0.5, "new_highs": 3}, "top_themes": []},
    }
    card = PlanCard(user_id=u1.id, date=datetime.date(2026, 6, 13),
                    regime_snapshot=snapshot)
    s.add(card)
    s.commit()
    s.refresh(card)
    assert card.regime_snapshot["CRYPTO"]["breadth"]["above_20ma"] == pytest.approx(0.7)
    assert card.regime_snapshot["EQUITY"]["breadth"]["new_highs"] == 3


def test_plan_card_nullable_fields(db):
    """A minimal PlanCard with only required fields is valid."""
    s, u1, _ = db
    card = PlanCard(user_id=u1.id, date=datetime.date(2026, 6, 14))
    s.add(card)
    s.commit()
    s.refresh(card)
    assert card.shortlist is None
    assert card.regime_snapshot is None
    assert card.max_trades is None
    assert card.max_daily_loss is None


# ---------------------------------------------------------------------------
# Review tests
# ---------------------------------------------------------------------------

def test_review_roundtrip(db):
    s, u1, _ = db
    rev = Review(
        user_id=u1.id,
        period_type="WEEK",
        period_start=datetime.date(2026, 6, 8),
        what_worked="Waited for confirmation",
        what_didnt="Chased gap fills",
        next_focus="Stick to shortlist",
    )
    s.add(rev)
    s.commit()
    s.refresh(rev)

    assert rev.id is not None
    assert rev.period_type == "WEEK"
    assert rev.period_start == datetime.date(2026, 6, 8)
    assert rev.what_worked == "Waited for confirmation"
    assert rev.what_didnt == "Chased gap fills"
    assert rev.next_focus == "Stick to shortlist"
    assert rev.created_at is not None


def test_review_uniqueness_user_period_type_start(db):
    """Same user cannot have two reviews with the same (period_type, period_start)."""
    s, u1, _ = db
    r1 = Review(user_id=u1.id, period_type="WEEK",
                period_start=datetime.date(2026, 6, 8))
    s.add(r1)
    s.commit()

    r2 = Review(user_id=u1.id, period_type="WEEK",
                period_start=datetime.date(2026, 6, 8))
    s.add(r2)
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()


def test_review_same_period_different_user_ok(db):
    """Two different users CAN have reviews for the same period."""
    s, u1, u2 = db
    r1 = Review(user_id=u1.id, period_type="WEEK",
                period_start=datetime.date(2026, 6, 8))
    r2 = Review(user_id=u2.id, period_type="WEEK",
                period_start=datetime.date(2026, 6, 8))
    s.add_all([r1, r2])
    s.commit()  # must not raise

    assert r1.id != r2.id


def test_review_different_period_type_same_start_ok(db):
    """WEEK and MONTH reviews with the same start date are distinct."""
    s, u1, _ = db
    r1 = Review(user_id=u1.id, period_type="WEEK",
                period_start=datetime.date(2026, 6, 1))
    r2 = Review(user_id=u1.id, period_type="MONTH",
                period_start=datetime.date(2026, 6, 1))
    s.add_all([r1, r2])
    s.commit()  # must not raise

    assert r1.id != r2.id
