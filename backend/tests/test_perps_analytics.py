from datetime import datetime, timezone
import pytest
from app.database import init_db, SessionLocal
from app.core.models import User
from app.perps.models import Position, Direction, PositionStatus, AssetClass, PerpsJournal, OpenedAtSource
import app.perps.services.analytics as pa

def _pos(uid, aid, **kw):
    d = dict(user_id=uid, exchange_account_id=aid, symbol="BTCUSDT", asset_class=AssetClass.PERP,
             direction=Direction.LONG, status=PositionStatus.CLOSED, avg_entry=100.0, avg_exit=110.0,
             quantity=1.0, realized_pnl=0.0, total_fees=0.0, total_funding=0.0, r_multiple=None,
             duration_seconds=300,
             opened_at=datetime(2024,1,1,9,tzinfo=timezone.utc),
             closed_at=datetime(2024,1,1,10,tzinfo=timezone.utc),
             opened_at_source=OpenedAtSource.EXACT)
    d.update(kw); return Position(**d)

@pytest.fixture()
def seeded():
    init_db()
    db = SessionLocal()
    db.query(PerpsJournal).delete(); db.query(Position).delete(); db.query(User).delete(); db.commit()
    u = User(email="p@x.com", password_hash="x"); db.add(u); db.commit(); db.refresh(u)
    db.add(_pos(u.id, 1, realized_pnl=10, r_multiple=2.0, closed_at=datetime(2024,1,1,10,tzinfo=timezone.utc)))
    db.add(_pos(u.id, 1, realized_pnl=20, r_multiple=4.0, closed_at=datetime(2024,1,2,10,tzinfo=timezone.utc)))
    db.add(_pos(u.id, 1, realized_pnl=-5, direction=Direction.SHORT, closed_at=datetime(2024,1,3,10,tzinfo=timezone.utc)))
    db.commit(); uid = u.id; db.close(); return uid

def test_overview(seeded):
    db = SessionLocal()
    ov = pa.compute_overview(db, user_id=seeded)
    assert ov.total_trades == 3
    assert ov.winning_trades == 2 and ov.losing_trades == 1
    assert ov.win_rate == pytest.approx(2/3*100)
    assert ov.total_pnl == pytest.approx(25)
    assert ov.avg_win == pytest.approx(15)
    assert ov.avg_loss == pytest.approx(-5)
    assert ov.profit_factor == pytest.approx(round(30/5, 2))
    assert ov.expectancy == pytest.approx(25/3)
    assert ov.avg_r_multiple == pytest.approx(3.0)
    assert ov.max_consecutive_wins == 2 and ov.max_consecutive_losses == 1
    assert ov.best_trade == pytest.approx(20) and ov.worst_trade == pytest.approx(-5)
    db.close()

def test_overview_empty():
    init_db()
    db = SessionLocal(); db.query(Position).delete(); db.query(User).delete(); db.commit()
    u = User(email="z@x.com", password_hash="x"); db.add(u); db.commit(); db.refresh(u); uid=u.id; db.close()
    db = SessionLocal()
    ov = pa.compute_overview(db, user_id=uid)
    assert ov.total_trades == 0 and ov.total_pnl == 0
    db.close()

def test_daily_pnl(seeded):
    db = SessionLocal()
    rows = pa.compute_daily_pnl(db, user_id=seeded)
    assert [r.date for r in rows] == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert [r.pnl for r in rows] == pytest.approx([10, 20, -5])
    assert [r.cumulative_pnl for r in rows] == pytest.approx([10, 30, 25])
    assert rows[0].wins == 1 and rows[2].losses == 1
    db.close()

def test_by_symbol(seeded):
    db = SessionLocal()
    rows = pa.compute_performance_by_group(db, "symbol", user_id=seeded)
    assert len(rows) == 1 and rows[0].group == "BTCUSDT"
    assert rows[0].trade_count == 3 and rows[0].total_pnl == pytest.approx(25)
    assert rows[0].win_rate == pytest.approx(2/3*100)
    assert rows[0].profit_factor == pytest.approx(6.0)
    db.close()

def test_by_direction(seeded):
    db = SessionLocal()
    rows = {r.group: r for r in pa.compute_performance_by_group(db, "direction", user_id=seeded)}
    assert rows["LONG"].trade_count == 2 and rows["LONG"].total_pnl == pytest.approx(30)
    assert rows["SHORT"].trade_count == 1 and rows["SHORT"].total_pnl == pytest.approx(-5)
    db.close()

def test_holdtime_and_rdist(seeded):
    db = SessionLocal()
    ht = pa.compute_by_holdtime(db, user_id=seeded)
    assert sum(b.trade_count for b in ht) == 3
    rd = pa.compute_r_distribution(db, user_id=seeded)
    assert sum(b["trade_count"] for b in rd) == 2
    db.close()

