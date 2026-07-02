"""Live cockpit assembly: what the exchange UI doesn't answer — risk if
stopped (in $ and R), session discipline, funding pressure."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.perps.models import Fill, PerpsJournal, Position, PositionStatus

_EPS = 1e-12


def _today_utc():
    # Session boundary is UTC midnight here (the perps-only fallback used when no
    # plan card exists). When a plan card IS active the boundary becomes plan-aware:
    # build_cockpit swaps these aggregates for the card's session window via
    # _active_plan_card / score_card (R4).
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def _active_plan_card(db: Session, user_id: int, now: datetime):
    """Today's OR yesterday's PlanCard whose session window contains naive-UTC ``now``.

    Cards with ``session_start_hour > 0`` straddle midnight, so the card whose window
    covers ``now`` may be dated yesterday. We check both today's and yesterday's card
    and return the one whose ``window_for_card`` contains ``now`` — preferring today's
    when both match. Returns ``None`` when neither contains ``now``.
    """
    # Function-level import: workflow.scoring imports only perps + prop models/services
    # (no app.workflow ← perps cycle today); kept local to stay robust to future chains.
    from app.workflow.models import PlanCard
    from app.workflow.services.scoring import window_for_card

    today = now.date()
    yesterday = today - timedelta(days=1)
    cards = (db.query(PlanCard)
             .filter(PlanCard.user_id == user_id,
                     PlanCard.date.in_([today, yesterday])).all())
    by_date = {c.date: c for c in cards}
    for d in (today, yesterday):  # prefer today's card when both windows match
        card = by_date.get(d)
        if card is None:
            continue
        start, end = window_for_card(card)
        if start <= now < end:
            return card
    return None


def _session_block(db: Session, user_id: int, account_id):
    """(realized_today, trades_today, plan). Plan-card mode is workspace-level
    (score_card perps, ignores account_id, as before). The no-card fallback
    scopes to account_id when given (single-account) or all the user's perps
    closed positions when None (aggregate)."""
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    card = _active_plan_card(db, user_id, now_naive)
    if card is not None:
        from app.workflow.services.scoring import score_card
        score = score_card(db, user_id, card, workspace="perps")
        plan = {
            "date": card.date.isoformat(), "max_trades": card.max_trades,
            "trades_count": score["trades_count"], "max_daily_loss": card.max_daily_loss,
            "realized": score["realized"], "trades_over": score["flags"]["trades_over"],
            "loss_breached": score["flags"]["loss_breached"],
        }
        return score["realized"], score["trades_count"], plan
    midnight = _today_utc()
    q = db.query(Position).filter(Position.status == PositionStatus.CLOSED,
                                  Position.closed_at >= midnight)
    if account_id is not None:
        q = q.filter(Position.exchange_account_id == account_id)
    else:
        q = q.filter(Position.user_id == user_id)
    realized = (q.with_entities(func.coalesce(func.sum(Position.realized_pnl), 0.0)).scalar()) or 0.0
    trades = (q.with_entities(func.count(Position.id)).scalar()) or 0
    return realized, trades, None


def _account_live(db: Session, account, client) -> dict:
    """Per-account LIVE parts only (no session/plan). Positions tagged with
    venue / account_id / account_label. Equity-relative ratios are computed by
    the composer (single uses this account's equity; aggregate uses the total)."""
    raw_positions = client.fetch_open_positions()
    symbols = [r["symbol"] for r in raw_positions]
    tickers = client.fetch_tickers(symbols) if symbols else {}
    wallet = client.fetch_wallet_balance()

    positions = []
    open_upnl = gross = net = open_risk = 0.0
    unstopped = 0
    for r in raw_positions:
        symbol = r["symbol"]
        direction = "LONG" if str(r.get("side", "")).upper().startswith("B") else "SHORT"
        sign = 1.0 if direction == "LONG" else -1.0
        qty = float(r.get("size") or 0.0)
        entry = float(r.get("avgPrice") or 0.0)
        t = tickers.get(symbol, {})
        mark = t.get("mark_price") or entry
        upnl = float(r.get("unrealisedPnl") or 0.0)
        notional = mark * qty
        liq = float(r.get("liqPrice") or 0.0) or None
        rate = t.get("funding_rate") or 0.0

        open_row = (db.query(Position)
                    .filter(Position.exchange_account_id == account.id,
                            Position.symbol == symbol,
                            Position.status == PositionStatus.OPEN).first())
        accrued = 0.0
        if open_row is not None:
            accrued = (db.query(func.coalesce(func.sum(Fill.funding_amount), 0.0))
                       .filter(Fill.exchange_account_id == account.id,
                               Fill.symbol == symbol,
                               Fill.quantity <= _EPS,
                               Fill.executed_at >= open_row.opened_at).scalar()) or 0.0

        journal = (db.query(PerpsJournal)
                   .filter(PerpsJournal.user_id == account.user_id,
                           PerpsJournal.position_key == f"{account.id}:{symbol}:open")
                   .first())
        journal_stop = getattr(journal, "stop_price", None) if journal else None
        # The trader's real SL usually lives on the exchange: Bybit carries it on the
        # position row as stopLoss; Hyperliquid has none on the position, so the HL
        # client reads it from the open Stop trigger orders (also surfaced as stopLoss).
        # A journal stop is an explicit intention and overrides; else the exchange stop.
        exchange_stop = float(r.get("stopLoss") or 0.0) or None
        stop = journal_stop if journal_stop is not None else exchange_stop
        stop_source = ("journal" if journal_stop is not None
                       else "exchange" if exchange_stop is not None else None)
        live_r = risk_usd = None
        if stop is not None:
            wrong_side = (direction == "LONG" and stop >= entry) or \
                         (direction == "SHORT" and stop <= entry)
            if not wrong_side and abs(entry - stop) > _EPS:
                live_r = (mark - entry) * sign / abs(entry - stop)
                risk_usd = abs(entry - stop) * qty
        if risk_usd is None:
            unstopped += 1
        else:
            open_risk += risk_usd

        open_upnl += upnl
        gross += notional
        net += notional * sign
        positions.append({
            "symbol": symbol, "direction": direction, "qty": qty,
            "avg_entry": entry, "mark": mark, "upnl": upnl,
            "upnl_pct": (upnl / (entry * qty) * 100) if entry * qty > _EPS else None,
            "notional": notional, "leverage": float(r.get("leverage") or 0.0) or None,
            "liq_price": liq,
            "liq_distance_pct": (abs(mark - liq) / mark * 100) if (liq and mark > _EPS) else None,
            "margin_mode": "isolated" if r.get("tradeMode") in (1, "1") else "cross",
            "funding_rate": rate, "next_funding_at": t.get("next_funding_time"),
            "projected_funding_24h": -rate * notional * 3 * sign,
            "accrued_funding": accrued,
            "stop_price": stop, "stop_source": stop_source,
            "live_r": live_r, "risk_usd": risk_usd,
            # multi-account tagging
            "venue": account.venue.value, "account_id": account.id,
            "account_label": account.label,
            # RiseX orderbook-WS subscription key (None for Bybit/HL)
            "market_id": r.get("marketId"),
        })

    return {
        "equity": wallet.get("equity") or 0.0,
        "balance": wallet.get("balance"), "available": wallet.get("available"),
        "open_upnl": open_upnl, "gross_notional": gross, "net_notional": net,
        "open_risk_usd": open_risk, "unstopped_count": unstopped,
        "positions": positions,
    }


def _compose(account_id, equity, balance, available, open_upnl, gross, net,
             open_risk, unstopped, realized_today, trades_today, plan, positions,
             unavailable=None) -> dict:
    out = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "plan": plan,
        "account": {
            "account_id": account_id,
            "equity": equity, "balance": balance, "available": available,
            "realized_today": realized_today, "trades_today": trades_today,
            "open_upnl": open_upnl, "session_pnl": realized_today + open_upnl,
            "gross_notional": gross, "net_notional": net,
            "exposure_pct": (gross / equity * 100) if equity > _EPS else None,
            "open_risk_usd": open_risk,
            "open_risk_pct": (open_risk / equity * 100) if equity > _EPS else None,
            "unstopped_count": unstopped,
        },
        "positions": positions,
    }
    if unavailable is not None:
        out["unavailable"] = unavailable
    return out


