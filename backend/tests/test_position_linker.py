from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.perps.models import (
    ExchangeAccount, Fill, Position, PositionFill, Venue, AssetClass, Side,
    Direction, PositionStatus, OpenedAtSource,
)

T0 = datetime(2026, 1, 1, 10, 0, 0)  # naive UTC, like DB storage


@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("x"))
    s.add(u); s.commit()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="Bybit")
    s.add(acc); s.commit()
    yield s, u, acc
    s.close()


def test_schema_has_linkage_and_mfe_columns(db):
    s, u, acc = db
    p = Position(
        user_id=u.id, exchange_account_id=acc.id, symbol="BTCUSDT",
        asset_class=AssetClass.PERP, direction=Direction.LONG,
        status=PositionStatus.CLOSED, opened_at=T0, closed_at=T0 + timedelta(hours=2),
        avg_entry=100.0, avg_exit=110.0, quantity=1.0, realized_pnl=10.0,
        total_fees=0.2, total_funding=0.0, position_key="1:BTCUSDT:cpnl:o1",
    )
    s.add(p); s.commit()
    assert p.opened_at_source == OpenedAtSource.ESTIMATED  # server default
    assert p.mfe_price is None and p.mae_price is None
    assert p.mfe_usd is None and p.mae_usd is None

    f = Fill(user_id=u.id, exchange_account_id=acc.id, venue=Venue.BYBIT,
             symbol="BTCUSDT", asset_class=AssetClass.PERP, side=Side.BUY,
             price=100.0, quantity=1.0, executed_at=T0)
    s.add(f); s.commit()
    link = PositionFill(position_id=p.id, fill_id=f.id)
    s.add(link); s.commit()
    assert s.query(PositionFill).count() == 1


from app.perps.services.position_linker import build_chains


class _F:  # minimal fill stand-in for the pure chain builder
    _next_id = 1
    def __init__(self, side, price, qty, t, order_id="o"):
        self.id = _F._next_id; _F._next_id += 1
        self.side = side; self.price = price; self.quantity = qty
        self.executed_at = t; self.order_id = order_id


def test_build_chains_simple_long(db):
    fills = [_F("BUY", 100, 1.0, T0, "o1"), _F("SELL", 110, 1.0, T0 + timedelta(hours=2), "o2")]
    chains = build_chains(fills)
    assert len(chains) == 1
    c = chains[0]
    assert c.direction == "LONG"
    assert c.opened_at == T0
    assert c.closed_at == T0 + timedelta(hours=2)
    assert c.fill_ids == [fills[0].id, fills[1].id]
    assert len(c.closes) == 1
    assert c.closes[0].order_id == "o2"
    assert c.closes[0].avg_entry == pytest.approx(100.0)


def test_build_chains_partial_closes_and_add(db):
    # open 2 @100, close 1 @110, add 1 @105, close 2 @120
    fills = [
        _F("BUY", 100, 2.0, T0, "o1"),
        _F("SELL", 110, 1.0, T0 + timedelta(hours=1), "o2"),
        _F("BUY", 105, 1.0, T0 + timedelta(hours=2), "o3"),
        _F("SELL", 120, 2.0, T0 + timedelta(hours=3), "o4"),
    ]
    chains = build_chains(fills)
    assert len(chains) == 1
    c = chains[0]
    assert c.closed_at == T0 + timedelta(hours=3)
    assert [cl.order_id for cl in c.closes] == ["o2", "o4"]
    # avg entry at first close: only the 2@100 batch -> 100
    assert c.closes[0].avg_entry == pytest.approx(100.0)
    # avg entry at second close: (2*100 + 1*105) / 3
    assert c.closes[1].avg_entry == pytest.approx(305 / 3)


