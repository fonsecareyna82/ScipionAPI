
"""backfill scipion object relations from runtime relations

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
    Backfill canonical object relations from runtime mapper relations.

    scipion_relations is still used by the Mapper-compatible relations API and
    stores Scipion runtime object ids. scipion_object_relations stores canonical
    PostgreSQL object row ids. This migration copies mappable legacy/runtime
    rows into scipion_object_relations without deleting or renaming
    scipion_relations.
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
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM public.scipion_object_relations
         WHERE metadata ->> 'migratedFrom' = 'scipion_relations';
        """
    )