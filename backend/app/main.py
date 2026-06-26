from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path

from app.config import get_settings
from app.core.auth import router as core_auth_router
from app.market.routers import router as market_router
from app.perps.routers import (
    exchange_accounts as perps_accounts, fills as perps_fills,
    positions as perps_positions, analytics as perps_analytics,
    reports as perps_reports, journal as perps_journal,
    chart_data as perps_chart_data, cockpit as perps_cockpit,
)
from app.workflow.routers import (
    plan_cards as workflow_plan_cards, playbooks as workflow_playbooks,
    reviews as workflow_reviews, symbol_stats as workflow_symbol_stats,
    watchlist as workflow_watchlist, alerts as workflow_alerts,
)
from app.alarms.routers import alarms as alarms_router, telegram as alarms_telegram

settings = get_settings()
app = FastAPI(title="LeftCurve", description="Self-hosted perps trading journal", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax", https_only=False)

screenshots_dir = Path("screenshots"); screenshots_dir.mkdir(exist_ok=True)
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")

app.include_router(core_auth_router)
app.include_router(market_router, prefix="/api")

PERPS = "/api/perps"
for r in (perps_accounts, perps_fills, perps_positions, perps_analytics,
          perps_reports, perps_journal, perps_chart_data, perps_cockpit):
    app.include_router(r.router, prefix=PERPS)

WORKFLOW = "/api/workflow"
for r in (workflow_plan_cards, workflow_playbooks, workflow_reviews, workflow_symbol_stats,
          workflow_watchlist, workflow_alerts):
    app.include_router(r.router, prefix=WORKFLOW)

app.include_router(alarms_router.router, prefix="/api")
app.include_router(alarms_telegram.router, prefix="/api")


@app.on_event("startup")
async def startup():
    import logging
    from app.perps import scheduler as perps_scheduler
    from app.alarms.engine import realtime, realtime_hl, positions as alarm_positions
    for label, start in (
        ("perps scheduler", perps_scheduler.start_scheduler),
        ("alarm realtime", realtime.start),
        ("alarm realtime HL", realtime_hl.start),
        ("alarm positions", alarm_positions.start_scheduler),
    ):
        try:
            start()
        except Exception:
            logging.getLogger(__name__).exception("%s failed to start", label)


@app.on_event("shutdown")
async def shutdown():
    from app.perps import scheduler as perps_scheduler
    from app.alarms.engine import realtime, realtime_hl, positions as alarm_positions
    for stop in (perps_scheduler.shutdown_scheduler, realtime.stop, realtime_hl.stop,
                 alarm_positions.shutdown_scheduler):
        try:
            stop()
        except Exception:
            pass


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