def test_heatmap_and_session(seeded):
    db = SessionLocal()
    hm = pa.compute_heatmap(db, user_id=seeded)
    assert sum(c.trade_count for c in hm) == 3
    sess = pa.compute_by_session(db, user_id=seeded)
    assert sum(s.trade_count for s in sess) == 3
    db.close()

def test_by_grade_setup_mistake(seeded):
    db = SessionLocal()
    p = db.query(Position).order_by(Position.id).first()
    if not p.position_key:
        p.position_key = f"x:{p.id}"; db.commit()
    key = p.position_key
    db.add(PerpsJournal(user_id=seeded, position_key=key, setup_name="Breakout", grade="A", mistake_tags=["fomo"]))
    db.commit(); db.close()
    db = SessionLocal()
    grades = {r.group: r for r in pa.compute_performance_by_group(db, "grade", user_id=seeded)}
    assert "A" in grades and grades["A"].trade_count == 1
    assert "Ungraded" in grades  # the other 2 positions
    setups = {r.group: r for r in pa.compute_performance_by_group(db, "setup", user_id=seeded)}
    assert "Breakout" in setups
    mistakes = {r.group: r for r in pa.compute_performance_by_group(db, "mistake", user_id=seeded)}
    assert "fomo" in mistakes and mistakes["fomo"].trade_count == 1
    db.close()


def test_analytics_date_filter_uses_datetimes(tmp_path):
    # Regression: date bounds must bind as datetimes (Postgres timestamp can't
    # compare to a text param). A 2026 closed position is included by a 2026
    # from_date and excluded by a later one.
    from datetime import datetime, timezone
    from app.database import Base, make_engine
    from sqlalchemy.orm import Session
    from app.core.models import User
    from app.perps.models import ExchangeAccount, Position, Venue, AssetClass, Direction, PositionStatus
    from app.perps.services import analytics

    eng = make_engine(f"sqlite:///{tmp_path/'t.db'}"); Base.metadata.create_all(eng); s = Session(eng)
    u = User(email="a@b.c", password_hash="x"); s.add(u); s.commit()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="x"); s.add(acc); s.commit()
    s.add(Position(user_id=u.id, exchange_account_id=acc.id, symbol="BTCUSDT", asset_class=AssetClass.PERP,
                   direction=Direction.LONG, status=PositionStatus.CLOSED,
                   opened_at=datetime(2026, 3, 18, 13, 0, tzinfo=timezone.utc),
                   closed_at=datetime(2026, 3, 18, 13, 37, tzinfo=timezone.utc),
                   avg_entry=100, avg_exit=110, quantity=1, realized_pnl=10, total_fees=0, total_funding=0))
    s.commit()

    assert analytics.compute_overview(s, {"from_date": "2026-01-01", "to_date": "2026-06-09"}, u.id).total_trades == 1
    assert analytics.compute_overview(s, {"from_date": "2026-04-01"}, u.id).total_trades == 0
    s.close()


def test_time_analytics_exclude_estimated_positions(seeded):
    # One ESTIMATED position opened 14:00 UTC (a fabricated entry time — would
    # be "New York" if trusted): session/heatmap/weekday/hour must skip it.
    from app.perps.models import OpenedAtSource
    db = SessionLocal()
    u = db.query(User).filter(User.email == "p@x.com").one()
    db.add(_pos(u.id, 1, realized_pnl=99, opened_at_source=OpenedAtSource.ESTIMATED,
                opened_at=datetime(2024, 1, 5, 14, tzinfo=timezone.utc),
                closed_at=datetime(2024, 1, 5, 14, tzinfo=timezone.utc),
                duration_seconds=None))
    db.commit()

    sessions = pa.compute_by_session(db, user_id=seeded)
    assert sum(s.trade_count for s in sessions) == 3        # the 3 EXACT seeds only

    cells = pa.compute_heatmap(db, user_id=seeded)
    assert sum(c.trade_count for c in cells) == 3

    weekday = pa.compute_performance_by_group(db, "weekday", user_id=seeded)
    assert sum(r.trade_count for r in weekday) == 3

    # P&L analytics still count ALL positions (money is always trustworthy)
    assert pa.compute_overview(db, user_id=seeded).total_trades == 4
    db.close()


def test_time_analytics_use_opened_at_not_closed_at(seeded):
    # Seeds are opened 09:00 UTC (London) but closed 10:00; entry attribution
    # must follow opened_at. (Before this change session keyed on closed_at.)
    db = SessionLocal()
    sessions = pa.compute_by_session(db, user_id=seeded)
    assert {s.session for s in sessions} == {"London"}
    db.close()


