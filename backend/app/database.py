from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_settings

settings = get_settings()

Base = declarative_base()


def make_engine(database_url: str):
    """Build a SQLAlchemy engine, applying SQLite-only connect args only for SQLite."""
    connect_args = {}
    if make_url(database_url).get_backend_name() == "sqlite":
        connect_args = {"check_same_thread": False}
    return create_engine(
        database_url,
        connect_args=connect_args,
        echo=False,
        pool_pre_ping=True,
    )


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Used only for SQLite/test fallback; Alembic owns Postgres schema."""
    from app.core.models import User  # noqa: F401
    from app.perps import models as _perps_models  # noqa: F401
    import app.workflow.models  # noqa: F401
    from app.alarms import models as _alarm_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
