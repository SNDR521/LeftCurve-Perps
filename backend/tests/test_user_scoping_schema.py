from sqlalchemy import inspect
from app.database import engine, init_db


def test_user_and_scoped_tables_exist():
    init_db()
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "users" in tables
    scoped = ["exchange_accounts", "fills", "positions", "perps_journal"]
    for t in scoped:
        assert t in tables, f"table {t!r} missing"
        cols = {c["name"] for c in insp.get_columns(t)}
        assert "user_id" in cols, f"{t} missing user_id"


def test_auth_tables_shape():
    from sqlalchemy import inspect
    from app.database import engine, init_db
    init_db()
    insp = inspect(engine)
    user_cols = {c["name"] for c in insp.get_columns("users")}
    assert "password_hash" in user_cols
    assert "google_sub" not in user_cols
    assert "is_admin" not in user_cols
    assert "auth_tokens" not in insp.get_table_names()


def test_perps_tables_shape():
    from sqlalchemy import inspect
    from app.database import engine, init_db
    init_db()
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert {"exchange_accounts", "fills", "positions"} <= tables
    for t in ("exchange_accounts", "fills", "positions"):
        cols = {c["name"] for c in insp.get_columns(t)}
        assert "user_id" in cols, f"{t} missing user_id"
    fill_cols = {c["name"] for c in insp.get_columns("fills")}
    assert {"stop_price", "risk_amount", "funding_amount", "external_fill_id"} <= fill_cols


def test_perps_journal_schema():
    from sqlalchemy import inspect
    from app.database import engine, init_db
    init_db()
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert {"perps_journal", "perps_tags", "perps_position_tags"} <= tables
    assert "position_key" in {c["name"] for c in insp.get_columns("positions")}
    jcols = {c["name"] for c in insp.get_columns("perps_journal")}
    assert {"position_key", "setup_name", "grade", "mistake_tags", "notes"} <= jcols
