import copy
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User, UserPreferences

router = APIRouter(prefix="/preferences", tags=["preferences"])

DEFAULT_PREFS = {
    "ticker_bar": {"enabled": True, "symbols": [
        {"symbol": "ES=F", "label": "US500", "source": "yahoo"},
        {"symbol": "NQ=F", "label": "US100", "source": "yahoo"},
        {"symbol": "RTY=F", "label": "US2000", "source": "yahoo"},
        {"symbol": "^GDAXI", "label": "DAX40", "source": "yahoo"},
        {"symbol": "^VIX", "label": "VIX", "source": "yahoo"},
        {"symbol": "GC=F", "label": "GOLD", "source": "yahoo"},
        {"symbol": "CL=F", "label": "OIL", "source": "yahoo"},
        {"symbol": "BTCUSDT", "label": "BTC", "source": "bybit"},
        {"symbol": "ETHUSDT", "label": "ETH", "source": "bybit"},
        {"symbol": "SOLUSDT", "label": "SOL", "source": "bybit"},
    ]},
    "default_period": "all",
    "pnl_view": "dollars",
    "landing": {"path": "/"},
    "theme": {"accent": "#38bdf8", "density": "comfortable"},
}

def _merged(stored):
    out = copy.deepcopy(DEFAULT_PREFS)
    if stored:
        for k, v in stored.items():
            out[k] = v
    return out

@router.get("")
def get_preferences(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    return _merged(row.prefs if row else None)

@router.put("")
def put_preferences(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    if row is None:
        row = UserPreferences(user_id=user.id, prefs={})
        db.add(row)
    merged = dict(row.prefs or {})
    for k, v in (body or {}).items():
        merged[k] = v
    row.prefs = merged
    db.commit(); db.refresh(row)
    return _merged(row.prefs)
