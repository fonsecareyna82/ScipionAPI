"""add protocol dependencies table

Revision ID: 9b7b3c4d8e21
Revises: f3f7b0a3f1aa
Create Date: 2026-04-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b7b3c4d8e21'
down_revision: Union[str, None] = 'f3f7b0a3f1aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_unique_constraint(
        'uq_protocols_projectId_id',
        'protocols',
        ['projectId', 'id'],
    )

    op.create_table(
        'protocol_dependencies',
        sa.Column('projectId', sa.Integer(), nullable=False),
        sa.Column('parentProtocolDbId', sa.Integer(), nullable=False),
        sa.Column('childProtocolDbId', sa.Integer(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('"parentProtocolDbId" <> "childProtocolDbId"', name='protocol_dependencies_no_self_loop'),
        sa.ForeignKeyConstraint(['projectId'], ['projects.id'], name='protocol_dependencies_projectId_fkey', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['projectId', 'parentProtocolDbId'],
            ['protocols.projectId', 'protocols.id'],
            name='protocol_dependencies_parentProtocolDbId_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['projectId', 'childProtocolDbId'],
            ['protocols.projectId', 'protocols.id'],
            name='protocol_dependencies_childProtocolDbId_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('projectId', 'parentProtocolDbId', 'childProtocolDbId', name='protocol_dependencies_pkey'),
    )

    op.create_index(
        'idx_protocol_dependencies_parent',
        'protocol_dependencies',
        ['projectId', 'parentProtocolDbId'],
        unique=False,
    )
    op.create_index(
        'idx_protocol_dependencies_child',
        'protocol_dependencies',
        ['projectId', 'childProtocolDbId'],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO protocol_dependencies (
            "projectId",
            "parentProtocolDbId",
            "childProtocolDbId"
        )
        SELECT DISTINCT
            child."projectId",
            parent.id,
            child.id
        FROM protocols child
        CROSS JOIN LATERAL unnest(COALESCE(child."parentIds", ARRAY[]::integer[])) AS parent_protocol_id
        JOIN protocols parent
          ON parent."projectId" = child."projectId"
         AND parent."protocolId" = parent_protocol_id::text
        WHERE parent.id <> child.id
        """
    )


def downgrade():
    op.drop_index('idx_protocol_dependencies_child', table_name='protocol_dependencies')
    op.drop_index('idx_protocol_dependencies_parent', table_name='protocol_dependencies')
    op.drop_table('protocol_dependencies')
    op.drop_constraint('uq_protocols_projectId_id', 'protocols', type_='unique')
