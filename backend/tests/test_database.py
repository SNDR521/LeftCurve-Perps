from app.database import make_engine


def test_sqlite_url_builds_sqlite_engine():
    eng = make_engine("sqlite:///:memory:")
    assert eng.dialect.name == "sqlite"


def test_postgres_url_builds_postgres_engine_without_sqlite_args():
    # Must not raise (would raise if check_same_thread were passed to psycopg)
    eng = make_engine("postgresql+psycopg://user:pass@localhost:5432/leftcurve")
    assert eng.dialect.name == "postgresql"
