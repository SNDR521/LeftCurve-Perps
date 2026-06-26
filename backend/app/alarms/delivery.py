"""Fire an alarm: write an in-app Alert and advance the alarm's state.
Telegram delivery is added in Phase 2 (deliver['telegram'])."""
from datetime import datetime, timezone
from app.workflow.models import Alert


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _describe(alarm, price) -> str:
    base = {
        "CROSS": "crossed", "CROSS_UP": "crossed up", "CROSS_DOWN": "crossed down",
        "GTE": "rose to ≥", "LTE": "fell to ≤", "PCT_MOVE": "moved %",
    }.get(alarm.condition, alarm.condition)
    return f"{alarm.symbol} {base} {alarm.value} (now {price})"


def fire(db, alarm, price, source="live") -> Alert | None:
    """Create the fired-event Alert (when any channel is active) and advance
    alarm state. Returns the Alert (or None if no channel is active). Caller commits.
    payload['in_app'] records inbox visibility; payload['telegram'] requests a TG push."""
    deliver = alarm.deliver or {"in_app": True}
    want_in_app = bool(deliver.get("in_app", True))
    want_tg = bool(deliver.get("telegram"))
    alert = None
    if want_in_app or want_tg:
        alert = Alert(
            user_id=alarm.user_id, kind="ALARM", symbol=alarm.symbol,
            payload={
                "alarm_id": alarm.id, "symbol": alarm.symbol, "market": alarm.market,
                "condition": alarm.condition, "value": alarm.value, "price": price,
                "message": alarm.message, "text": _describe(alarm, price), "source": source,
                "in_app": want_in_app, "telegram": want_tg,
            },
            triggered_at=_now(),
        )
        db.add(alert)
    alarm.last_fired_at = _now()
    alarm.fired_count = (alarm.fired_count or 0) + 1
    if alarm.trigger_mode == "ONCE":
        alarm.status = "TRIGGERED"
        alarm.enabled = False
    return alert
