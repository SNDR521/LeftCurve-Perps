import math
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.perps.models import Position, PositionStatus, PerpsJournal, OpenedAtSource
from app.perps.services.risk import compute_risk
from app.core.schemas import OverviewMetrics, DailyPnl


def _as_dt(value, end_of_day=False):
    """Coerce a 'YYYY-MM-DD' bound (or datetime) into a naive datetime.

    closed_at is a Postgres `timestamp`; comparing it to a bare string makes
    psycopg3 send the bound as `text`, and Postgres has no `timestamp >= text`
    operator, so the date-filtered query errors (worked on dev SQLite, which is
    loose about types). Binding a real datetime avoids that.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    d = datetime.fromisoformat(str(value)[:10])
    return d.replace(hour=23, minute=59, second=59, microsecond=999999) if end_of_day else d


def _closed_positions(db: Session, user_id: int, filters: dict | None, exact_only: bool = False):
    q = db.query(Position).filter(Position.status == PositionStatus.CLOSED)
    if exact_only:
        q = q.filter(Position.opened_at_source == OpenedAtSource.EXACT)
    if user_id is not None:
        q = q.filter(Position.user_id == user_id)
    if filters:
        if filters.get("symbol"):
            q = q.filter(Position.symbol == filters["symbol"])
        if filters.get("account_id"):
            q = q.filter(Position.exchange_account_id == int(filters["account_id"]))
        if filters.get("from_date"):
            q = q.filter(Position.closed_at >= _as_dt(filters["from_date"]))
        if filters.get("to_date"):
            q = q.filter(Position.closed_at <= _as_dt(filters["to_date"], end_of_day=True))
    return q.order_by(Position.closed_at.asc(), Position.id.asc()).all()


def _day(p: Position) -> str:
    dt = p.closed_at or p.opened_at
    return dt.strftime("%Y-%m-%d")


def compute_overview(db: Session, filters: dict = None, user_id: int = None) -> OverviewMetrics:
    positions = _closed_positions(db, user_id, filters)
    if not positions:
        return OverviewMetrics()

    pnls = [p.realized_pnl or 0 for p in positions]
    winners = [p for p in positions if (p.realized_pnl or 0) > 0]
    losers = [p for p in positions if (p.realized_pnl or 0) < 0]
    total_wins = sum(p.realized_pnl for p in winners)
    total_losses = abs(sum(p.realized_pnl for p in losers))

    cumulative = peak = max_dd = 0.0
    for p in positions:
        cumulative += p.realized_pnl or 0
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)

    max_w = max_l = curr_w = curr_l = 0
    for p in positions:
        v = p.realized_pnl or 0
        if v > 0: curr_w += 1; curr_l = 0
        elif v < 0: curr_l += 1; curr_w = 0
        else: curr_w = curr_l = 0
        max_w = max(max_w, curr_w); max_l = max(max_l, curr_l)

    r_vals = [p.r_multiple for p in positions if p.r_multiple is not None]
    avg_r = sum(r_vals) / len(r_vals) if r_vals else None
    durations = [p.duration_seconds for p in positions if p.duration_seconds]
    avg_dur = sum(durations) / len(durations) if durations else None

    daily = defaultdict(float)
    for p in positions:
        daily[_day(p)] += p.realized_pnl or 0
    series = list(daily.values())
    sharpe = sortino = None
    if len(series) >= 2:
        mean_d = sum(series) / len(series)
        variance = sum((x - mean_d) ** 2 for x in series) / (len(series) - 1)
        std_d = math.sqrt(variance) if variance > 0 else 0
        if std_d > 0:
            sharpe = round(mean_d / std_d * math.sqrt(252), 2)
        downside = [x for x in series if x < 0]
        if downside:
            down_std = math.sqrt(sum(x ** 2 for x in downside) / len(downside))
            if down_std > 0:
                sortino = round(mean_d / down_std * math.sqrt(252), 2)

    return OverviewMetrics(
        total_trades=len(positions),
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate=len(winners) / len(positions) * 100,
        total_pnl=sum(pnls),
        avg_win=total_wins / len(winners) if winners else 0,
        avg_loss=-total_losses / len(losers) if losers else 0,
        profit_factor=round(total_wins / total_losses, 2) if total_losses > 0 else 0.0,
        expectancy=sum(pnls) / len(positions),
        avg_r_multiple=avg_r,
        avg_risk_amount=None,
        max_drawdown=max_dd,
        max_consecutive_wins=max_w,
        max_consecutive_losses=max_l,
        best_trade=max(pnls),
        worst_trade=min(pnls),
        avg_duration_seconds=avg_dur,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
    )


def compute_daily_pnl(db: Session, filters: dict = None, user_id: int = None) -> list[DailyPnl]:
    positions = _closed_positions(db, user_id, filters)
    by_day = defaultdict(lambda: {"pnl": 0.0, "n": 0, "w": 0, "l": 0})
    for p in positions:
        d = by_day[_day(p)]
        v = p.realized_pnl or 0
        d["pnl"] += v; d["n"] += 1
        if v > 0: d["w"] += 1
        elif v < 0: d["l"] += 1
    out, cum = [], 0.0
    for day in sorted(by_day):
        d = by_day[day]; cum += d["pnl"]
        out.append(DailyPnl(date=day, pnl=d["pnl"], trade_count=d["n"], wins=d["w"], losses=d["l"], cumulative_pnl=cum))
    return out


from app.core.schemas import PerformanceByGroup, SessionMetrics, HoldtimeBucket, HeatmapCell

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _group_metrics(group: str, items: list[Position], max_streak=None) -> PerformanceByGroup:
    pnls = [p.realized_pnl or 0 for p in items]
    winners = [v for v in pnls if v > 0]
    gross_w = sum(v for v in pnls if v > 0)
    gross_l = abs(sum(v for v in pnls if v < 0))
    return PerformanceByGroup(
        group=group, trade_count=len(items),
        win_rate=len(winners) / len(items) * 100 if items else 0,
        total_pnl=sum(pnls), avg_pnl=sum(pnls) / len(items) if items else 0,
        profit_factor=round(gross_w / gross_l, 2) if gross_l > 0 else None,
        max_streak=max_streak,
    )


def _group_key(p: Position, group_by: str):
    if group_by == "symbol": return p.symbol
    if group_by == "direction": return p.direction.value
    if group_by == "weekday": return _WEEKDAYS[p.opened_at.weekday()]
    if group_by == "hour": return f"{p.opened_at.hour:02d}:00"
    return "—"


def _journal_map(db, user_id, position_keys):
    if not position_keys:
        return {}
    rows = db.query(PerpsJournal).filter(
        PerpsJournal.user_id == user_id, PerpsJournal.position_key.in_(position_keys)).all()
    return {j.position_key: j for j in rows}


def compute_performance_by_group(db, group_by, filters=None, user_id=None) -> list[PerformanceByGroup]:
    positions = _closed_positions(db, user_id, filters, exact_only=(group_by in ("weekday", "hour")))
    buckets = defaultdict(list)
    if group_by in ("setup", "grade", "mistake"):
        jmap = _journal_map(db, user_id, [p.position_key for p in positions if p.position_key])
        for p in positions:
            j = jmap.get(p.position_key)
            if group_by == "setup":
                buckets[(j.setup_name if j and j.setup_name else "Unspecified")].append(p)
            elif group_by == "grade":
                buckets[(j.grade if j and j.grade else "Ungraded")].append(p)
            else:  # mistake
                tags = (j.mistake_tags if j and j.mistake_tags else []) or []
                if not tags:
                    buckets["None"].append(p)
                else:
                    for t in tags:
                        buckets[t].append(p)
        if group_by == "mistake":
            from app.core.streaks import max_streaks
            ordered = sorted(positions, key=lambda p: p.closed_at or p.opened_at)
            streaks = max_streaks([
                ((jmap.get(p.position_key).mistake_tags
                  if jmap.get(p.position_key) and jmap.get(p.position_key).mistake_tags else []) or [])
                for p in ordered])
            rows = [_group_metrics(k, v, max_streak=streaks.get(k, 0)) for k, v in buckets.items()]
        else:
            rows = [_group_metrics(k, v) for k, v in buckets.items()]
        return sorted(rows, key=lambda r: r.total_pnl, reverse=True)
    if group_by == "tag":
        from app.perps.models import PerpsTag, perps_position_tags
        if user_id is None:
            # user_id == None would compile to `user_id IS NULL` and silently
            # match nothing — every position would come back "Untagged".
            raise ValueError("by-tag grouping requires a user_id")
        tag_rows = db.execute(
            perps_position_tags.select().where(perps_position_tags.c.user_id == user_id)
        ).all()
        names = {t.id: t.name for t in db.query(PerpsTag).filter(PerpsTag.user_id == user_id)}
        keys_to_tags = {}
        for r in tag_rows:
            keys_to_tags.setdefault(r.position_key, []).append(names.get(r.tag_id, "?"))
        for p in positions:
            tags = keys_to_tags.get(p.position_key, [])
            if not tags:
                buckets["Untagged"].append(p)
            else:
                for name in tags:
                    buckets[name].append(p)
        rows = [_group_metrics(k, v) for k, v in buckets.items()]
        return sorted(rows, key=lambda r: r.total_pnl, reverse=True)
    for p in positions:
        buckets[_group_key(p, group_by)].append(p)
    rows = [_group_metrics(k, v) for k, v in buckets.items()]
    if group_by == "weekday":
        rows.sort(key=lambda r: _WEEKDAYS.index(r.group) if r.group in _WEEKDAYS else 99)
    elif group_by == "hour":
        rows.sort(key=lambda r: r.group)
    else:
        rows.sort(key=lambda r: r.total_pnl, reverse=True)
    return rows


def _session_for(hour: int) -> tuple[str, str]:
    if 0 <= hour < 8: return "Tokyo", "00:00–08:00 UTC"
    if 8 <= hour < 13: return "London", "08:00–13:00 UTC"
    if 13 <= hour < 22: return "New York", "13:00–22:00 UTC"
    return "Off-hours", "22:00–00:00 UTC"


def compute_by_session(db, filters=None, user_id=None) -> list[SessionMetrics]:
    positions = _closed_positions(db, user_id, filters, exact_only=True)
    buckets = defaultdict(list)
    labels = {}
    for p in positions:
        dt = p.opened_at
        name, lbl = _session_for(dt.hour)
        buckets[name].append(p); labels[name] = lbl
    out = []
    for name, items in buckets.items():
        pnls = [p.realized_pnl or 0 for p in items]
        winners = [v for v in pnls if v > 0]
        gw = sum(v for v in pnls if v > 0); gl = abs(sum(v for v in pnls if v < 0))
        out.append(SessionMetrics(
            session=name, utc_hours=labels[name], trade_count=len(items),
            win_rate=len(winners) / len(items) * 100, total_pnl=sum(pnls),
            avg_pnl=sum(pnls) / len(items),
            profit_factor=round(gw / gl, 2) if gl > 0 else None,
            best_trade=max(pnls), worst_trade=min(pnls),
        ))
    return sorted(out, key=lambda s: s.total_pnl, reverse=True)


_HT_BUCKETS = [("<5m", 0, 300), ("5–30m", 300, 1800), ("30m–2h", 1800, 7200),
               ("2–8h", 7200, 28800), (">8h", 28800, 10**12)]


def compute_by_holdtime(db, filters=None, user_id=None) -> list[HoldtimeBucket]:
    positions = [p for p in _closed_positions(db, user_id, filters) if p.duration_seconds is not None]
    out = []
    for label, lo, hi in _HT_BUCKETS:
        items = [p for p in positions if lo <= p.duration_seconds < hi]
        pnls = [p.realized_pnl or 0 for p in items]
        winners = [v for v in pnls if v > 0]
        gw = sum(v for v in pnls if v > 0); gl = abs(sum(v for v in pnls if v < 0))
        out.append(HoldtimeBucket(
            bucket=label, min_seconds=lo, max_seconds=(hi if hi < 10**12 else -1),
            trade_count=len(items), win_rate=(len(winners) / len(items) * 100) if items else 0,
            total_pnl=sum(pnls), avg_pnl=(sum(pnls) / len(items)) if items else 0,
            profit_factor=round(gw / gl, 2) if gl > 0 else None,
        ))
    return out


def compute_heatmap(db, filters=None, user_id=None) -> list[HeatmapCell]:
    positions = _closed_positions(db, user_id, filters, exact_only=True)
    cells = defaultdict(lambda: {"n": 0, "pnl": 0.0, "w": 0})
    for p in positions:
        dt = p.opened_at
        c = cells[(dt.weekday(), dt.hour)]
        c["n"] += 1; c["pnl"] += p.realized_pnl or 0
        if (p.realized_pnl or 0) > 0: c["w"] += 1
    return [HeatmapCell(weekday=wd, hour=hr, trade_count=c["n"], total_pnl=c["pnl"],
                        win_rate=c["w"] / c["n"] * 100 if c["n"] else 0)
            for (wd, hr), c in cells.items()]


_R_BUCKETS = [("<-2R", -10**9, -2), ("-2..-1R", -2, -1), ("-1..0R", -1, 0),
              ("0..1R", 0, 1), ("1..2R", 1, 2), ("2..3R", 2, 3), (">3R", 3, 10**9)]


def compute_r_distribution(db, filters=None, user_id=None, mode: str = "stored") -> list[dict]:
    positions = _closed_positions(db, user_id, filters)
    if mode == "actual":
        jmap = _journal_map(db, user_id, [p.position_key for p in positions if p.position_key])
        pairs = []
        for p in positions:
            r = p.r_multiple
            if r is None:
                r = compute_risk(p, jmap.get(p.position_key))["actual_r"]
            if r is not None:
                pairs.append((p, r))
    else:
        pairs = [(p, p.r_multiple) for p in positions if p.r_multiple is not None]
    out = []
    for label, lo, hi in _R_BUCKETS:
        items = [(p, r) for p, r in pairs if lo <= r < hi]
        out.append({"bucket": label, "trade_count": len(items),
                    "total_pnl": sum(p.realized_pnl or 0 for p, _ in items)})
    return out


def compute_coverage(db: Session, filters: dict = None, user_id: int = None) -> dict:
    """How many closed positions have verified entry times — shown next to
    time-based analytics so partial coverage is never silent."""
    allp = _closed_positions(db, user_id, filters)
    exact = [p for p in allp if p.opened_at_source == OpenedAtSource.EXACT]
    return {"total": len(allp), "exact": len(exact)}
