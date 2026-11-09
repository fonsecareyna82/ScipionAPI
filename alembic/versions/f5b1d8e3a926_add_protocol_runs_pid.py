"""The process that runs each protocol, so what is on a machine's GPUs can be told whose it is.

pid is the worker process that ran the protocol on its host; the programs it starts descend from it. Together with
host it ties a process seen on a GPU to its run.

Revision ID: f5b1d8e3a926
Revises: e2a9c4f7b318
"""
from alembic import op


revision = "f5b1d8e3a926"
down_revision = "e2a9c4f7b318"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE protocol_runs ADD COLUMN pid INTEGER')


def downgrade():
    op.execute('ALTER TABLE protocol_runs DROP COLUMN pid')