def test_coverage_counts(seeded):
    from app.perps.models import OpenedAtSource
    db = SessionLocal()
    u = db.query(User).filter(User.email == "p@x.com").one()
    db.add(_pos(u.id, 1, opened_at_source=OpenedAtSource.ESTIMATED))
    db.commit()
    cov = pa.compute_coverage(db, user_id=seeded)
    assert cov == {"total": 4, "exact": 3}
    db.close()


def test_by_tag_grouping(seeded):
    from app.perps.models import PerpsTag, perps_position_tags, Position
    db = SessionLocal()
    u = db.query(User).filter(User.email == "p@x.com").one()
    db.execute(perps_position_tags.delete())
    db.query(PerpsTag).delete()
    db.commit()
    p = db.query(Position).filter(Position.user_id == u.id).first()
    p.position_key = "1:BTCUSDT:cpnl:oT"; db.commit()
    t = PerpsTag(user_id=u.id, name="A+ setup"); db.add(t); db.commit(); db.refresh(t)
    db.execute(perps_position_tags.insert().values(
        user_id=u.id, position_key="1:BTCUSDT:cpnl:oT", tag_id=t.id))
    db.commit()
    rows = pa.compute_performance_by_group(db, "tag", user_id=seeded)
    by_name = {r.group: r for r in rows}
    assert by_name["A+ setup"].trade_count == 1
    assert by_name["Untagged"].trade_count == 2
    db.close()


def test_r_distribution_actual_mode_uses_journal_stop(seeded):
    db = SessionLocal()
    u = db.query(User).filter(User.email == "p@x.com").one()
    p = db.query(Position).filter(Position.user_id == u.id,
                                  Position.r_multiple.is_(None)).first()
    p.position_key = "1:BTCUSDT:cpnl:oR"; db.commit()
    # SHORT loser entry 100 exit 110, stop above entry → actual_r = -2.0
    db.add(PerpsJournal(user_id=u.id, position_key="1:BTCUSDT:cpnl:oR", stop_price=105.0))
    db.commit()

    default = pa.compute_r_distribution(db, user_id=seeded)
    actual = pa.compute_r_distribution(db, user_id=seeded, mode="actual")
    assert sum(b["trade_count"] for b in default) == 2          # stored mode unchanged
    assert sum(b["trade_count"] for b in actual) == 3
    bucket = {b["bucket"]: b for b in actual}
    assert bucket["-2..-1R"]["trade_count"] == 1                # the -2.0 trade
    assert bucket["-2..-1R"]["total_pnl"] == pytest.approx(-5)
    db.close()


def test_by_tag_multi_tag_counts_in_each_bucket(seeded):
    from app.perps.models import PerpsTag, perps_position_tags, Position
    db = SessionLocal()
    u = db.query(User).filter(User.email == "p@x.com").one()
    db.execute(perps_position_tags.delete())
    db.query(PerpsTag).delete()
    db.commit()
    p = db.query(Position).filter(Position.user_id == u.id).first()
    p.position_key = "1:BTCUSDT:cpnl:oM"; db.commit()
    t1 = PerpsTag(user_id=u.id, name="TagA"); t2 = PerpsTag(user_id=u.id, name="TagB")
    db.add(t1); db.add(t2); db.commit(); db.refresh(t1); db.refresh(t2)
    for tid in (t1.id, t2.id):
        db.execute(perps_position_tags.insert().values(
            user_id=u.id, position_key="1:BTCUSDT:cpnl:oM", tag_id=tid))
    db.commit()
    rows = pa.compute_performance_by_group(db, "tag", user_id=seeded)
    by_name = {r.group: r for r in rows}
    assert by_name["TagA"].trade_count == 1
    assert by_name["TagB"].trade_count == 1
    assert by_name["Untagged"].trade_count == 2
    db.close()


def test_mistake_max_streak():
    init_db()
    db = SessionLocal()
    db.query(PerpsJournal).delete(); db.query(Position).delete(); db.query(User).delete(); db.commit()
    u = User(email="streak@x.com", password_hash="x"); db.add(u); db.commit(); db.refresh(u)
    # three closed trades on consecutive days, all tagged "Chased"
    for i, day in enumerate((1, 2, 3)):
        p = _pos(u.id, 1, realized_pnl=-5,
                 closed_at=datetime(2024, 1, day, 10, tzinfo=timezone.utc),
                 position_key=f"1:BTCUSDT:cpnl:s{i}")
        db.add(p)
    db.commit()
    for i in range(3):
        db.add(PerpsJournal(user_id=u.id, position_key=f"1:BTCUSDT:cpnl:s{i}",
                            mistake_tags=["Chased"]))
    db.commit(); uid = u.id; db.close()

    db = SessionLocal()
    rows = {r.group: r for r in pa.compute_performance_by_group(db, "mistake", user_id=uid)}
    assert rows["Chased"].trade_count == 3
    assert rows["Chased"].max_streak == 3
    db.close()