def test_build_chains_flip_splits_into_two(db):
    # long 1 @100, then SELL 2 @110 → closes the long AND opens a short
    fills = [_F("BUY", 100, 1.0, T0, "o1"), _F("SELL", 110, 2.0, T0 + timedelta(hours=1), "o2"),
             _F("BUY", 105, 1.0, T0 + timedelta(hours=2), "o3")]
    chains = build_chains(fills)
    assert len(chains) == 2
    assert chains[0].direction == "LONG" and chains[0].closed_at == T0 + timedelta(hours=1)
    assert chains[1].direction == "SHORT" and chains[1].opened_at == T0 + timedelta(hours=1)
    # the flip fill belongs to both chains
    assert fills[1].id in chains[0].fill_ids and fills[1].id in chains[1].fill_ids


def test_build_chains_open_tail(db):
    chains = build_chains([_F("BUY", 100, 1.0, T0, "o1")])
    assert len(chains) == 1
    assert chains[0].closed_at is None and chains[0].closes == []


def test_build_chains_simple_short(db):
    fills = [_F("SELL", 100, 1.0, T0, "o1"), _F("BUY", 90, 1.0, T0 + timedelta(hours=1), "o2")]
    chains = build_chains(fills)
    assert len(chains) == 1
    assert chains[0].direction == "SHORT"
    assert chains[0].closes[0].avg_entry == pytest.approx(100.0)


def test_build_chains_multi_fill_closing_order(db):
    # one closing order executed as two partial fills (same order_id) — both
    # ChainClose entries must carry that order_id and the chain closes on the last
    fills = [
        _F("BUY", 100, 2.0, T0, "o1"),
        _F("SELL", 110, 1.0, T0 + timedelta(hours=1), "oclose"),
        _F("SELL", 111, 1.0, T0 + timedelta(hours=1, minutes=1), "oclose"),
    ]
    chains = build_chains(fills)
    assert len(chains) == 1
    assert [cl.order_id for cl in chains[0].closes] == ["oclose", "oclose"]
    assert chains[0].closed_at == T0 + timedelta(hours=1, minutes=1)


from app.perps.services.position_linker import link_account


def _fill(s, u, acc, side, price, qty, t, order_id, funding=None, eid=None):
    f = Fill(user_id=u.id, exchange_account_id=acc.id, venue=Venue.BYBIT,
             symbol="BTCUSDT", asset_class=AssetClass.PERP, side=side,
             price=price, quantity=qty, executed_at=t, order_id=order_id,
             funding_amount=funding,
             external_fill_id=eid or f"e{t.timestamp()}{side}{price}")
    s.add(f); s.commit()
    return f


def _cpnl_pos(s, u, acc, order_id, direction, closed_at, avg_entry, qty=1.0):
    p = Position(user_id=u.id, exchange_account_id=acc.id, symbol="BTCUSDT",
                 asset_class=AssetClass.PERP, direction=direction,
                 status=PositionStatus.CLOSED, opened_at=closed_at, closed_at=closed_at,
                 avg_entry=avg_entry, avg_exit=0.0, quantity=qty, realized_pnl=0.0,
                 total_fees=0.0, total_funding=0.0,
                 position_key=f"{acc.id}:BTCUSDT:cpnl:{order_id}")
    s.add(p); s.commit()
    return p


def test_link_account_exact_match(db):
    s, u, acc = db
    f1 = _fill(s, u, acc, Side.BUY, 100.0, 1.0, T0, "o1")
    f2 = _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0 + timedelta(hours=2), "o2")
    fund = _fill(s, u, acc, Side.BUY, 0.0, 0.0, T0 + timedelta(hours=1), None,
                 funding=-0.5, eid="funding:1")
    p = _cpnl_pos(s, u, acc, "o2", Direction.LONG, T0 + timedelta(hours=2), 100.0)

    link_account(s, acc)
    s.refresh(p)
    assert p.opened_at_source == OpenedAtSource.EXACT
    assert p.opened_at == T0
    assert p.duration_seconds == 2 * 3600
    assert p.total_funding == pytest.approx(-0.5)
    linked = {pf.fill_id for pf in s.query(PositionFill).filter_by(position_id=p.id)}
    assert linked == {f1.id, f2.id, fund.id}


