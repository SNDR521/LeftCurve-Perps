"""Playbook endpoints with perps edge stats.

Each playbook's ``stats`` field shows live performance data from the perps
workspace (by PerpsJournal.setup_name).  Matching is case-sensitive against
the playbook name so "Breakout" only merges with setups named exactly "Breakout".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.workflow.models import Playbook
from app.workflow.schemas import PlaybookIn, PlaybookOut, PlaybookUpdate

from app.perps.services.analytics import (
    compute_performance_by_group as perps_perf_by_group,
)

router = APIRouter(prefix="/playbooks", tags=["workflow-playbooks"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_stats_index(db: Session, user_id: int) -> dict[str, dict]:
    """Return a dict keyed by setup name → perps stats.

    Perps compute_performance_by_group("setup") groups closed positions by
    PerpsJournal.setup_name (falls back to "Unspecified").

    "Unspecified" cannot match a user-defined playbook name in practice, so
    that bucket is silently ignored.
    """
    try:
        perps_rows = perps_perf_by_group(db, "setup", filters=None, user_id=user_id)
    except Exception:
        perps_rows = []

    index: dict[str, dict] = {}

    for row in perps_rows:
        name = row.group
        index[name] = {
            "trade_count": row.trade_count,
            "win_rate": row.win_rate,
            "total_pnl": row.total_pnl,
        }

    return index


def _zero_stats() -> dict:
    return {"trade_count": 0, "win_rate": 0.0, "total_pnl": 0.0}


def _attach_stats(playbooks: list[Playbook], stats_index: dict[str, dict]) -> list[dict]:
    """Convert ORM rows to dicts with stats injected."""
    out = []
    for pb in playbooks:
        row = PlaybookOut.model_validate(pb)
        row.stats = stats_index.get(pb.name, _zero_stats())
        out.append(row.model_dump())
    return out


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
def list_playbooks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all playbooks for the current user, each with cross-workspace stats."""
    playbooks = (
        db.query(Playbook)
        .filter(Playbook.user_id == user.id)
        .order_by(Playbook.name)
        .all()
    )
    stats_index = _build_stats_index(db, user.id)
    return _attach_stats(playbooks, stats_index)


@router.get("/names")
def list_playbook_names(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[str]:
    """Return sorted list of playbook names — useful for datalist/autocomplete."""
    rows = (
        db.query(Playbook.name)
        .filter(Playbook.user_id == user.id)
        .order_by(Playbook.name)
        .all()
    )
    return [r.name for r in rows]


@router.post("", status_code=201)
def create_playbook(
    body: PlaybookIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a playbook.  Returns 400 if the name already exists for this user."""
    existing = (
        db.query(Playbook)
        .filter(Playbook.user_id == user.id, Playbook.name == body.name)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail="Playbook name already exists")

    pb = Playbook(
        user_id=user.id,
        name=body.name,
        context_requirements=body.context_requirements,
        entry_triggers=body.entry_triggers,
        invalidation=body.invalidation,
        management=body.management,
        notes=body.notes,
    )
    db.add(pb)
    db.commit()
    db.refresh(pb)

    row = PlaybookOut.model_validate(pb)
    row.stats = _zero_stats()
    return row.model_dump()


@router.put("/{playbook_id}")
def update_playbook(
    playbook_id: int,
    body: PlaybookUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a playbook (partial — only sent fields change).  Returns 404 if not owned."""
    pb = (
        db.query(Playbook)
        .filter(Playbook.id == playbook_id, Playbook.user_id == user.id)
        .first()
    )
    if pb is None:
        raise HTTPException(status_code=404, detail="Playbook not found")

    # If renaming, check for duplicate name.
    data = body.model_dump(exclude_unset=True)
    new_name = data.get("name")
    if new_name is not None and new_name != pb.name:
        conflict = (
            db.query(Playbook)
            .filter(Playbook.user_id == user.id, Playbook.name == new_name)
            .first()
        )
        if conflict is not None:
            raise HTTPException(status_code=400, detail="Playbook name already exists")

    for k, v in data.items():
        setattr(pb, k, v)
    db.commit()
    db.refresh(pb)

    stats_index = _build_stats_index(db, user.id)
    row = PlaybookOut.model_validate(pb)
    row.stats = stats_index.get(pb.name, _zero_stats())
    return row.model_dump()


@router.delete("/{playbook_id}", status_code=204)
def delete_playbook(
    playbook_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a playbook row.  Does NOT touch perps or prop journal entries —
    setup_name strings in journals are freeform and are not FK-linked to playbooks."""
    pb = (
        db.query(Playbook)
        .filter(Playbook.id == playbook_id, Playbook.user_id == user.id)
        .first()
    )
    if pb is None:
        raise HTTPException(status_code=404, detail="Playbook not found")

    db.delete(pb)
    db.commit()
