"""Keep the streaming monitor thresholds of each project.

The monitor of a project turns the CTF and drift of each micrograph into alerts
with these thresholds; a project without a row uses the defaults.

Revision ID: 9c4e2a7b1d63
Revises: 4e8b1d2c7a55
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "9c4e2a7b1d63"
down_revision = "4e8b1d2c7a55"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_monitor_settings",
        sa.Column("projectId", sa.Integer(), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("updatedBy", sa.Integer(), nullable=True),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["projectId"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updatedBy"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("projectId"),
    )


def downgrade():
    op.drop_table("project_monitor_settings")
