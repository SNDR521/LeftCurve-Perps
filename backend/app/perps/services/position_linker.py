"""Attribution-only fill→position linkage.

Replays one (account, symbol)'s time-ordered fills into flat→flat *chains*
(net-position logic). Chains attribute entry times, executions and funding to
Bybit closed-PnL positions — they NEVER compute P&L (closed-PnL rows are the
only money truth; see the master roadmap spec).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace

log = logging.getLogger(__name__)

_EPS = 1e-9
ENTRY_TOLERANCE = 0.005  # relative avg-entry mismatch beyond this → ESTIMATED


@dataclass
class ChainClose:
    order_id: str | None
    closed_at: datetime
    # Cumulative weighted avg over ALL chain entries up to this close. NOT
    # equivalent to Bybit's avgEntryPrice when a re-add followed a partial
    # close (Bybit re-weights only the surviving size). Chains where the two
    # diverge beyond ENTRY_TOLERANCE fall back to ESTIMATED — conservative,
    # never wrong.
    avg_entry: float


@dataclass
class Chain:
    direction: str                      # "LONG" | "SHORT"
    opened_at: datetime
    closed_at: datetime | None = None   # None = still open at end of fills
    fill_ids: list[int] = field(default_factory=list)
    closes: list[ChainClose] = field(default_factory=list)


def build_chains(fills) -> list[Chain]:
    """fills: trade fills (quantity > 0) ordered by executed_at, id.

    Fills with order_id=None still produce ChainClose entries (with
    order_id=None); consumers that match by order id must skip those.
    """
    chains: list[Chain] = []
    cur: Chain | None = None
    entry_qty = entry_notional = open_remaining = 0.0

    for f in fills:
        qty = float(f.quantity or 0)
        if qty <= _EPS:
            continue
        fdir = 1 if str(f.side).upper().endswith("BUY") else -1
        q = qty
        while q > _EPS:
            if cur is None:
                cur = Chain(direction="LONG" if fdir > 0 else "SHORT", opened_at=f.executed_at)
                entry_qty = entry_notional = open_remaining = 0.0
            if not cur.fill_ids or cur.fill_ids[-1] != f.id:
                cur.fill_ids.append(f.id)
            cur_dir = 1 if cur.direction == "LONG" else -1
            if fdir == cur_dir:
                entry_qty += q
                entry_notional += float(f.price) * q
                open_remaining += q
                q = 0.0
            else:
                close_qty = min(q, open_remaining)
                open_remaining -= close_qty
                q -= close_qty
                cur.closes.append(ChainClose(
                    order_id=f.order_id, closed_at=f.executed_at,
                    avg_entry=entry_notional / entry_qty if entry_qty > _EPS else 0.0,
                ))
                if open_remaining <= _EPS:
                    cur.closed_at = f.executed_at
                    chains.append(cur)
                    cur = None

    if cur is not None:
        chains.append(cur)
    return chains


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo is not None else dt


def _order_lookup(chains) -> dict:
    """First ChainClose index per closing order id, across chains."""
    lookup: dict[str, tuple[Chain, int]] = {}
    for c in chains:
        for i, cl in enumerate(c.closes):
            if cl.order_id and cl.order_id not in lookup:
                lookup[cl.order_id] = (c, i)
    return lookup


def _is_exact(chain: Chain, close: ChainClose, position) -> bool:
    """The EXACT criteria: direction match + avg-entry within tolerance."""
    ref = position.avg_entry or 0.0
    return (chain.direction == position.direction.value
            and ref > 0
            and abs(close.avg_entry - ref) / ref <= ENTRY_TOLERANCE)


def link_account(db, account) -> dict:
    """Re-derive fill↔position attribution for one account. Idempotent
    (wipes and rebuilds all links touching this account's fills/positions)."""
    from app.perps.models import (
        Fill, Position, PositionFill, PositionStatus, OpenedAtSource,
    )

    db.query(PositionFill).filter(
        PositionFill.fill_id.in_(
            db.query(Fill.id).filter(Fill.exchange_account_id == account.id)
        )
    ).delete(synchronize_session=False)
    db.commit()

    out = {"exact": 0, "estimated": 0}
    symbols = [sym for (sym,) in db.query(Fill.symbol)
               .filter(Fill.exchange_account_id == account.id).distinct()]

    for symbol in symbols:
        fills = (db.query(Fill)
                 .filter(Fill.exchange_account_id == account.id, Fill.symbol == symbol)
                 .order_by(Fill.executed_at.asc(), Fill.id.asc()).all())
        trade_fills = [f for f in fills if (f.quantity or 0) > _EPS]
        funding_fills = [f for f in fills if (f.quantity or 0) <= _EPS and f.funding_amount]
        fills_by_id = {f.id: f for f in fills}

        positions = (db.query(Position)
                     .filter(Position.exchange_account_id == account.id,
                             Position.symbol == symbol,
                             Position.status == PositionStatus.CLOSED,
                             Position.position_key.like("%:cpnl:%")).all())

        chains = build_chains(trade_fills)

        # Gap compensation: Bybit's fill feed has holes — the ~2y retention
        # wall at the head, and mid-history events that never appear in
        # /v5/execution/list (observed even same-day). Any hole gives the
        # replay a permanent net offset, so chain boundaries after it are
        # wrong and matches fail. We can't know WHERE the holes are, but we
        # know their net total (replay end net vs the live open position).
        # Build a second variant seeded with a synthetic price-0 entry at the
        # head: it re-aligns everything after the LAST hole (recent trades)
        # while the unseeded replay covers everything before the FIRST hole.
        # Each position is matched against BOTH (per-position union) — the
        # direction + avg-entry tolerance gate makes any match trustworthy
        # regardless of variant.
        seeded_chains = []
        if trade_fills:
            replay_net = sum(
                f.quantity if str(f.side).upper().endswith("BUY") else -f.quantity
                for f in trade_fills
            )
            open_pos = (db.query(Position)
                        .filter(Position.exchange_account_id == account.id,
                                Position.symbol == symbol,
                                Position.status == PositionStatus.OPEN)
                        .first())
            actual_net = 0.0
            if open_pos is not None:
                actual_net = open_pos.quantity if open_pos.direction.value == "LONG" \
                    else -(open_pos.quantity or 0.0)
            offset = actual_net - replay_net
            if abs(offset) > _EPS:
                seed = SimpleNamespace(
                    id=None, order_id=None, price=0.0, quantity=abs(offset),
                    side="BUY" if offset > 0 else "SELL",
                    executed_at=_naive(trade_fills[0].executed_at) - timedelta(seconds=1),
                )
                seeded_chains = build_chains([seed] + trade_fills)
                log.info("linker %s %s: net offset %.6f — matching against both variants",
                         account.id, symbol, offset)

        order_lookup = _order_lookup(chains)
        seeded_lookup = _order_lookup(seeded_chains) if seeded_chains else {}

        for p in positions:
            order_id = p.position_key.split(":cpnl:")[-1]
            exact = False
            chain = ci = None
            for lookup in (order_lookup, seeded_lookup):
                hit = lookup.get(order_id)
                if hit is not None and _is_exact(hit[0], hit[0].closes[hit[1]], p):
                    chain, ci = hit
                    exact = True
                    break
            if not exact:
                # Reset linker-owned fields so an EXACT→ESTIMATED flip on a
                # later run (e.g. late-arriving fills shifting a chain) can't
                # leave stale attribution from a previous run.
                p.opened_at_source = OpenedAtSource.ESTIMATED
                if p.closed_at is not None:
                    p.opened_at = _naive(p.closed_at)
                p.duration_seconds = None
                p.total_funding = 0.0
                out["estimated"] += 1
                continue

            prev_opened = _naive(p.opened_at)
            p.opened_at = _naive(chain.opened_at)
            p.opened_at_source = OpenedAtSource.EXACT
            if prev_opened != p.opened_at:
                # excursion window moved — stale MFE/MAE must be recomputed
                p.mfe_price = p.mae_price = p.mfe_usd = p.mae_usd = None
            closed_at = _naive(p.closed_at)
            if closed_at is not None:
                p.duration_seconds = int((closed_at - p.opened_at).total_seconds())

            # funding window: (previous close in chain, this close]. Known
            # under-attribution: if an earlier close's cpnl row is missing
            # (aged past Bybit's 2y retention), funding before that close is
            # attributed to no position — an under-count, never a double-count.
            win_start = _naive(chain.closes[ci - 1].closed_at) if ci > 0 else p.opened_at
            entry_side = "BUY" if p.direction.value == "LONG" else "SELL"

            linked: set[int] = set()
            for fid in chain.fill_ids:
                f = fills_by_id.get(fid)
                if f is None:
                    continue  # synthetic head seed — not a real fill
                ft = _naive(f.executed_at)
                if str(f.side.value).upper() == entry_side and ft <= closed_at:
                    linked.add(fid)                       # shared entry fills
                elif f.order_id == order_id:
                    linked.add(fid)                       # this position's closing fills
            funding_sum = 0.0
            for f in funding_fills:
                ft = _naive(f.executed_at)
                if win_start < ft <= closed_at:
                    linked.add(f.id)
                    funding_sum += f.funding_amount or 0.0
            p.total_funding = funding_sum

            for fid in linked:
                db.add(PositionFill(position_id=p.id, fill_id=fid))
            out["exact"] += 1
        db.commit()

    log.info("linker account=%s exact=%d estimated=%d", account.id, out["exact"], out["estimated"])
    return out