def test_link_account_truncated_history_is_estimated(db):
    # Only the closing SELL exists (entry lost behind the 2y wall): the replay
    # opens a phantom SHORT chain — direction mismatch → ESTIMATED, untouched.
    s, u, acc = db
    _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0, "o2")
    p = _cpnl_pos(s, u, acc, "o2", Direction.LONG, T0, 100.0)
    before_opened = p.opened_at

    link_account(s, acc)
    s.refresh(p)
    assert p.opened_at_source == OpenedAtSource.ESTIMATED
    assert p.opened_at == before_opened
    assert p.duration_seconds is None
    assert s.query(PositionFill).count() == 0


def test_link_account_avg_entry_mismatch_is_estimated(db):
    # Chain exists but replayed avg entry differs >0.5% from Bybit's avgEntryPrice
    # (e.g. partially truncated adds) → ESTIMATED.
    s, u, acc = db
    _fill(s, u, acc, Side.BUY, 100.0, 1.0, T0, "o1")
    _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0 + timedelta(hours=2), "o2")
    p = _cpnl_pos(s, u, acc, "o2", Direction.LONG, T0 + timedelta(hours=2), avg_entry=90.0)

    link_account(s, acc)
    s.refresh(p)
    assert p.opened_at_source == OpenedAtSource.ESTIMATED


def test_link_account_partial_closes_share_entries_split_funding(db):
    # open 2 @100; funding A; close 1 @110 (o2); funding B; close 1 @120 (o3)
    s, u, acc = db
    f1 = _fill(s, u, acc, Side.BUY, 100.0, 2.0, T0, "o1")
    fa = _fill(s, u, acc, Side.BUY, 0.0, 0.0, T0 + timedelta(minutes=30), None,
               funding=-0.1, eid="funding:a")
    f2 = _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0 + timedelta(hours=1), "o2")
    fb = _fill(s, u, acc, Side.BUY, 0.0, 0.0, T0 + timedelta(hours=1, minutes=30), None,
               funding=-0.2, eid="funding:b")
    f3 = _fill(s, u, acc, Side.SELL, 120.0, 1.0, T0 + timedelta(hours=2), "o3")
    p1 = _cpnl_pos(s, u, acc, "o2", Direction.LONG, T0 + timedelta(hours=1), 100.0)
    p2 = _cpnl_pos(s, u, acc, "o3", Direction.LONG, T0 + timedelta(hours=2), 100.0)

    link_account(s, acc)
    s.refresh(p1); s.refresh(p2)
    # both partial closes inherit the chain's true open
    assert p1.opened_at == T0 and p2.opened_at == T0
    assert p1.opened_at_source == OpenedAtSource.EXACT
    assert p2.opened_at_source == OpenedAtSource.EXACT
    # funding split by close windows: A → p1, B → p2
    assert p1.total_funding == pytest.approx(-0.1)
    assert p2.total_funding == pytest.approx(-0.2)
    l1 = {pf.fill_id for pf in s.query(PositionFill).filter_by(position_id=p1.id)}
    l2 = {pf.fill_id for pf in s.query(PositionFill).filter_by(position_id=p2.id)}
    assert l1 == {f1.id, fa.id, f2.id}          # entry + own funding + own close
    assert l2 == {f1.id, fb.id, f3.id}          # shared entry + own funding + own close


def test_link_account_is_idempotent(db):
    s, u, acc = db
    _fill(s, u, acc, Side.BUY, 100.0, 1.0, T0, "o1")
    _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0 + timedelta(hours=2), "o2")
    p = _cpnl_pos(s, u, acc, "o2", Direction.LONG, T0 + timedelta(hours=2), 100.0)
    link_account(s, acc)
    n1 = s.query(PositionFill).count()
    link_account(s, acc)
    assert s.query(PositionFill).count() == n1