def build_cockpit(db: Session, account, client) -> dict:
    live = _account_live(db, account, client)
    realized_today, trades_today, plan = _session_block(db, account.user_id, account.id)
    return _compose(account.id, live["equity"], live["balance"], live["available"],
                    live["open_upnl"], live["gross_notional"], live["net_notional"],
                    live["open_risk_usd"], live["unstopped_count"],
                    realized_today, trades_today, plan, live["positions"])


def build_cockpit_aggregate(db: Session, user_id: int, live_results: list[dict],
                            unavailable: list[str]) -> dict:
    equity = sum(r["equity"] for r in live_results)
    balance = sum((r["balance"] or 0.0) for r in live_results)
    available = sum((r["available"] or 0.0) for r in live_results)
    open_upnl = sum(r["open_upnl"] for r in live_results)
    gross = sum(r["gross_notional"] for r in live_results)
    net = sum(r["net_notional"] for r in live_results)
    open_risk = sum(r["open_risk_usd"] for r in live_results)
    unstopped = sum(r["unstopped_count"] for r in live_results)
    positions = [p for r in live_results for p in r["positions"]]
    realized_today, trades_today, plan = _session_block(db, user_id, None)
    return _compose(None, equity, balance, available, open_upnl, gross, net,
                    open_risk, unstopped, realized_today, trades_today, plan,
                    positions, unavailable=unavailable)
