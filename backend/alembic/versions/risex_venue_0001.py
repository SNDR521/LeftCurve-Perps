"""add RISEX to the venue enum

Revision ID: risex_venue_0001
Revises: 7889aeac82f5
"""
from alembic import op

revision = "risex_venue_0001"
down_revision = "7889aeac82f5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ADD VALUE cannot run inside a transaction on older PG; autocommit_block
        # runs it outside Alembic's transaction. IF NOT EXISTS makes it idempotent.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE venue ADD VALUE IF NOT EXISTS 'RISEX'")
    # SQLite stores enums as plain strings — no schema change needed.


def downgrade():
    # Postgres cannot drop an enum value; intentionally a no-op.
    pass
