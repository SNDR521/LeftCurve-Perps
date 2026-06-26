"""Planned/actual risk:reward for perps positions (TradeStream model).

actual_r: triggered stop -> -1; else signed price move divided by per-unit
risk (|entry - stop|, falling back to MAE when no stop is recorded).
planned_rr: pct-weighted avg target distance over stop distance.
"""
from __future__ import annotations

from app.perps.models import Direction

_EPS = 1e-12


def compute_risk(position, journal) -> dict:
    out = {"planned_rr": None, "actual_r": None, "risk_source": None}
    if position is None:
        return out
    entry = position.avg_entry or 0.0
    stop = getattr(journal, "stop_price", None) if journal else None
    targets = (getattr(journal, "targets", None) or []) if journal else []

    # A stop on the wrong side of entry (LONG stop above, SHORT stop below)
    # could never have produced a 1R loss — using its distance would anchor R
    # to a structurally invalid risk. Treat it as no stop (MAE fallback).
    if stop is not None:
        wrong_side = (position.direction == Direction.LONG and stop >= entry) or \
                     (position.direction == Direction.SHORT and stop <= entry)
        if wrong_side:
            stop = None

    risk_per_unit = None
    if stop is not None and abs(entry - stop) > _EPS:
        risk_per_unit, out["risk_source"] = abs(entry - stop), "stop"
    elif getattr(position, "mae_price", None):
        # NOTE: mae_price == 0.0 (instant winner, never in drawdown) is falsy
        # on purpose — with no stop and zero adverse excursion there is no
        # measurable per-unit risk, so R stays None rather than near-infinite.
        risk_per_unit, out["risk_source"] = position.mae_price, "mae"

    if journal is not None and getattr(journal, "stop_triggered", False):
        out["actual_r"] = -1.0
    elif risk_per_unit and position.avg_exit is not None:
        sign = 1.0 if position.direction == Direction.LONG else -1.0
        out["actual_r"] = (position.avg_exit - entry) * sign / risk_per_unit

    if stop is not None and targets and abs(entry - stop) > _EPS:
        # .get() hardening: the API validates targets (TargetIn), but old or
        # hand-edited JSON rows must degrade to planned_rr=None, not crash.
        total_pct = sum(t.get("pct", 0) or 0 for t in targets)
        if total_pct > _EPS:
            avg_target = sum((t.get("price", 0) or 0) * (t.get("pct", 0) or 0)
                             for t in targets) / total_pct
            out["planned_rr"] = abs(avg_target - entry) / abs(entry - stop)
    return out
