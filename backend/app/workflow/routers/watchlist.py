"""Watchlist CRUD endpoints.

Each item is user-scoped. Symbol uniqueness is enforced at the application
layer (pre-checked, 400 returned) to give a clear error before hitting the
database unique constraint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.workflow.models import WatchlistItem
from app.workflow.schemas import WatchlistIn, WatchlistOut, WatchlistUpdate

router = APIRouter(prefix="/watchlist", tags=["workflow-watchlist"])


@router.get("", response_model=list[WatchlistOut])
def list_watchlist(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's watchlist items, newest first."""
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.id.desc())
        .all()
    )
    return items


@router.post("", response_model=WatchlistOut, status_code=201)
def create_watchlist_item(
    body: WatchlistIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a symbol to the watchlist. Returns 400 if the symbol is already watched."""
    existing = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.id,
                WatchlistItem.symbol == body.symbol)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=400,
                            detail="Symbol already in watchlist")

    item = WatchlistItem(
        user_id=user.id,
        symbol=body.symbol,
        market=body.market,
        note=body.note,
        levels=[lvl.model_dump() for lvl in body.levels],
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=WatchlistOut)
def update_watchlist_item(
    item_id: int,
    body: WatchlistUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Partial update of a watchlist item (only sent fields change). 404 if not owned."""
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.id == item_id, WatchlistItem.user_id == user.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    data = body.model_dump(exclude_unset=True)
    # Serialise LevelIn objects to plain dicts for JSON storage
    if "levels" in data and data["levels"] is not None:
        data["levels"] = [
            lvl.model_dump() if hasattr(lvl, "model_dump") else lvl
            for lvl in (body.levels or [])
        ]
    for k, v in data.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=204)
def delete_watchlist_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a watchlist item. 404 if not owned by the current user."""
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.id == item_id, WatchlistItem.user_id == user.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    db.delete(item)
    db.commit()
