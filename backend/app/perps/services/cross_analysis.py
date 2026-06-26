"""Cross-analysis engine for perps deep-dive reports.

Computes cross-tab analytics over closed perps Positions, PerpsJournal, and
perps tags across a rich dimension set (symbol, direction, setup, grade,
session, weekday, leverage, emotions, etc.). Metric formulas are pinned by
tests.
"""
from collections import defaultdict

from sqlalchemy.orm import Session

from app.perps.models import PerpsJournal
from app.perps.services.analytics import _closed_positions, _session_for, _WEEKDAYS


# Perps dimension superset (key -> label)
DIMENSIONS = {
    "symbol": "Symbol",
    "direction": "Direction",
    "setup": "Setup",
    "grade": "Grade",
    "mistake": "Mistake",
    "tag": "Tag",
    "session": "Session",
    "weekday": "Day of Week",
    "hour": "Hour of Day",
    "leverage": "Leverage",
    "emotion_before": "Emotion (before)",
    "emotion_after": "Emotion (after)",
    "rating": "Execution Rating",
    "followed_plan": "Followed Plan",
    "was_overtrading": "Overtrading",
}

_TIME_DIMS = {"weekday", "hour", "session"}

# Mirror of costs._LEVERAGE_BUCKETS (kept local — analytics are mirrored, not shared).
_LEVERAGE_BUCKETS = [
    ("≤3x", 0, 3),
    ("3–5x", 3, 5),
    ("5–10x", 5, 10),
    ("10–20x", 10, 20),
    (">20x", 20, 1e9),
]


def _leverage_bucket(lev):
    if lev is None or lev <= 0:
        return "unknown"
    for label, lo, hi in _LEVERAGE_BUCKETS:
        if lo < lev <= hi:
            return label
    return "unknown"


def _journal_map(db, user_id, position_keys):
    if user_id is None or not position_keys:
        return {}
    rows = db.query(PerpsJournal).filter(
        PerpsJournal.user_id == user_id,
        PerpsJournal.position_key.in_(position_keys),
    ).all()
    return {j.position_key: j for j in rows}


def _tags_map(db, user_id, position_keys):
    """position_key -> [tag name, ...] for the user's positions."""
    from app.perps.models import PerpsTag, perps_position_tags
    if user_id is None or not position_keys:
        return {}
    key_set = set(position_keys)
    tag_rows = db.execute(
        perps_position_tags.select().where(perps_position_tags.c.user_id == user_id)
    ).all()
    names = {t.id: t.name for t in db.query(PerpsTag).filter(PerpsTag.user_id == user_id)}
    out = {}
    for r in tag_rows:
        if r.position_key in key_set:
            out.setdefault(r.position_key, []).append(names.get(r.tag_id, "?"))
    return out


def get_dimension_value(position, journal, tags, dim):
    """Extract the grouping value for a position along a given dimension.

    `journal` is the PerpsJournal for the position (or None); `tags` is a list
    of tag names (possibly empty). Multi-value dims (tag, mistake) are joined
    into one label — the dedicated by-tag/by-mistake tabs give the exploded view.
    """
    p = position
    if dim == "symbol":
        return p.symbol
    if dim == "direction":
        return p.direction.value if p.direction else "Unknown"
    if dim == "weekday":
        return _WEEKDAYS[p.opened_at.weekday()] if p.opened_at else "Unknown"
    if dim == "hour":
        return f"{p.opened_at.hour:02d}:00" if p.opened_at else "Unknown"
    if dim == "session":
        return _session_for(p.opened_at.hour)[0] if p.opened_at else "Unknown"
    if dim == "leverage":
        return _leverage_bucket(p.leverage)
    if dim == "tag":
        return ", ".join(tags) if tags else "Untagged"
    if dim == "setup":
        return journal.setup_name if journal and journal.setup_name else "Unspecified"
    if dim == "grade":
        return journal.grade if journal and journal.grade else "Ungraded"
    if dim == "mistake":
        mt = (journal.mistake_tags if journal and journal.mistake_tags else []) or []
        return ", ".join(mt) if mt else "None"
    if dim == "emotion_before":
        return journal.emotion_before if journal and journal.emotion_before else "Not logged"
    if dim == "emotion_after":
        return journal.emotion_after if journal and journal.emotion_after else "Not logged"
    if dim == "rating":
        return str(journal.rating) if journal and journal.rating else "Not rated"
    if dim == "followed_plan":
        if not journal or journal.followed_plan is None:
            return "Not logged"
        return "Yes" if journal.followed_plan else "No"
    if dim == "was_overtrading":
        if not journal or journal.was_overtrading is None:
            return "Not logged"
        return "Yes" if journal.was_overtrading else "No"
    return "Unknown"


def compute_group_metrics(positions):
    """Metrics for a group of positions — mirrors the prop engine's formulas.

    profit_factor is None (not inf) when there are no losing trades: this matches
    the perps-native convention in analytics._group_metrics, keeps the value
    JSON-serializable (Starlette rejects inf), and the perps frontend renders
    null profit_factor as "∞".
    """
    if not positions:
        return None
    pnls = [p.realized_pnl or 0 for p in positions]
    winners = [v for v in pnls if v > 0]
    losers = [v for v in pnls if v < 0]
    total_wins = sum(winners)
    total_losses = abs(sum(losers))
    r_vals = [p.r_multiple for p in positions if p.r_multiple is not None]
    return {
        "trade_count": len(positions),
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl": round(sum(pnls) / len(positions), 2),
        "win_rate": round(len(winners) / len(positions) * 100, 1),
        "profit_factor": round(total_wins / total_losses, 2) if total_losses > 0 else None,
        "avg_win": round(total_wins / len(winners), 2) if winners else 0,
        "avg_loss": round(-total_losses / len(losers), 2) if losers else 0,
        "avg_r": round(sum(r_vals) / len(r_vals), 2) if r_vals else None,
        "best_trade": round(max(pnls), 2) if pnls else 0,
        "worst_trade": round(min(pnls), 2) if pnls else 0,
    }


