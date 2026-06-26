"""Review draft + saved-review endpoint tests.

Covers GET /api/workflow/reviews/draft (period math, perps stats, adherence with
null-excluded days, flagged worst trades, days_without_card), GET/PUT
/api/workflow/reviews (upsert + round-trip + skeleton), type validation,
isolation and 401.

Seeded week (start 2026-06-08 Monday):
  day1 (06-08): plan card with commitments (max_trades=3) + 1 perps trade  → adherent
  day2 (06-09): plan card with max_trades=1 + 2 perps trades              → breached
  day3 (06-10): plan card with NO commitments (no trades in perps)        → adherent null
  day4 (06-11): NO plan card, but 1 perps trade (a big -500 loser)       → days_without_card

Note: prop seeding removed in Task 1.3 (perps-only extraction). Tests that
previously checked prop workspace stats or prop-only views have been adjusted
to reflect the perps-only scoring.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user

from app.workflow.models import PlanCard, Review
from app.perps.models import (
    ExchangeAccount, Position, Venue, AssetClass, Direction, PositionStatus,
    OpenedAtSource,
)


# ── fixtures / helpers ────────────────────────────────────────────────────────

def _user(email: str) -> User:
    db = SessionLocal()
    u = User(email=email, password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.expunge(u)
    db.close()
    return u


@pytest.fixture()
def setup():
    init_db()
    db = SessionLocal()
    for M in (Position, ExchangeAccount, Review, PlanCard, User):
        db.query(M).delete()
    db.commit()
    db.close()
    return _user("rev@x.com")


def _as(u: User):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


# ── seeding helpers ───────────────────────────────────────────────────────────

def _perps_account(user_id: int) -> int:
    db = SessionLocal()
    acc = ExchangeAccount(user_id=user_id, venue=Venue.BYBIT, label="b")
    db.add(acc)
    db.commit()
    aid = acc.id
    db.close()
    return aid


def _seed_perps(user_id: int, acc_id: int, *, symbol: str, pnl: float,
                closed_at: datetime, r_multiple=None, key: str) -> int:
    db = SessionLocal()
    pos = Position(
        user_id=user_id,
        exchange_account_id=acc_id,
        symbol=symbol,
        asset_class=AssetClass.PERP,
        direction=Direction.LONG,
        status=PositionStatus.CLOSED,
        opened_at=closed_at - timedelta(hours=1),
        closed_at=closed_at,
        avg_entry=100.0,
        avg_exit=105.0,
        quantity=1.0,
        realized_pnl=pnl,
        total_fees=0.0,
        total_funding=0.0,
        r_multiple=r_multiple,
        opened_at_source=OpenedAtSource.EXACT,
        position_key=key,
    )
    db.add(pos)
    db.commit()
    pid = pos.id
    db.close()
    return pid


def _seed_card(user_id: int, d, **fields) -> int:
    db = SessionLocal()
    card = PlanCard(user_id=user_id, date=d, session_start_hour=0, **fields)
    db.add(card)
    db.commit()
    cid = card.id
    db.close()
    return cid


# Build the full seeded week described in the module docstring.
def _seed_week(user) -> dict:
    from datetime import date
    acc_id = _perps_account(user.id)
    ids = {}
    # day1 adherent: card max_trades=3, 1 perps trade
    _seed_card(user.id, date(2026, 6, 8), max_trades=3)
    ids["d1"] = _seed_perps(user.id, acc_id, symbol="BTCUSDT", pnl=50.0,
                            closed_at=datetime(2026, 6, 8, 10), key="k:d1")
    # day2 breached: card max_trades=1, 2 perps trades
    _seed_card(user.id, date(2026, 6, 9), max_trades=1)
    _seed_perps(user.id, acc_id, symbol="ETHUSDT", pnl=20.0,
                closed_at=datetime(2026, 6, 9, 10), key="k:d2a")
    _seed_perps(user.id, acc_id, symbol="ETHUSDT", pnl=-30.0,
                closed_at=datetime(2026, 6, 9, 12), key="k:d2b")
    # day3 adherent null: card NO commitments, no perps trades in this period
    _seed_card(user.id, date(2026, 6, 10))
    # day4 NO card, big loser
    ids["loser"] = _seed_perps(user.id, acc_id, symbol="SOLUSDT", pnl=-500.0,
                               closed_at=datetime(2026, 6, 11, 9), key="k:loser")
    ids["acc"] = acc_id
    return ids


# ── draft: period math ────────────────────────────────────────────────────────

def test_draft_week_period_end(setup):
    _as(setup)
    c = TestClient(app)
    r = c.get("/api/workflow/reviews/draft", params={"type": "WEEK", "start": "2026-06-08"})
    assert r.status_code == 200
    period = r.json()["period"]
    assert period["type"] == "WEEK"
    assert period["start"] == "2026-06-08"
    assert period["end"] == "2026-06-15"  # start + 7 days


def test_draft_month_period_end(setup):
    _as(setup)
    c = TestClient(app)
    r = c.get("/api/workflow/reviews/draft", params={"type": "MONTH", "start": "2026-06-01"})
    assert r.status_code == 200
    period = r.json()["period"]
    assert period["type"] == "MONTH"
    assert period["start"] == "2026-06-01"
    assert period["end"] == "2026-07-01"  # first of next month


def test_draft_month_period_end_december_rolls_year(setup):
    _as(setup)
    c = TestClient(app)
    r = c.get("/api/workflow/reviews/draft", params={"type": "MONTH", "start": "2026-12-01"})
    assert r.json()["period"]["end"] == "2027-01-01"


def test_draft_bad_type_422(setup):
    _as(setup)
    c = TestClient(app)
    r = c.get("/api/workflow/reviews/draft", params={"type": "DAY", "start": "2026-06-08"})
    assert r.status_code == 422


# ── draft: stats ──────────────────────────────────────────────────────────────

def test_draft_stats_perps_workspace(setup):
    """Perps workspace returns perps-only stats."""
    _as(setup)
    _seed_week(setup)
    c = TestClient(app)

    perps = c.get("/api/workflow/reviews/draft",
                  params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    assert perps["workspace"] == "perps"
    # d1 +50, d2a +20, d2b -30, loser -500 = 4 trades
    assert perps["stats"]["total_trades"] == 4
    assert abs(perps["stats"]["total_pnl"] - (-460.0)) < 0.01
    assert abs(perps["stats"]["win_rate"] - 50.0) < 0.01


def test_draft_bad_workspace_422(setup):
    _as(setup)
    c = TestClient(app)
    r = c.get("/api/workflow/reviews/draft",
              params={"type": "WEEK", "start": "2026-06-08", "workspace": "crypto"})
    assert r.status_code == 422


# ── draft: adherence ──────────────────────────────────────────────────────────

def test_draft_adherence_summary(setup):
    _as(setup)
    _seed_week(setup)
    c = TestClient(app)
    body = c.get("/api/workflow/reviews/draft",
                 params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    adh = body["adherence"]
    # 3 cards in week (d1, d2, d3)
    assert adh["days_with_cards"] == 3
    # d3 has no commitments → excluded; d1 + d2 evaluated
    assert adh["days_evaluated"] == 2
    # d1 adherent, d2 breached
    assert adh["adherent_days"] == 1
    assert adh["rate_pct"] == 50.0


def test_draft_per_day_includes_null_case(setup):
    _as(setup)
    _seed_week(setup)
    c = TestClient(app)
    body = c.get("/api/workflow/reviews/draft",
                 params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    per_day = {row["date"]: row for row in body["adherence"]["per_day"]}

    assert per_day["2026-06-08"]["adherent"] is True
    assert per_day["2026-06-08"]["trades_count"] == 1
    assert per_day["2026-06-09"]["adherent"] is False
    assert per_day["2026-06-09"]["trades_count"] == 2
    # d3: card with no commitments → adherent null (excluded from rate)
    assert per_day["2026-06-10"]["adherent"] is None
    assert per_day["2026-06-10"]["trades_count"] == 0   # no perps trades on this day


def test_draft_rate_null_when_nothing_evaluated(setup):
    """A card-less, trade-less period → rate_pct is null."""
    _as(setup)
    c = TestClient(app)
    body = c.get("/api/workflow/reviews/draft",
                 params={"type": "WEEK", "start": "2026-06-08"}).json()
    adh = body["adherence"]
    assert adh["days_with_cards"] == 0
    assert adh["days_evaluated"] == 0
    assert adh["adherent_days"] == 0
    assert adh["rate_pct"] is None


# ── draft: flagged + days_without_card ────────────────────────────────────────

def test_draft_flagged_worst_first(setup):
    _as(setup)
    _seed_week(setup)
    c = TestClient(app)
    body = c.get("/api/workflow/reviews/draft",
                 params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    flagged = body["flagged"]
    assert len(flagged) <= 3
    worst = flagged[0]
    assert abs(worst["pnl"] - (-500.0)) < 0.01
    assert worst["workspace"] == "perps"
    assert worst["symbol"] == "SOLUSDT"
    assert "id" in worst
    assert "r" in worst


def test_draft_days_without_card(setup):
    _as(setup)
    _seed_week(setup)
    c = TestClient(app)
    body = c.get("/api/workflow/reviews/draft",
                 params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    # day4 (06-11) had a perps trade but no card → at least 1
    assert body["days_without_card"] >= 1


def test_draft_flagged_perps_only(setup):
    """All flagged trades are perps workspace; no prop trades appear."""
    _as(setup)
    _seed_week(setup)
    c = TestClient(app)
    body = c.get("/api/workflow/reviews/draft",
                 params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    assert body["flagged"]  # non-empty
    assert all(f["workspace"] == "perps" for f in body["flagged"])


# ── saved review: GET skeleton / PUT upsert / round-trip ──────────────────────

def test_get_review_skeleton_when_none(setup):
    _as(setup)
    c = TestClient(app)
    r = c.get("/api/workflow/reviews", params={"type": "WEEK", "start": "2026-06-08"})
    assert r.status_code == 200
    body = r.json()
    assert body["period_type"] == "WEEK"
    assert body["period_start"] == "2026-06-08"
    assert body["what_worked"] is None
    assert body["what_didnt"] is None
    assert body["next_focus"] is None


def test_put_review_upsert_and_roundtrip(setup):
    _as(setup)
    c = TestClient(app)
    payload = {
        "period_type": "WEEK",
        "period_start": "2026-06-08",
        "what_worked": "Stuck to shortlist",
        "what_didnt": "Overtraded Tuesday",
        "next_focus": "Cut size after a loss",
    }
    r = c.put("/api/workflow/reviews", json=payload)
    assert r.status_code == 200
    assert r.json()["what_worked"] == "Stuck to shortlist"

    # GET returns the saved row.
    g = c.get("/api/workflow/reviews", params={"type": "WEEK", "start": "2026-06-08"})
    assert g.json()["what_didnt"] == "Overtraded Tuesday"

    # Second PUT updates in place (upsert, not duplicate).
    payload["what_worked"] = "Patience"
    c.put("/api/workflow/reviews", json=payload)
    g2 = c.get("/api/workflow/reviews", params={"type": "WEEK", "start": "2026-06-08"})
    assert g2.json()["what_worked"] == "Patience"

    db = SessionLocal()
    n = db.query(Review).filter(Review.user_id == setup.id).count()
    db.close()
    assert n == 1


def test_put_review_bad_type_422(setup):
    _as(setup)
    c = TestClient(app)
    r = c.put("/api/workflow/reviews", json={
        "period_type": "DAY", "period_start": "2026-06-08",
    })
    assert r.status_code == 422


# ── auth + isolation ──────────────────────────────────────────────────────────

def test_unauthenticated_401(setup):
    app.dependency_overrides.clear()
    c = TestClient(app)
    assert c.get("/api/workflow/reviews/draft",
                 params={"type": "WEEK", "start": "2026-06-08"}).status_code == 401
    assert c.get("/api/workflow/reviews",
                 params={"type": "WEEK", "start": "2026-06-08"}).status_code == 401
    assert c.put("/api/workflow/reviews", json={
        "period_type": "WEEK", "period_start": "2026-06-08"}).status_code == 401


def test_user_isolation(setup):
    _as(setup)
    c = TestClient(app)
    c.put("/api/workflow/reviews", json={
        "period_type": "WEEK", "period_start": "2026-06-08",
        "what_worked": "mine",
    })

    other = _user("iso-rev@x.com")
    _as(other)
    g = c.get("/api/workflow/reviews", params={"type": "WEEK", "start": "2026-06-08"})
    # Other user sees a skeleton, not my saved review.
    assert g.json()["what_worked"] is None


# ── per-workspace model constraint ────────────────────────────────────────────

def test_review_workspace_unique_per_workspace(setup):
    """Same (user, period_type, period_start) is allowed once PER workspace,
    and rejected for a duplicate within the same workspace."""
    from datetime import date
    import sqlalchemy.exc
    db = SessionLocal()
    db.add(Review(user_id=setup.id, period_type="WEEK",
                  period_start=date(2026, 6, 8), workspace="prop", what_worked="p"))
    db.add(Review(user_id=setup.id, period_type="WEEK",
                  period_start=date(2026, 6, 8), workspace="perps", what_worked="x"))
    db.commit()  # different workspace → OK
    db.add(Review(user_id=setup.id, period_type="WEEK",
                  period_start=date(2026, 6, 8), workspace="prop", what_worked="dup"))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.commit()
    db.rollback()
    db.close()


# ── saved review: per-workspace keying ───────────────────────────────────────

def test_saved_review_independent_per_workspace(setup):
    _as(setup)
    c = TestClient(app)
    base = {"period_type": "WEEK", "period_start": "2026-06-08"}

    c.put("/api/workflow/reviews", json={**base, "workspace": "prop", "what_worked": "prop note"})
    c.put("/api/workflow/reviews", json={**base, "workspace": "perps", "what_worked": "perps note"})

    p = c.get("/api/workflow/reviews",
              params={"type": "WEEK", "start": "2026-06-08", "workspace": "prop"}).json()
    x = c.get("/api/workflow/reviews",
              params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    assert p["what_worked"] == "prop note" and p["workspace"] == "prop"
    assert x["what_worked"] == "perps note" and x["workspace"] == "perps"

    # two independent rows for the same period
    db = SessionLocal()
    n = db.query(Review).filter(Review.user_id == setup.id).count()
    db.close()
    assert n == 2


def test_get_review_skeleton_echoes_workspace(setup):
    _as(setup)
    c = TestClient(app)
    g = c.get("/api/workflow/reviews",
              params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    assert g["workspace"] == "perps"
    assert g["what_worked"] is None


def test_put_review_bad_workspace_422(setup):
    _as(setup)
    c = TestClient(app)
    r = c.put("/api/workflow/reviews", json={
        "period_type": "WEEK", "period_start": "2026-06-08", "workspace": "crypto"})
    assert r.status_code == 422


def test_saved_review_guided_fields_roundtrip(setup):
    _as(setup)
    c = TestClient(app)
    payload = {
        "period_type": "WEEK", "period_start": "2026-06-08", "workspace": "perps",
        "probe_flags": ["Entered too late", "Risked too much"],
        "problem": "late entries", "why": "watching instead of executing",
        "next_focus": "set alerts at the level and act",  # reused as Action
    }
    r = c.put("/api/workflow/reviews", json=payload)
    assert r.status_code == 200, r.text
    g = c.get("/api/workflow/reviews",
              params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    assert g["probe_flags"] == ["Entered too late", "Risked too much"]
    assert g["problem"] == "late entries"
    assert g["why"] == "watching instead of executing"
    assert g["next_focus"] == "set alerts at the level and act"


def _seed_perps_journal(user_id, position_key, mistake_tags):
    from app.perps.models import PerpsJournal
    db = SessionLocal()
    db.add(PerpsJournal(user_id=user_id, position_key=position_key, mistake_tags=mistake_tags))
    db.commit(); db.close()


def test_draft_demons_perps(setup):
    _as(setup)
    acc = _perps_account(setup.id)
    # three closed perps trades in the week, two tagged "Late Entry" back-to-back
    from datetime import datetime
    _seed_perps(setup.id, acc, symbol="BTCUSDT", pnl=-10,
                closed_at=datetime(2026, 6, 8, 10), key="d:1")
    _seed_perps(setup.id, acc, symbol="ETHUSDT", pnl=-20,
                closed_at=datetime(2026, 6, 9, 10), key="d:2")
    _seed_perps(setup.id, acc, symbol="SOLUSDT", pnl=5,
                closed_at=datetime(2026, 6, 10, 10), key="d:3")
    _seed_perps_journal(setup.id, "d:1", ["Late Entry"])
    _seed_perps_journal(setup.id, "d:2", ["Late Entry", "Sized Up"])
    _seed_perps_journal(setup.id, "d:3", ["Sized Up"])

    c = TestClient(app)
    body = c.get("/api/workflow/reviews/draft",
                 params={"type": "WEEK", "start": "2026-06-08", "workspace": "perps"}).json()
    demons = body["demons"]
    ranked = {r["demon"]: r for r in demons["ranked"]}
    assert ranked["Late Entry"]["count"] == 2
    assert ranked["Late Entry"]["max_streak"] == 2   # d:1, d:2 consecutive
    assert ranked["Sized Up"]["count"] == 2
    assert ranked["Sized Up"]["max_streak"] == 2     # d:2 and d:3 are consecutive
    assert demons["top"]["demon"] in ("Late Entry", "Sized Up")  # tied count=2
    assert demons["alarm"] is None                   # no run >= 3

    # "prop" workspace now returns identical perps demons (perps-only mode);
    # the response also reports workspace == "perps", never "prop".
    prop = c.get("/api/workflow/reviews/draft",
                 params={"type": "WEEK", "start": "2026-06-08", "workspace": "prop"}).json()
    assert prop["workspace"] == "perps"
    assert prop["demons"]["ranked"] == demons["ranked"]
    assert prop["demons"]["alarm"] is None
