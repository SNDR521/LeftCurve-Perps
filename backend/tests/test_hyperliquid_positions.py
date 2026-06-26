from datetime import datetime
from types import SimpleNamespace
from app.perps.services.hyperliquid_positions import build_closed_positions

ACC = SimpleNamespace(id=7, user_id=3)


def f(time, side, sz, px, start, closed="0", fee="0.1", coin="ETH", h=None):
    return {"coin": coin, "side": side, "sz": str(sz), "px": str(px),
            "time": time, "startPosition": str(start), "closedPnl": str(closed),
            "fee": fee, "hash": h or f"h{time}", "oid": time, "tid": time,
            "dir": ""}


def test_simple_long_round_trip():
    fills = [
        f(1000, "B", 1, 100, start=0),            # open long 1 @100
        f(2000, "A", 1, 110, start=1, closed=10), # close long 1 @110, +10
    ]
    pos = build_closed_positions(ACC, fills)
    assert len(pos) == 1
    p = pos[0]
    assert p["direction"].name == "LONG"
    assert p["quantity"] == 1.0
    assert p["avg_entry"] == 100.0 and p["avg_exit"] == 110.0
    assert p["realized_pnl"] == 10.0
    assert p["total_fees"] == 0.2
    assert p["status"].name == "CLOSED"
    assert p["opened_at_source"].name == "EXACT"
    assert p["position_key"] == "7:ETH:hl:h1000"
    # opened_at/closed_at must be datetimes (Position columns are DateTime), not raw ms.
    assert isinstance(p["opened_at"], datetime) and isinstance(p["closed_at"], datetime)
    assert p["duration_seconds"] == 1  # 2000ms - 1000ms = 1s


def test_pyramid_then_partial_closes():
    fills = [
        f(1000, "B", 1, 100, start=0),
        f(1500, "B", 1, 102, start=1),             # add -> size 2, avg entry 101
        f(2000, "A", 1, 110, start=2, closed=9),
        f(2500, "A", 1, 112, start=1, closed=10),  # fully closed
    ]
    pos = build_closed_positions(ACC, fills)
    assert len(pos) == 1
    p = pos[0]
    assert p["quantity"] == 2.0
    assert p["avg_entry"] == 101.0
    assert p["avg_exit"] == 111.0
    assert p["realized_pnl"] == 19.0


def test_flip_long_to_short_splits_into_two_positions():
    fills = [
        f(1000, "B", 1, 100, start=0),               # open long 1
        f(2000, "A", 2, 110, start=1, closed=10),    # sell 2: closes long 1 (+10), opens short 1
        f(3000, "B", 1, 105, start=-1, closed=5),    # buy 1: closes short 1 (+5)
    ]
    pos = build_closed_positions(ACC, fills)
    assert len(pos) == 2
    longp = next(p for p in pos if p["direction"].name == "LONG")
    shortp = next(p for p in pos if p["direction"].name == "SHORT")
    assert longp["realized_pnl"] == 10.0 and longp["quantity"] == 1.0
    assert shortp["realized_pnl"] == 5.0 and shortp["quantity"] == 1.0
    assert shortp["avg_entry"] == 110.0 and shortp["avg_exit"] == 105.0


def test_still_open_position_is_not_emitted():
    fills = [f(1000, "B", 2, 100, start=0), f(1500, "A", 1, 110, start=2, closed=10)]
    pos = build_closed_positions(ACC, fills)  # net 1 still open
    assert pos == []


def test_emits_contributing_fill_ids():
    fills = [f(1000, "B", 1, 100, start=0, h="hopen"),
             f(2000, "A", 1, 110, start=1, closed=10, h="hclose")]
    pos = build_closed_positions(ACC, fills)
    # both legs recorded → the sync links them so the chart shows entry+exit markers
    assert pos[0]["fill_external_ids"] == ["hopen", "hclose"]


def test_flip_fill_id_recorded_in_both_positions():
    fills = [
        f(1000, "B", 1, 100, start=0, h="hopen"),
        f(2000, "A", 2, 110, start=1, closed=10, h="hflip"),    # closes long, opens short
        f(3000, "B", 1, 105, start=-1, closed=5, h="hcloseshort"),
    ]
    pos = build_closed_positions(ACC, fills)
    longp = next(p for p in pos if p["direction"].name == "LONG")
    shortp = next(p for p in pos if p["direction"].name == "SHORT")
    assert longp["fill_external_ids"] == ["hopen", "hflip"]
    assert shortp["fill_external_ids"] == ["hflip", "hcloseshort"]


def test_unsorted_input_is_handled():
    fills = [
        f(2000, "A", 1, 110, start=1, closed=10),
        f(1000, "B", 1, 100, start=0),
    ]
    pos = build_closed_positions(ACC, fills)
    assert len(pos) == 1 and pos[0]["realized_pnl"] == 10.0
