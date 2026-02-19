"""initial schema (pg_dump)

Revision ID: d79a883ddb7c
Revises:
Create Date: 2026-02-18
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "d79a883ddb7c"
down_revision = None
branch_labels = None
depends_on = None


def _loadSchemaSql() -> str:
    # loadSchemaSqlFromRepo
    schemaPath = Path(__file__).resolve().parents[1] / "initial_schema.sql"
    if not schemaPath.exists():
        raise RuntimeError(f"Missing schema dump file: {schemaPath}")
    return schemaPath.read_text(encoding="utf-8")


def _ensureAlembicVersionTable() -> None:
    # ensureAlembicVersionTableExists
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL,
            CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
        )
        """.strip()
    )


def upgrade() -> None:
    # applyInitialSchemaDump
    bind = op.get_bind()

    # forceSearchPathPublicBeforeDump
    bind.exec_driver_sql("SET search_path TO public;")

    schemaSql = _loadSchemaSql()
    bind.exec_driver_sql(schemaSql)

    # forceSearchPathPublicAfterDump
    bind.exec_driver_sql("SET search_path TO public;")

    # recreateVersionTableIfDumpDroppedOrHidIt
    _ensureAlembicVersionTable()


def downgrade() -> None:
    # dropPublicSchemaForFullRollback
    op.execute("DROP SCHEMA IF EXISTS public CASCADE;")
    op.execute("CREATE SCHEMA public;")
