"""normalize protocol input ref object ids

Revision ID: 0d02314012e3
Revises: d7c68b46162e
Create Date: 2026-07-14 11:35:49.682230

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d02314012e3'
down_revision: Union[str, None] = 'd7c68b46162e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH persisted_outputs AS (
            SELECT
                s."projectId",
                s."protocolDbId",
                s."outputName",
                o."scipionObjId"::text AS "runtimeObjectId"
              FROM scipion_sets s
              JOIN scipion_objects o
                ON o."projectId" = s."projectId"
               AND o.id = s."objectId"
             WHERE o."scipionObjId" IS NOT NULL

            UNION ALL

            SELECT
                o."projectId",
                o."protocolDbId",
                COALESCE(NULLIF(o.path, ''), o.name) AS "outputName",
                o."scipionObjId"::text AS "runtimeObjectId"
              FROM scipion_objects o
             WHERE o."parentObjectId" IS NULL
               AND o."scipionObjId" IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM scipion_sets s
                     WHERE s."projectId" = o."projectId"
                       AND s."objectId" = o.id
               )
        )
        UPDATE protocol_input_refs ref
           SET "objectId" = output."runtimeObjectId",
               "updatedAt" = NOW()
          FROM persisted_outputs output
         WHERE ref."projectId" = output."projectId"
           AND ref."parentProtocolDbId" = output."protocolDbId"
           AND ref."parentOutputName" = output."outputName"
           AND ref."objectId"
               IS DISTINCT FROM output."runtimeObjectId";
        """
    )


def downgrade() -> None:
    pass