def cross_analysis(db: Session, primary_dim: str, secondary_dim: str = None,
                   filters: dict = None, user_id: int = None) -> dict:
    """Cross two perps dimensions and compute metrics for each combination."""
    exact_only = primary_dim in _TIME_DIMS or (bool(secondary_dim) and secondary_dim in _TIME_DIMS)
    positions = _closed_positions(db, user_id, filters, exact_only=exact_only)

    keys = [p.position_key for p in positions if p.position_key]
    jmap = _journal_map(db, user_id, keys)
    tmap = _tags_map(db, user_id, keys)

    def val(p, dim):
        return get_dimension_value(p, jmap.get(p.position_key), tmap.get(p.position_key, []), dim)

    if not positions:
        return {
            "primary_dim": primary_dim,
            "secondary_dim": secondary_dim,
            "groups": [],
            "primary_totals": {},
            "secondary_totals": {},
            "overall": {
                "trade_count": 0, "total_pnl": 0, "avg_pnl": 0, "win_rate": 0,
                "profit_factor": None, "avg_win": 0, "avg_loss": 0, "avg_r": None,
                "best_trade": 0, "worst_trade": 0,
            },
        }

    if secondary_dim:
        cross_groups = defaultdict(list)
        for p in positions:
            cross_groups[(val(p, primary_dim), val(p, secondary_dim))].append(p)
        groups = []
        for (p_val, s_val), items in sorted(cross_groups.items()):
            m = compute_group_metrics(items)
            if m:
                groups.append({"primary": p_val, "secondary": s_val, **m})
    else:
        single = defaultdict(list)
        for p in positions:
            single[val(p, primary_dim)].append(p)
        groups = []
        for v, items in sorted(single.items()):
            m = compute_group_metrics(items)
            if m:
                groups.append({"primary": v, "secondary": None, **m})

    primary_groups = defaultdict(list)
    for p in positions:
        primary_groups[val(p, primary_dim)].append(p)
    primary_totals = {k: compute_group_metrics(v) for k, v in primary_groups.items()}

    secondary_totals = {}
    if secondary_dim:
        sec = defaultdict(list)
        for p in positions:
            sec[val(p, secondary_dim)].append(p)
        secondary_totals = {k: compute_group_metrics(v) for k, v in sec.items()}

    return {
        "primary_dim": primary_dim,
        "secondary_dim": secondary_dim,
        "groups": groups,
        "primary_totals": primary_totals,
        "secondary_totals": secondary_totals,
        "overall": compute_group_metrics(positions),
    }


def compute_insights(db: Session, filters: dict = None, user_id: int = None) -> list[dict]:
    """Auto-detect best/worst combos across key dimension pairs (mirror of prop)."""
    insights = []
    primary_dims = ["setup", "symbol", "session", "weekday", "grade", "direction"]
    secondary_dims = ["weekday", "session", "direction", "grade"]
    seen = set()

    for p in primary_dims:
        for s in secondary_dims:
            if p == s:
                continue
            pair_key = tuple(sorted([p, s]))
            if pair_key in seen:
                continue
            seen.add(pair_key)

            result = cross_analysis(db, p, s, filters, user_id=user_id)
            meaningful = [g for g in result["groups"] if g["trade_count"] >= 3]
            if not meaningful:
                continue

            best = max(meaningful, key=lambda g: g["total_pnl"])
            if best["total_pnl"] > 0:
                insights.append({
                    "type": "positive",
                    "primary_dim": DIMENSIONS.get(p, p),
                    "secondary_dim": DIMENSIONS.get(s, s),
                    "primary_val": best["primary"],
                    "secondary_val": best["secondary"],
                    "metric": "total_pnl",
                    "value": best["total_pnl"],
                    "trade_count": best["trade_count"],
                    "win_rate": best["win_rate"],
                    "profit_factor": best["profit_factor"],
                    "message": f'{best["primary"]} on {best["secondary"]}: ${best["total_pnl"]:.2f} P&L ({best["trade_count"]} trades, {best["win_rate"]:.0f}% WR)',
                })

            worst = min(meaningful, key=lambda g: g["total_pnl"])
            if worst["total_pnl"] < 0:
                insights.append({
                    "type": "negative",
                    "primary_dim": DIMENSIONS.get(p, p),
                    "secondary_dim": DIMENSIONS.get(s, s),
                    "primary_val": worst["primary"],
                    "secondary_val": worst["secondary"],
                    "metric": "total_pnl",
                    "value": worst["total_pnl"],
                    "trade_count": worst["trade_count"],
                    "win_rate": worst["win_rate"],
                    "profit_factor": worst["profit_factor"],
                    "message": f'{worst["primary"]} on {worst["secondary"]}: ${worst["total_pnl"]:.2f} P&L ({worst["trade_count"]} trades, {worst["win_rate"]:.0f}% WR)',
                })

    positive = sorted([i for i in insights if i["type"] == "positive"], key=lambda x: -x["value"])
    negative = sorted([i for i in insights if i["type"] == "negative"], key=lambda x: x["value"])
    return positive[:5] + negative[:5]
