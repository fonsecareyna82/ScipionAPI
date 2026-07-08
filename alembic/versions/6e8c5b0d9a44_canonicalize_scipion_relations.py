
"""canonicalize scipion relations

Revision ID: 6e8c5b0d9a44
Revises: 2fc2cd4da2e2
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = "6e8c5b0d9a44"
down_revision: Union[str, None] = "2fc2cd4da2e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Canonical relation table is scipion_object_relations.

    scipion_relations was an old initTables-only table using legacy object ids.
    If present, migrate mappable rows to scipion_object_relations and keep the
    old table renamed as scipion_relations_legacy for safety.
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.scipion_relations') IS NOT NULL THEN

                INSERT INTO public.scipion_object_relations (
                    "projectId",
                    "creatorObjectId",
                    "parentObjectId",
                    "childObjectId",
                    name,
                    "parentExtended",
                    "childExtended",
                    metadata,
                    "createdAt"
                )
                SELECT
                    legacy."projectId",
                    creator_object.id,
                    parent_object.id,
                    child_object.id,
                    legacy.name,
                    NULLIF(legacy."parentExtended", ''),
                    NULLIF(legacy."childExtended", ''),
                    jsonb_build_object(
                        'migratedFrom', 'scipion_relations',
                        'legacyRelationId', legacy.id,
                        'legacyCreatorObjId', legacy."creatorObjId",
                        'legacyParentObjId', legacy."parentObjId",
                        'legacyChildObjId', legacy."childObjId"
                    ),
                    legacy."createdAt"
                FROM public.scipion_relations legacy
                JOIN LATERAL (
                    SELECT o.id
                      FROM public.scipion_objects o
                     WHERE o."projectId" = legacy."projectId"
                       AND (
                            o.id = legacy."creatorObjId"
                            OR o."scipionObjId" = legacy."creatorObjId"
                       )
                     ORDER BY
                       CASE WHEN o.id = legacy."creatorObjId" THEN 0 ELSE 1 END,
                       o.id
                     LIMIT 1
                ) creator_object ON TRUE
                JOIN LATERAL (
                    SELECT o.id
                      FROM public.scipion_objects o
                     WHERE o."projectId" = legacy."projectId"
                       AND (
                            o.id = legacy."parentObjId"
                            OR o."scipionObjId" = legacy."parentObjId"
                       )
                     ORDER BY
                       CASE WHEN o.id = legacy."parentObjId" THEN 0 ELSE 1 END,
                       o.id
                     LIMIT 1
                ) parent_object ON TRUE
                JOIN LATERAL (
                    SELECT o.id
                      FROM public.scipion_objects o
                     WHERE o."projectId" = legacy."projectId"
                       AND (
                            o.id = legacy."childObjId"
                            OR o."scipionObjId" = legacy."childObjId"
                       )
                     ORDER BY
                       CASE WHEN o.id = legacy."childObjId" THEN 0 ELSE 1 END,
                       o.id
                     LIMIT 1
                ) child_object ON TRUE
                WHERE NOT EXISTS (
                    SELECT 1
                      FROM public.scipion_object_relations existing
                     WHERE existing."projectId" = legacy."projectId"
                       AND existing.name = legacy.name
                       AND existing."parentObjectId" = parent_object.id
                       AND existing."childObjectId" = child_object.id
                       AND COALESCE(existing."parentExtended", '') = COALESCE(legacy."parentExtended", '')
                       AND COALESCE(existing."childExtended", '') = COALESCE(legacy."childExtended", '')
                );

                IF to_regclass('public.scipion_relations_legacy') IS NULL THEN
                    ALTER TABLE public.scipion_relations RENAME TO scipion_relations_legacy;
                ELSE
                    DROP TABLE public.scipion_relations;
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.scipion_relations') IS NULL
               AND to_regclass('public.scipion_relations_legacy') IS NOT NULL THEN
                ALTER TABLE public.scipion_relations_legacy RENAME TO scipion_relations;
            END IF;
        END $$;
        """
    )