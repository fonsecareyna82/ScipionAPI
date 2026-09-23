import json
from typing import Any, Dict, List, Optional


class TomogramReviewRevisionConflict(RuntimeError):
    def __init__(self, current: Optional[Dict[str, Any]]):
        super().__init__("Tomogram review revision conflict")
        self.current = current


class TomogramReviewSchemaRevisionConflict(RuntimeError):
    def __init__(self, current: Optional[Dict[str, Any]]):
        super().__init__("Tomogram review schema revision conflict")
        self.current = current


class TomogramReviewTargetNotFound(LookupError):
    pass


class TomogramReviewPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def resolveSetId(
            self,
            projectId: int,
            protocolDbId: int,
            outputName: str,
    ) -> int:
        row = self.db.fetchOne(
            """
            SELECT id
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND "outputName" = %s
            """,
            (
                int(projectId),
                int(protocolDbId),
                str(outputName),
            ),
        )

        if row is None:
            raise TomogramReviewTargetNotFound(
                "Tomogram review Set was not found"
            )

        return int(row["id"])

    def getReviewContext(
            self,
            projectId: int,
            setId: int,
    ) -> Dict[str, Any]:
        progress = self.db.fetchOne(
            """
            SELECT stored_set.id AS "setId",
                   COUNT(item.id)::integer AS total,
                   COUNT(review.id) FILTER (
                       WHERE review.reviewed = TRUE
                   )::integer AS reviewed
              FROM scipion_sets stored_set
         LEFT JOIN scipion_set_items item
                ON item."setId" = stored_set.id
         LEFT JOIN tomogram_reviews review
                ON review."setId" = stored_set.id
               AND review."scipionItemId" = item."scipionItemId"
             WHERE stored_set.id = %s
               AND stored_set."projectId" = %s
          GROUP BY stored_set.id
            """,
            (
                int(setId),
                int(projectId),
            ),
        )

        if progress is None:
            raise TomogramReviewTargetNotFound(
                "Tomogram review Set was not found"
            )

        schema = self.db.fetchOne(
            """
            SELECT id,
                   "setId",
                   version,
                   definition,
                   revision,
                   "createdByUserId",
                   "createdAt",
                   "updatedAt"
              FROM tomogram_review_schemas
             WHERE "setId" = %s
            """,
            (int(setId),),
        )

        reviewRows = self.db.fetchAll(
            """
            SELECT review.id,
                   review."setId",
                   review."scipionItemId",
                   review.reviewed,
                   review.values,
                   review.comment,
                   review."schemaVersion",
                   review.revision,
                   review."reviewedByUserId",
                   review."reviewedAt",
                   review."createdAt",
                   review."updatedAt"
              FROM tomogram_reviews review
              JOIN scipion_set_items item
                ON item."setId" = review."setId"
               AND item."scipionItemId" = review."scipionItemId"
             WHERE review."setId" = %s
          ORDER BY review."scipionItemId"
            """,
            (int(setId),),
        ) or []

        return {
            "setId": int(progress["setId"]),
            "schema": dict(schema) if schema is not None else None,
            "progress": {
                "total": int(progress.get("total") or 0),
                "reviewed": int(progress.get("reviewed") or 0),
            },
            "reviews": {
                str(row["scipionItemId"]): dict(row)
                for row in reviewRows
            },
        }

    def getFilteredScipionItemIds(
            self,
            projectId: int,
            setId: int,
            reviewFilter: str,
            reviewCriteria: Optional[Dict[str, Any]] = None,
    ) -> List[int]:
        reviewFilter = str(reviewFilter or "").strip().lower()

        filterConditions = {
            "all": "",
            "pending": "AND COALESCE(review.reviewed, FALSE) = FALSE",
            "reviewed": "AND COALESCE(review.reviewed, FALSE) = TRUE",
        }

        if reviewFilter not in filterConditions:
            raise ValueError(
                "reviewFilter must be one of: all, pending, reviewed"
            )

        reviewCriteria = reviewCriteria or {}
        qualities = self._normalizedStringList(reviewCriteria.get("qualities"))
        tags = self._normalizedStringList(reviewCriteria.get("tags"))
        minimumTagCounts = self._normalizedMinimumTagCounts(
            reviewCriteria.get("minimumTagCounts")
        )
        advancedConditions = []
        advancedParams = []

        if qualities:
            advancedConditions.append("AND review.values ->> 'quality' = ANY(%s)")
            advancedParams.append(qualities)

        if tags:
            advancedConditions.append(
                "AND COALESCE(review.values -> 'tags', '[]'::jsonb) @> %s::jsonb"
            )
            advancedParams.append(json.dumps(tags))

        for tagKey, minimumCount in minimumTagCounts.items():
            advancedConditions.append(
                """
                AND COALESCE(
                    CASE
                        WHEN jsonb_typeof(review.values -> 'tagCounts' -> %s) = 'number'
                        THEN (review.values -> 'tagCounts' ->> %s)::numeric
                        ELSE NULL
                    END,
                    CASE
                        WHEN COALESCE(review.values -> 'tags', '[]'::jsonb) @> %s::jsonb
                        THEN 1
                        ELSE 0
                    END
                ) >= %s
                """
            )
            advancedParams.extend((tagKey, tagKey, json.dumps([tagKey]), minimumCount))

        advancedWhere = "\n".join(advancedConditions)

        rows = self.db.fetchAll(
            f"""
            SELECT item."scipionItemId"
              FROM scipion_sets stored_set
              JOIN scipion_set_items item
                ON item."setId" = stored_set.id
         LEFT JOIN tomogram_reviews review
                ON review."setId" = stored_set.id
               AND review."scipionItemId" = item."scipionItemId"
             WHERE stored_set.id = %s
               AND stored_set."projectId" = %s
               {filterConditions[reviewFilter]}
               {advancedWhere}
          ORDER BY item."scipionItemId"
            """,
            (
                int(setId),
                int(projectId),
                *advancedParams,
            ),
        ) or []

        return [
            int(row["scipionItemId"])
            for row in rows
        ]

    @staticmethod
    def _normalizedStringList(rawValues) -> List[str]:
        if not isinstance(rawValues, list):
            return []

        normalized = []
        for rawValue in rawValues:
            if not isinstance(rawValue, str):
                continue
            value = rawValue.strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    @staticmethod
    def _normalizedMinimumTagCounts(rawCounts) -> Dict[str, int]:
        if not isinstance(rawCounts, dict):
            return {}

        normalized = {}
        for rawKey, rawCount in rawCounts.items():
            key = rawKey.strip() if isinstance(rawKey, str) else ""
            if not key or isinstance(rawCount, bool):
                continue
            try:
                count = int(rawCount)
            except (TypeError, ValueError):
                continue
            if count > 0:
                normalized[key] = count
        return normalized


    def getSchema(
            self,
            projectId: int,
            setId: int,
    ) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(
            """
            SELECT review_schema.id AS "schemaId",
                   stored_set.id AS "setId",
                   review_schema.version,
                   review_schema.definition,
                   review_schema.revision,
                   review_schema."createdByUserId",
                   review_schema."createdAt",
                   review_schema."updatedAt"
              FROM scipion_sets stored_set
         LEFT JOIN tomogram_review_schemas review_schema
                ON review_schema."setId" = stored_set.id
             WHERE stored_set.id = %s
               AND stored_set."projectId" = %s
            """,
            (
                int(setId),
                int(projectId),
            ),
        )

        if row is None:
            raise TomogramReviewTargetNotFound(
                "Tomogram review Set was not found"
            )

        if row.get("schemaId") is None:
            return None

        row = dict(row)
        row["id"] = row.pop("schemaId")
        return row

    def saveSchema(
            self,
            projectId: int,
            setId: int,
            definition: Dict[str, Any],
            expectedRevision: int,
            createdByUserId: Optional[int] = None,
    ) -> Dict[str, Any]:
        expectedRevision = int(expectedRevision)

        if expectedRevision < 0:
            raise ValueError("expectedRevision must be greater than or equal to zero")

        if not isinstance(definition, dict):
            raise ValueError("Tomogram review schema definition must be a dictionary")

        with self.db.transaction():
            if expectedRevision == 0:
                stored = self._insertSchema(
                    projectId=projectId,
                    setId=setId,
                    definition=definition,
                    createdByUserId=createdByUserId,
                )
            else:
                stored = self._updateSchema(
                    projectId=projectId,
                    setId=setId,
                    definition=definition,
                    expectedRevision=expectedRevision,
                )

            if stored is not None:
                return dict(stored)

            current = self.getSchema(
                projectId=projectId,
                setId=setId,
            )

            raise TomogramReviewSchemaRevisionConflict(
                current=current
            )

    def _insertSchema(
            self,
            projectId: int,
            setId: int,
            definition: Dict[str, Any],
            createdByUserId: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        return self.db.executeReturningOne(
            """
            INSERT INTO tomogram_review_schemas (
                "setId",
                version,
                definition,
                revision,
                "createdByUserId",
                "updatedAt"
            )
            SELECT stored_set.id,
                   1,
                   %s::jsonb,
                   1,
                   %s,
                   NOW()
              FROM scipion_sets stored_set
             WHERE stored_set.id = %s
               AND stored_set."projectId" = %s
            ON CONFLICT ON CONSTRAINT ux_tomogram_review_schemas_set
            DO NOTHING
            RETURNING id,
                      "setId",
                      version,
                      definition,
                      revision,
                      "createdByUserId",
                      "createdAt",
                      "updatedAt"
            """,
            (
                json.dumps(definition),
                createdByUserId,
                int(setId),
                int(projectId),
            ),
        )

    def _updateSchema(
            self,
            projectId: int,
            setId: int,
            definition: Dict[str, Any],
            expectedRevision: int,
    ) -> Optional[Dict[str, Any]]:
        return self.db.executeReturningOne(
            """
            UPDATE tomogram_review_schemas review_schema
               SET version = review_schema.version + 1,
                   definition = %s::jsonb,
                   revision = review_schema.revision + 1,
                   "updatedAt" = NOW()
              FROM scipion_sets stored_set
             WHERE review_schema."setId" = stored_set.id
               AND review_schema."setId" = %s
               AND review_schema.revision = %s
               AND stored_set."projectId" = %s
            RETURNING review_schema.id,
                      review_schema."setId",
                      review_schema.version,
                      review_schema.definition,
                      review_schema.revision,
                      review_schema."createdByUserId",
                      review_schema."createdAt",
                      review_schema."updatedAt"
            """,
            (
                json.dumps(definition),
                int(setId),
                int(expectedRevision),
                int(projectId),
            ),
        )

    def getReview(
            self,
            projectId: int,
            setId: int,
            scipionItemId: int,
    ) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(
            """
            SELECT review.id AS "reviewId",
                   review."setId",
                   review."scipionItemId",
                   review.reviewed,
                   review.values,
                   review.comment,
                   review."schemaVersion",
                   review.revision,
                   review."reviewedByUserId",
                   review."reviewedAt",
                   review."createdAt",
                   review."updatedAt"
              FROM scipion_sets stored_set
              JOIN scipion_set_items item
                ON item."setId" = stored_set.id
               AND item."scipionItemId" = %s
         LEFT JOIN tomogram_reviews review
                ON review."setId" = stored_set.id
               AND review."scipionItemId" = item."scipionItemId"
             WHERE stored_set.id = %s
               AND stored_set."projectId" = %s
            """,
            (
                int(scipionItemId),
                int(setId),
                int(projectId),
            ),
        )

        if row is None:
            raise TomogramReviewTargetNotFound(
                "Tomogram review target was not found"
            )

        if row.get("reviewId") is None:
            return None

        row = dict(row)
        row["id"] = row.pop("reviewId")
        return row

    def saveReview(
            self,
            projectId: int,
            setId: int,
            scipionItemId: int,
            reviewed: bool,
            values: Dict[str, Any],
            comment: Optional[str],
            expectedRevision: int,
            reviewedByUserId: Optional[int] = None,
    ) -> Dict[str, Any]:
        expectedRevision = int(expectedRevision)

        if expectedRevision < 0:
            raise ValueError("expectedRevision must be greater than or equal to zero")

        if not isinstance(values, dict):
            raise ValueError("Tomogram review values must be a dictionary")

        with self.db.transaction():
            if expectedRevision == 0:
                stored = self._insertReview(
                    projectId=projectId,
                    setId=setId,
                    scipionItemId=scipionItemId,
                    reviewed=reviewed,
                    values=values,
                    comment=comment,
                    reviewedByUserId=reviewedByUserId,
                )
            else:
                stored = self._updateReview(
                    projectId=projectId,
                    setId=setId,
                    scipionItemId=scipionItemId,
                    reviewed=reviewed,
                    values=values,
                    comment=comment,
                    expectedRevision=expectedRevision,
                    reviewedByUserId=reviewedByUserId,
                )

            if stored is not None:
                return dict(stored)

            current = self.getReview(
                projectId=projectId,
                setId=setId,
                scipionItemId=scipionItemId,
            )

            raise TomogramReviewRevisionConflict(
                current=current
            )

    def _insertReview(
            self,
            projectId: int,
            setId: int,
            scipionItemId: int,
            reviewed: bool,
            values: Dict[str, Any],
            comment: Optional[str],
            reviewedByUserId: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        return self.db.executeReturningOne(
            """
            INSERT INTO tomogram_reviews (
                "setId",
                "scipionItemId",
                reviewed,
                values,
                comment,
                "schemaVersion",
                revision,
                "reviewedByUserId",
                "reviewedAt",
                "updatedAt"
            )
            SELECT stored_set.id,
                   item."scipionItemId",
                   %s,
                   %s::jsonb,
                   %s,
                   COALESCE(review_schema.version, 1),
                   1,
                   %s,
                   CASE WHEN %s THEN NOW() ELSE NULL END,
                   NOW()
              FROM scipion_sets stored_set
              JOIN scipion_set_items item
                ON item."setId" = stored_set.id
               AND item."scipionItemId" = %s
         LEFT JOIN tomogram_review_schemas review_schema
                ON review_schema."setId" = stored_set.id
             WHERE stored_set.id = %s
               AND stored_set."projectId" = %s
            ON CONFLICT ON CONSTRAINT ux_tomogram_reviews_set_item
            DO NOTHING
            RETURNING id,
                      "setId",
                      "scipionItemId",
                      reviewed,
                      values,
                      comment,
                      "schemaVersion",
                      revision,
                      "reviewedByUserId",
                      "reviewedAt",
                      "createdAt",
                      "updatedAt"
            """,
            (
                bool(reviewed),
                json.dumps(values),
                comment,
                reviewedByUserId,
                bool(reviewed),
                int(scipionItemId),
                int(setId),
                int(projectId),
            ),
        )

    def _updateReview(
            self,
            projectId: int,
            setId: int,
            scipionItemId: int,
            reviewed: bool,
            values: Dict[str, Any],
            comment: Optional[str],
            expectedRevision: int,
            reviewedByUserId: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        return self.db.executeReturningOne(
            """
            UPDATE tomogram_reviews review
               SET reviewed = %s,
                   values = %s::jsonb,
                   comment = %s,
                   "schemaVersion" = COALESCE(review_schema.version, review."schemaVersion"),
                   revision = review.revision + 1,
                   "reviewedByUserId" = %s,
                   "reviewedAt" = CASE WHEN %s THEN NOW() ELSE NULL END,
                   "updatedAt" = NOW()
              FROM scipion_sets stored_set
         LEFT JOIN tomogram_review_schemas review_schema
                ON review_schema."setId" = stored_set.id
             WHERE review."setId" = stored_set.id
               AND review."setId" = %s
               AND review."scipionItemId" = %s
               AND review.revision = %s
               AND stored_set."projectId" = %s
               AND EXISTS (
                   SELECT 1
                     FROM scipion_set_items item
                    WHERE item."setId" = stored_set.id
                      AND item."scipionItemId" = review."scipionItemId"
               )
            RETURNING review.id,
                      review."setId",
                      review."scipionItemId",
                      review.reviewed,
                      review.values,
                      review.comment,
                      review."schemaVersion",
                      review.revision,
                      review."reviewedByUserId",
                      review."reviewedAt",
                      review."createdAt",
                      review."updatedAt"
            """,
            (
                bool(reviewed),
                json.dumps(values),
                comment,
                reviewedByUserId,
                bool(reviewed),
                int(setId),
                int(scipionItemId),
                expectedRevision,
                int(projectId),
            ),
        )