def test_link_account_exact_to_estimated_flip_resets_fields(db):
    # A position that matched EXACT on one run must not keep stale opened_at/
    # duration/funding if a later run can no longer verify the chain.
    s, u, acc = db
    _fill(s, u, acc, Side.BUY, 100.0, 1.0, T0, "o1")
    _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0 + timedelta(hours=2), "o2")
    _fill(s, u, acc, Side.BUY, 0.0, 0.0, T0 + timedelta(hours=1), None,
          funding=-0.5, eid="funding:1")
    p = _cpnl_pos(s, u, acc, "o2", Direction.LONG, T0 + timedelta(hours=2), 100.0)

    link_account(s, acc)
    s.refresh(p)
    assert p.opened_at_source == OpenedAtSource.EXACT
    assert p.total_funding == pytest.approx(-0.5)

    # Simulate divergence: Bybit avg entry no longer within tolerance
    p.avg_entry = 90.0
    s.commit()
    link_account(s, acc)
    s.refresh(p)
    assert p.opened_at_source == OpenedAtSource.ESTIMATED
    assert p.opened_at == p.closed_at
    assert p.duration_seconds is None
    assert p.total_funding == 0.0
    assert s.query(PositionFill).filter_by(position_id=p.id).count() == 0


def test_link_account_truncated_head_recovers_later_chains(db):
    # Symbol history truncated at the retention wall: the first retained fill
    # is a SELL closing an unrecorded long. Without head-offset seeding, the
    # replay net never returns to true zero and every later chain on the
    # symbol fails the match. With seeding, the truncated close stays
    # ESTIMATED but subsequent clean round-trips become EXACT.
    s, u, acc = db
    _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0, "o1")                         # truncated close
    f2 = _fill(s, u, acc, Side.BUY, 100.0, 1.0, T0 + timedelta(hours=1), "o2")
    f3 = _fill(s, u, acc, Side.SELL, 120.0, 1.0, T0 + timedelta(hours=3), "o3")
    p1 = _cpnl_pos(s, u, acc, "o1", Direction.LONG, T0, 90.0)                  # entry unknown
    p2 = _cpnl_pos(s, u, acc, "o3", Direction.LONG, T0 + timedelta(hours=3), 100.0)

    link_account(s, acc)
    s.refresh(p1); s.refresh(p2)
    assert p1.opened_at_source == OpenedAtSource.ESTIMATED
    assert p2.opened_at_source == OpenedAtSource.EXACT
    assert p2.opened_at == T0 + timedelta(hours=1)
    assert p2.duration_seconds == 2 * 3600
    linked = {pf.fill_id for pf in s.query(PositionFill).filter_by(position_id=p2.id)}
    assert linked == {f2.id, f3.id}


def test_link_account_truncated_head_with_open_position(db):
    # Same wall scenario but the account currently HOLDS 2 LONG (open snapshot
    # row): actual net = +2, replay net from fills = +2 - 3 = ... the offset
    # math must use the live open position as truth.
    s, u, acc = db
    # truncated history: SELL 3 closing an unrecorded long of 3
    _fill(s, u, acc, Side.SELL, 110.0, 3.0, T0, "o1")
    # then a clean round trip
    f2 = _fill(s, u, acc, Side.BUY, 100.0, 1.0, T0 + timedelta(hours=1), "o2")
    f3 = _fill(s, u, acc, Side.SELL, 120.0, 1.0, T0 + timedelta(hours=2), "o3")
    # and a still-open long of 2
    _fill(s, u, acc, Side.BUY, 105.0, 2.0, T0 + timedelta(hours=4), "o4")
    open_pos = Position(user_id=u.id, exchange_account_id=acc.id, symbol="BTCUSDT",
                        asset_class=AssetClass.PERP, direction=Direction.LONG,
                        status=PositionStatus.OPEN, opened_at=T0 + timedelta(hours=4),
                        avg_entry=105.0, quantity=2.0, realized_pnl=0.0,
                        total_fees=0.0, total_funding=0.0,
                        position_key=f"{acc.id}:BTCUSDT:open")
    s.add(open_pos); s.commit()
    p2 = _cpnl_pos(s, u, acc, "o3", Direction.LONG, T0 + timedelta(hours=2), 100.0)

    link_account(s, acc)
    s.refresh(p2)
    assert p2.opened_at_source == OpenedAtSource.EXACT
    assert p2.opened_at == T0 + timedelta(hours=1)
    linked = {pf.fill_id for pf in s.query(PositionFill).filter_by(position_id=p2.id)}
    assert linked == {f2.id, f3.id}


def test_link_account_resets_mfe_when_opened_at_moves(db):
    # If re-linking corrects opened_at (e.g. after head seeding improved the
    # chains), an MFE computed on the old window is stale and must clear.
    s, u, acc = db
    _fill(s, u, acc, Side.BUY, 100.0, 1.0, T0, "o1")
    _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0 + timedelta(hours=2), "o2")
    p = _cpnl_pos(s, u, acc, "o2", Direction.LONG, T0 + timedelta(hours=2), 100.0)
    p.mfe_usd = 42.0; p.mae_usd = 7.0; p.mfe_price = 4.2; p.mae_price = 0.7
    s.commit()

    link_account(s, acc)   # opened_at moves from closed_at to T0
    s.refresh(p)
    assert p.opened_at == T0
    assert p.mfe_usd is None and p.mae_usd is None
    assert p.mfe_price is None and p.mae_price is None


def test_link_account_mid_history_gap_keeps_unseeded_when_better(db):
    # A clean round trip FIRST, then a mid-history hole (a close with no
    # recorded entry). Head seeding would poison the early clean chain while
    # fixing nothing after the hole — the linker must keep the unseeded
    # variant and preserve the early EXACT match.
    s, u, acc = db
    f1 = _fill(s, u, acc, Side.BUY, 100.0, 1.0, T0, "o1")
    f2 = _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0 + timedelta(hours=1), "o2")
    _fill(s, u, acc, Side.SELL, 120.0, 2.0, T0 + timedelta(hours=5), "o3")  # hole: entry missing
    p1 = _cpnl_pos(s, u, acc, "o2", Direction.LONG, T0 + timedelta(hours=1), 100.0)
    p2 = _cpnl_pos(s, u, acc, "o3", Direction.LONG, T0 + timedelta(hours=5), 95.0)

    link_account(s, acc)
    s.refresh(p1); s.refresh(p2)
    assert p1.opened_at_source == OpenedAtSource.EXACT
    assert p1.opened_at == T0
    assert p2.opened_at_source == OpenedAtSource.ESTIMATED
    linked = {pf.fill_id for pf in s.query(PositionFill).filter_by(position_id=p1.id)}
    assert linked == {f1.id, f2.id}


def test_link_account_union_rescues_trades_after_mid_history_hole(db):
    # Early clean round trip, then a HOLE (close with no recorded entry),
    # then another clean round trip. The unseeded replay matches the early
    # trade; only the head-seeded replay aligns the late one. Per-position
    # union must verify BOTH (the old per-symbol winner-takes-all sacrificed
    # whichever side had fewer matches).
    s, u, acc = db
    f1 = _fill(s, u, acc, Side.BUY, 100.0, 1.0, T0, "o1")
    f2 = _fill(s, u, acc, Side.SELL, 110.0, 1.0, T0 + timedelta(hours=1), "o2")
    _fill(s, u, acc, Side.SELL, 120.0, 2.0, T0 + timedelta(hours=5), "oHole")  # entry missing
    f4 = _fill(s, u, acc, Side.BUY, 200.0, 1.0, T0 + timedelta(hours=10), "o4")
    f5 = _fill(s, u, acc, Side.SELL, 220.0, 1.0, T0 + timedelta(hours=12), "o5")
    p_early = _cpnl_pos(s, u, acc, "o2", Direction.LONG, T0 + timedelta(hours=1), 100.0)
    p_late = _cpnl_pos(s, u, acc, "o5", Direction.LONG, T0 + timedelta(hours=12), 200.0)

    link_account(s, acc)
    s.refresh(p_early); s.refresh(p_late)
    assert p_early.opened_at_source == OpenedAtSource.EXACT
    assert p_early.opened_at == T0
    assert p_late.opened_at_source == OpenedAtSource.EXACT
    assert p_late.opened_at == T0 + timedelta(hours=10)
    late_links = {pf.fill_id for pf in s.query(PositionFill).filter_by(position_id=p_late.id)}
    assert late_links == {f4.id, f5.id}
