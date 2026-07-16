# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
import json
from typing import Any, Dict, List, Optional


class ProtocolGraphRepository:
    """
    Persist PostgreSQL runtime protocol graph data.

    This repository owns:
      - protocol_dependencies
      - protocol_input_refs
      - scipion_object_relations for runtime output relations
      - protocols.parentIds
    """

    @staticmethod
    def _rowsToDicts(rows) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in rows or []
        ]

    @staticmethod
    def _extractRuntimeScipionObjId(outputRow: Dict[str, Any]):
        if not outputRow:
            return None

        value = outputRow.get("runtimeObjectId")

        if value not in (None, ""):
            try:
                return int(value)
            except Exception:
                pass

        properties = outputRow.get("properties") or {}

        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except Exception:
                properties = {}

        if not isinstance(properties, dict):
            return None

        for key in ("scipionObjId", "_objId", "objId"):
            value = properties.get(key)

            if value in (None, ""):
                continue

            try:
                return int(value)
            except Exception:
                continue

        return None

    def getPersistedSetOutputRow(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            outputName: str,
    ) -> Optional[Dict[str, Any]]:
        row = mapper.db.fetchOne(
            """
            SELECT
                s.id AS "setId",
                s."projectId",
                s."protocolDbId",
                p."protocolId",
                s."objectId",
                o."scipionObjId" AS "runtimeObjectId",
                s."outputName",
                s."setClassName" AS "className",
                s."itemClassName",
                s.properties
              FROM scipion_sets s
              JOIN protocols p
                ON p."projectId" = s."projectId"
               AND p.id = s."protocolDbId"
         LEFT JOIN scipion_objects o
                ON o."projectId" = s."projectId"
               AND o.id = s."objectId"
             WHERE s."projectId" = %s
               AND s."protocolDbId" = %s
               AND s."outputName" = %s
             LIMIT 1
            """,
            (
                int(projectId),
                int(protocolDbId),
                outputName,
            ),
        )

        return dict(row) if row else None

    def getPersistedSetOutputRowByRuntimeObjectId(
            self,
            mapper,
            projectId: int,
            runtimeObjectId: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve one persisted PostgreSQL set using the Scipion runtime
        object id stored in scipion_objects.scipionObjId.

        runtimeObjectId must never be compared directly with
        scipion_sets.objectId, because that column contains the canonical
        scipion_objects primary key.
        """
        if mapper is None:
            raise ValueError(
                "mapper is required"
            )

        db = getattr(
            mapper,
            "db",
            None,
        )

        if db is None:
            raise ValueError(
                "mapper.db is required"
            )

        if projectId in (
                None,
                "",
        ):
            raise ValueError(
                "projectId is required"
            )

        if runtimeObjectId in (
                None,
                "",
        ):
            raise ValueError(
                "runtimeObjectId is required"
            )

        rows = db.fetchAll(
            """
            SELECT
                s.id AS "setId",
                s."projectId",
                s."protocolDbId",
                p."protocolId",
                s."objectId",
                o."scipionObjId" AS "runtimeObjectId",
                s."outputName",
                s."setClassName" AS "className",
                s."itemClassName",
                s.properties
              FROM scipion_sets s
              JOIN protocols p
                ON p."projectId" = s."projectId"
               AND p.id = s."protocolDbId"
              JOIN scipion_objects o
                ON o."projectId" = s."projectId"
               AND o.id = s."objectId"
             WHERE s."projectId" = %s
               AND o."scipionObjId" = %s
             ORDER BY s.id ASC
             LIMIT 2
            """,
            (
                int(projectId),
                int(runtimeObjectId),
            ),
        )

        rows = [
            dict(row)
            for row in rows or []
        ]

        if not rows:
            return None

        if len(rows) > 1:
            raise ValueError(
                "More than one PostgreSQL set was found "
                "for project %s and runtime object %s"
                % (
                    projectId,
                    runtimeObjectId,
                )
            )

        return rows[0]

    def listPersistedSetOutputRows(
            self,
            mapper,
            projectId: int,
            className: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List PostgreSQL-backed Scipion set outputs that expose a usable
        Scipion runtime object id.

        className applies an exact stored set class filter. Subclass
        expansion belongs to the runtime mapper, where the Scipion class
        registry is available.
        """
        if mapper is None:
            raise ValueError(
                "mapper is required"
            )

        db = getattr(
            mapper,
            "db",
            None,
        )

        if db is None:
            raise ValueError(
                "mapper.db is required"
            )

        if projectId in (
                None,
                "",
        ):
            raise ValueError(
                "projectId is required"
            )

        classNameText = str(
            className or ""
        ).strip()

        query = """
            SELECT
                s.id AS "setId",
                s."projectId",
                s."protocolDbId",
                p."protocolId",
                s."objectId",
                o."scipionObjId" AS "runtimeObjectId",
                s."outputName",
                s."setClassName" AS "className",
                s."itemClassName",
                s.properties
              FROM scipion_sets s
              JOIN protocols p
                ON p."projectId" = s."projectId"
               AND p.id = s."protocolDbId"
              JOIN scipion_objects o
                ON o."projectId" = s."projectId"
               AND o.id = s."objectId"
             WHERE s."projectId" = %s
               AND o."scipionObjId" IS NOT NULL
        """

        params = [
            int(projectId),
        ]

        if classNameText:
            query += """
               AND s."setClassName" = %s
            """

            params.append(
                classNameText
            )

        query += """
             ORDER BY
                s."protocolDbId" ASC,
                s."outputName" ASC,
                s.id ASC
        """

        rows = self._rowsToDicts(
            db.fetchAll(
                query,
                tuple(params),
            )
        )

        result = []
        runtimeObjectIds = set()

        for row in rows:
            runtimeObjectId = (
                self._extractRuntimeScipionObjId(
                    row
                )
            )

            if runtimeObjectId is None:
                continue

            runtimeObjectId = int(
                runtimeObjectId
            )

            if runtimeObjectId in runtimeObjectIds:
                raise ValueError(
                    "More than one PostgreSQL set was found "
                    "for project %s and runtime object %s"
                    % (
                        projectId,
                        runtimeObjectId,
                    )
                )

            runtimeObjectIds.add(
                runtimeObjectId
            )

            normalizedRow = dict(
                row
            )

            normalizedRow[
                "runtimeObjectId"
            ] = runtimeObjectId

            result.append(
                normalizedRow
            )

        return result

    def replaceRuntimeOutputRelation(
            self,
            mapper,
            projectId: int,
            sourceProtocolDbId: int,
            sourceOutputName: str,
            relationName: str,
            targetProtocolDbId: int,
            targetOutputName: str,
            metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sourceOutput = self.getPersistedSetOutputRow(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=sourceProtocolDbId,
            outputName=sourceOutputName,
        )

        if not sourceOutput or sourceOutput.get("objectId") in (None, ""):
            return {
                "saved": False,
                "reason": "source_output_not_found",
                "relationName": relationName,
                "sourceProtocolDbId": sourceProtocolDbId,
                "sourceOutputName": sourceOutputName,
            }

        targetOutput = self.getPersistedSetOutputRow(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=targetProtocolDbId,
            outputName=targetOutputName,
        )

        if not targetOutput or targetOutput.get("objectId") in (None, ""):
            return {
                "saved": False,
                "reason": "target_output_not_found",
                "relationName": relationName,
                "sourceProtocolDbId": sourceProtocolDbId,
                "sourceOutputName": sourceOutputName,
                "targetProtocolDbId": targetProtocolDbId,
                "targetOutputName": targetOutputName,
            }

        sourceRuntimeObjectId = self._extractRuntimeScipionObjId(sourceOutput)
        targetRuntimeObjectId = self._extractRuntimeScipionObjId(targetOutput)

        metadata = dict(metadata or {})
        metadata.update({
            "sourceProtocolDbId": int(sourceProtocolDbId),
            "sourceProtocolId": str(sourceOutput.get("protocolId")),
            "sourceOutputName": sourceOutputName,
            "sourceClassName": sourceOutput.get("className"),
            "targetProtocolDbId": int(targetProtocolDbId),
            "targetProtocolId": str(targetOutput.get("protocolId")),
            "targetOutputName": targetOutputName,
            "targetClassName": targetOutput.get("className"),
            "relationScope": "runtime_output",
        })

        with mapper.db.transaction():
            mapper.db.execute(
                """
                DELETE FROM scipion_object_relations
                 WHERE "projectId" = %s
                   AND "parentObjectId" = %s
                   AND name = %s
                   AND COALESCE("parentExtended", '') = %s
                """,
                (
                    int(projectId),
                    int(sourceOutput["objectId"]),
                    relationName,
                    sourceOutputName,
                ),
                commit=False,
            )

            if sourceRuntimeObjectId is not None and targetRuntimeObjectId is not None:
                mapper.db.execute(
                    """
                    DELETE FROM scipion_relations
                     WHERE "projectId" = %s
                       AND "parentObjId" = %s
                       AND name = %s
                       AND COALESCE("parentExtended", '') = %s
                    """,
                    (
                        int(projectId),
                        int(sourceRuntimeObjectId),
                        relationName,
                        sourceOutputName,
                    ),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    INSERT INTO scipion_relations (
                        "projectId",
                        name,
                        "creatorObjId",
                        "parentObjId",
                        "childObjId",
                        "parentExtended",
                        "childExtended"
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        int(projectId),
                        relationName,
                        int(sourceRuntimeObjectId),
                        int(sourceRuntimeObjectId),
                        int(targetRuntimeObjectId),
                        sourceOutputName,
                        targetOutputName,
                    ),
                    commit=False,
                )

            mapper.db.execute(
                """
                INSERT INTO scipion_object_relations (
                    "projectId",
                    "creatorObjectId",
                    "parentObjectId",
                    "childObjectId",
                    name,
                    "parentExtended",
                    "childExtended",
                    metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    int(projectId),
                    int(sourceOutput["objectId"]),
                    int(sourceOutput["objectId"]),
                    int(targetOutput["objectId"]),
                    relationName,
                    sourceOutputName,
                    targetOutputName,
                    json.dumps(metadata),
                ),
                commit=False,
            )

            fallbackRelationSaved = False
            fallbackRelationError = None

            if sourceRuntimeObjectId is not None and targetRuntimeObjectId is not None:
                fallbackMapper = getattr(mapper, "writeFallbackMapper", None)
                insertRelationData = getattr(fallbackMapper, "insertRelationData", None)

                if callable(insertRelationData):
                    try:
                        insertRelationData(
                            relationName,
                            int(sourceRuntimeObjectId),
                            int(sourceRuntimeObjectId),
                            int(targetRuntimeObjectId),
                            sourceOutputName,
                            targetOutputName,
                        )

                        commit = getattr(fallbackMapper, "commit", None)
                        if callable(commit):
                            commit()

                        fallbackRelationSaved = True

                    except Exception as e:
                        fallbackRelationError = str(e)

        return {
            "saved": True,
            "relationName": relationName,
            "sourceProtocolDbId": int(sourceProtocolDbId),
            "sourceOutputName": sourceOutputName,
            "sourceObjectId": int(sourceOutput["objectId"]),
            "sourceRuntimeObjectId": sourceRuntimeObjectId,
            "targetProtocolDbId": int(targetProtocolDbId),
            "targetOutputName": targetOutputName,
            "targetObjectId": int(targetOutput["objectId"]),
            "targetRuntimeObjectId": targetRuntimeObjectId,
            "legacyRelationSaved": sourceRuntimeObjectId is not None and targetRuntimeObjectId is not None,
            "fallbackRelationSaved": fallbackRelationSaved,
            "fallbackRelationError": fallbackRelationError,
        }

    def loadRuntimeOutputRelations(
            self,
            mapper,
            projectId: int,
            sourceProtocolDbId: int,
            sourceOutputName: str,
    ) -> List[Dict[str, Any]]:
        rows = mapper.db.fetchAll(
            """
            SELECT
                r.id AS "relationId",
                r.name AS "relationName",
                r."parentExtended" AS "sourceOutputName",
                r."childExtended" AS "targetOutputName",
                r.metadata,
                source_set.id AS "sourceSetId",
                source_set."protocolDbId" AS "sourceProtocolDbId",
                source_protocol."protocolId" AS "sourceProtocolId",
                source_set."setClassName" AS "sourceClassName",
                source_set."itemClassName" AS "sourceItemClassName",
                target_set.id AS "targetSetId",
                target_set."protocolDbId" AS "targetProtocolDbId",
                target_protocol."protocolId" AS "targetProtocolId",
                target_set."setClassName" AS "targetClassName",
                target_set."itemClassName" AS "targetItemClassName"
              FROM scipion_sets source_set
              JOIN scipion_object_relations r
                ON r."projectId" = source_set."projectId"
               AND r."parentObjectId" = source_set."objectId"
              JOIN scipion_sets target_set
                ON target_set."projectId" = r."projectId"
               AND target_set."objectId" = r."childObjectId"
              JOIN protocols source_protocol
                ON source_protocol."projectId" = source_set."projectId"
               AND source_protocol.id = source_set."protocolDbId"
              JOIN protocols target_protocol
                ON target_protocol."projectId" = target_set."projectId"
               AND target_protocol.id = target_set."protocolDbId"
             WHERE source_set."projectId" = %s
               AND source_set."protocolDbId" = %s
               AND source_set."outputName" = %s
             ORDER BY r.id ASC
            """,
            (
                int(projectId),
                int(sourceProtocolDbId),
                sourceOutputName,
            ),
        )

        result = []

        for row in rows or []:
            item = dict(row)
            metadata = item.get("metadata") or {}

            if not isinstance(metadata, dict):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}

            item["metadata"] = metadata
            result.append(item)

        return result

    def getPersistedOutputInfoForInputRef(
            self,
            mapper,
            projectId: int,
            parentProtocolDbId: int,
            outputName: str,
    ) -> Dict[str, Any]:
        """
        Return the Scipion runtime identity associated with a persisted output.

        protocol_input_refs.objectId stores the Scipion runtime object id,
        not the canonical scipion_objects.id primary key.
        """
        row = mapper.db.fetchOne(
            """
            SELECT
                o."scipionObjId"::text AS "runtimeObjectId",
                s."setClassName" AS "className"
              FROM scipion_sets s
         LEFT JOIN scipion_objects o
                ON o."projectId" = s."projectId"
               AND o.id = s."objectId"
             WHERE s."projectId" = %s
               AND s."protocolDbId" = %s
               AND s."outputName" = %s

            UNION ALL

            SELECT
                o."scipionObjId"::text AS "runtimeObjectId",
                o."className" AS "className"
              FROM scipion_objects o
             WHERE o."projectId" = %s
               AND o."protocolDbId" = %s
               AND o."parentObjectId" IS NULL
               AND (o.path = %s OR o.name = %s)

             LIMIT 1
            """,
            (
                projectId,
                parentProtocolDbId,
                outputName,
                projectId,
                parentProtocolDbId,
                outputName,
                outputName,
            ),
        )

        if not row:
            return {
                "runtimeObjectId": None,
                "className": None,
            }

        return {
            "runtimeObjectId": row.get("runtimeObjectId"),
            "className": row.get("className"),
        }

    def getPostgresqlRuntimeOutputInfo(
            self,
            mapper,
            projectId: int,
            parentProtocolDbId: int,
            outputName: str,
    ) -> Dict[str, Any]:
        """
        Resolve a persisted parent output from PostgreSQL.

        This is used by runtime input resolution so child protocols do not depend
        exclusively on the parent runtime db exposing the output as a live attribute.
        """
        row = mapper.db.fetchOne(
            """
            SELECT
                'set' AS kind,
                s.id AS "setId",
                s."objectId"::text AS "objectId",
                o."scipionObjId"::text AS "runtimeObjectId",
                s."outputName" AS "outputName",
                s."setClassName" AS "className",
                s."itemClassName" AS "itemClassName",
                s.properties AS properties
              FROM scipion_sets s
         LEFT JOIN scipion_objects o
                ON o."projectId" = s."projectId"
               AND o.id = s."objectId"
             WHERE s."projectId" = %s
               AND s."protocolDbId" = %s
               AND s."outputName" = %s

            UNION ALL

            SELECT
                'object' AS kind,
                NULL AS "setId",
                o.id::text AS "objectId",
                o."scipionObjId"::text AS "runtimeObjectId",
                o.name AS "outputName",
                o."className" AS "className",
                NULL AS "itemClassName",
                o.metadata AS properties
              FROM scipion_objects o
             WHERE o."projectId" = %s
               AND o."protocolDbId" = %s
               AND o."parentObjectId" IS NULL
               AND (o.path = %s OR o.name = %s)

             LIMIT 1
            """,
            (
                projectId,
                parentProtocolDbId,
                outputName,
                projectId,
                parentProtocolDbId,
                outputName,
                outputName,
            ),
        )

        if not row:
            return {
                "exists": False,
                "kind": None,
                "setId": None,
                "objectId": None,
                "runtimeObjectId": None,
                "outputName": outputName,
                "className": None,
                "itemClassName": None,
                "properties": {},
                "itemsCount": None,
                "tablesCount": None,
                "tableItemsCount": None,
            }

        info = dict(row)
        properties = info.get("properties") or {}

        if not isinstance(properties, dict):
            try:
                properties = json.loads(properties)
            except Exception:
                properties = {}

        info["properties"] = properties
        info["exists"] = True

        setId = info.get("setId")

        itemsCount = None
        tablesCount = None
        tableItemsCount = None

        if setId is not None:
            try:
                countRow = mapper.db.fetchOne(
                    """
                    SELECT COUNT(*) AS count
                      FROM scipion_set_items
                     WHERE "setId" = %s
                    """,
                    (int(setId),),
                )
                itemsCount = int(countRow.get("count") or 0) if countRow else 0
            except Exception:
                itemsCount = None

            try:
                countRow = mapper.db.fetchOne(
                    """
                    SELECT COUNT(*) AS count
                      FROM scipion_set_tables
                     WHERE "setId" = %s
                    """,
                    (int(setId),),
                )
                tablesCount = int(countRow.get("count") or 0) if countRow else 0
            except Exception:
                tablesCount = None

            try:
                countRow = mapper.db.fetchOne(
                    """
                    SELECT COUNT(ti.id) AS count
                      FROM scipion_set_tables t
                      JOIN scipion_set_table_items ti
                        ON ti."tableId" = t.id
                     WHERE t."setId" = %s
                    """,
                    (int(setId),),
                )
                tableItemsCount = int(countRow.get("count") or 0) if countRow else 0
            except Exception:
                tableItemsCount = None

        if itemsCount is None:
            try:
                itemsCount = int(
                    properties.get("itemsCount")
                    or properties.get("_size")
                    or 0
                )
            except Exception:
                itemsCount = None

        info["itemsCount"] = itemsCount
        info["tablesCount"] = tablesCount
        info["tableItemsCount"] = tableItemsCount

        return info

    def loadSelfInputRefs(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> List[Dict[str, Any]]:
        rows = mapper.db.fetchAll(
            """
            SELECT
                r."inputName",
                r."parentOutputName",
                r."parentProtocolDbId"
              FROM protocol_input_refs r
             WHERE r."projectId" = %s
               AND r."protocolDbId" = %s
               AND r."parentProtocolDbId" = r."protocolDbId"
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        )

        return self._rowsToDicts(rows)

    def loadInputRefsForProtocol(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> List[Dict[str, Any]]:
        rows = mapper.db.fetchAll(
            """
            SELECT
                "inputName",
                "itemIndex",
                "parentProtocolDbId",
                "parentProtocolId",
                "parentOutputName",
                "objectClassName",
                "objectId"
              FROM protocol_input_refs
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "inputName", "itemIndex"
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        )

        return self._rowsToDicts(rows)

    def loadSubworkflowRows(
            self,
            mapper,
            projectId: int,
            rootProtocolDbId: int,
    ) -> List[Dict[str, Any]]:
        rows = mapper.db.fetchAll(
            """
            WITH RECURSIVE subworkflow("protocolDbId", "level", path) AS (
                SELECT
                    p.id,
                    0,
                    ARRAY[p.id]
                  FROM protocols p
                 WHERE p."projectId" = %s
                   AND p.id = %s

                UNION ALL

                SELECT
                    d."childProtocolDbId",
                    sw."level" + 1,
                    sw.path || d."childProtocolDbId"
                  FROM subworkflow sw
                  JOIN protocol_dependencies d
                    ON d."projectId" = %s
                   AND d."parentProtocolDbId" = sw."protocolDbId"
                 WHERE NOT d."childProtocolDbId" = ANY(sw.path)
            )
            SELECT
                p.id AS "protocolDbId",
                p."protocolId" AS "protocolId",
                MIN(sw."level") AS "level"
              FROM subworkflow sw
              JOIN protocols p
                ON p."projectId" = %s
               AND p.id = sw."protocolDbId"
             GROUP BY p.id, p."protocolId"
             ORDER BY MIN(sw."level"), p.id
            """,
            (
                int(projectId),
                int(rootProtocolDbId),
                int(projectId),
                int(projectId),
            ),
        )

        return self._rowsToDicts(rows)

    def loadExternalDescendantsForDeleteValidation(
            self,
            mapper,
            projectId: int,
            selectedProtocolDbIds: List[int],
    ) -> List[Dict[str, Any]]:
        rows = mapper.db.fetchAll(
            """
            WITH RECURSIVE downstream("protocolDbId", path) AS (
                SELECT
                    d."childProtocolDbId",
                    ARRAY[d."parentProtocolDbId", d."childProtocolDbId"]
                  FROM protocol_dependencies d
                 WHERE d."projectId" = %s
                   AND d."parentProtocolDbId" = ANY(%s)

                UNION ALL

                SELECT
                    d."childProtocolDbId",
                    downstream.path || d."childProtocolDbId"
                  FROM downstream
                  JOIN protocol_dependencies d
                    ON d."projectId" = %s
                   AND d."parentProtocolDbId" = downstream."protocolDbId"
                 WHERE NOT d."childProtocolDbId" = ANY(downstream.path)
            ),
            external_descendants AS (
                SELECT DISTINCT "protocolDbId"
                  FROM downstream
                 WHERE NOT "protocolDbId" = ANY(%s)
            ),
            output_counts AS (
                SELECT
                    p.id AS "protocolDbId",
                    COUNT(DISTINCT s.id) AS "setsCount",
                    COUNT(DISTINCT o.id) AS "objectsCount"
                  FROM protocols p
             LEFT JOIN scipion_sets s
                    ON s."projectId" = p."projectId"
                   AND s."protocolDbId" = p.id
             LEFT JOIN scipion_objects o
                    ON o."projectId" = p."projectId"
                   AND o."protocolDbId" = p.id
                 WHERE p."projectId" = %s
                   AND p.id IN (
                       SELECT "protocolDbId"
                         FROM external_descendants
                   )
                 GROUP BY p.id
            )
            SELECT
                p.id AS "protocolDbId",
                p."protocolId",
                p.status,
                COALESCE(oc."setsCount", 0) AS "setsCount",
                COALESCE(oc."objectsCount", 0) AS "objectsCount"
              FROM protocols p
         LEFT JOIN output_counts oc
                ON oc."protocolDbId" = p.id
             WHERE p."projectId" = %s
               AND p.id IN (
                   SELECT "protocolDbId"
                     FROM external_descendants
               )
             ORDER BY p.id
            """,
            (
                int(projectId),
                selectedProtocolDbIds,
                int(projectId),
                selectedProtocolDbIds,
                int(projectId),
                int(projectId),
            ),
        )

        return self._rowsToDicts(rows)

    def loadAffectedChildProtocolDbIdsForDeletedParents(
            self,
            mapper,
            projectId: int,
            parentProtocolDbIds: List[int],
    ) -> List[int]:
        if not parentProtocolDbIds:
            return []

        rows = mapper.db.fetchAll(
            """
            SELECT DISTINCT "protocolDbId"
              FROM protocol_input_refs
             WHERE "projectId" = %s
               AND "parentProtocolDbId" = ANY(%s)
               AND NOT ("protocolDbId" = ANY(%s))
             ORDER BY "protocolDbId"
            """,
            (
                int(projectId),
                parentProtocolDbIds,
                parentProtocolDbIds,
            ),
        )

        return [
            int(row["protocolDbId"])
            for row in rows or []
            if row.get("protocolDbId") not in (None, "")
        ]

    def loadInputRefPointerValue(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            inputName: str,
    ) -> Optional[Dict[str, Any]]:
        values = self.loadInputRefPointerValues(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
            inputName=inputName,
        )

        if not values:
            return None

        parentId, outputName = values[0].split(".", 1)

        return {
            "parentId": parentId,
            "outputName": outputName,
            "value": values[0],
        }

    def loadInputRefPointerValues(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            inputName: str,
    ) -> List[str]:
        rows = mapper.db.fetchAll(
            """
            SELECT
                parent."protocolId" AS "parentProtocolId",
                r."parentOutputName"
              FROM protocol_input_refs r
         LEFT JOIN protocols parent
                ON parent."projectId" = r."projectId"
               AND parent.id = r."parentProtocolDbId"
             WHERE r."projectId" = %s
               AND r."protocolDbId" = %s
               AND r."inputName" = %s
             ORDER BY r."itemIndex"
            """,
            (
                int(projectId),
                int(protocolDbId),
                str(inputName),
            ),
        )

        pointerValues = []

        for row in rows or []:
            parentId = row.get("parentProtocolId")
            outputName = row.get("parentOutputName")

            if parentId in (None, "") or not outputName:
                continue

            pointerValues.append("%s.%s" % (parentId, outputName))

        return pointerValues

    def loadInputRefsForProtocolCopy(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> List[Dict[str, Any]]:
        rows = mapper.db.fetchAll(
            """
            SELECT
                r."inputName",
                r."itemIndex",
                r."parentProtocolDbId",
                parent."protocolId" AS "parentProtocolId",
                r."parentOutputName",
                r."objectClassName",
                r."objectId"
              FROM protocol_input_refs r
         LEFT JOIN protocols parent
                ON parent."projectId" = r."projectId"
               AND parent.id = r."parentProtocolDbId"
             WHERE r."projectId" = %s
               AND r."protocolDbId" = %s
             ORDER BY r."inputName", r."itemIndex"
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        )

        return self._rowsToDicts(rows)

    def loadParentRefsForChildProtocol(
            self,
            mapper,
            projectId: int,
            childProtocolDbId: int,
    ) -> Dict[str, Any]:
        rows = mapper.db.fetchAll(
            """
            SELECT DISTINCT
                   r."parentProtocolDbId",
                   r."parentProtocolId"
              FROM protocol_input_refs r
             WHERE r."projectId" = %s
               AND r."protocolDbId" = %s
               AND r."parentProtocolDbId" IS NOT NULL
             ORDER BY r."parentProtocolDbId"
            """,
            (
                int(projectId),
                int(childProtocolDbId),
            ),
        )

        parentDbIds = []
        parentProtocolIds = []

        for row in rows or []:
            parentDbId = row.get("parentProtocolDbId")
            parentProtocolId = row.get("parentProtocolId")

            if parentDbId not in (None, ""):
                parentDbId = int(parentDbId)

                if parentDbId not in parentDbIds:
                    parentDbIds.append(parentDbId)

            if parentProtocolId not in (None, ""):
                try:
                    parentProtocolId = int(parentProtocolId)

                    if parentProtocolId not in parentProtocolIds:
                        parentProtocolIds.append(parentProtocolId)
                except Exception:
                    pass

        return {
            "parentProtocolDbIds": parentDbIds,
            "parentProtocolIds": parentProtocolIds,
        }

    def getProtocolStatusByScipionProtocolId(
            self,
            mapper,
            projectId: int,
            protocolId,
    ) -> Optional[str]:
        rows = mapper.db.fetchAll(
            """
            SELECT status
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
             ORDER BY id DESC
             LIMIT 1
            """,
            (
                int(projectId),
                str(protocolId),
            ),
        )

        if not rows:
            return None

        statusValue = rows[0].get("status")

        if statusValue is None:
            return None

        return str(statusValue).strip()

    def getProtocolRuntimeInfoByDbId(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> Optional[Dict[str, Any]]:
        row = mapper.db.fetchOne(
            """
            SELECT
                "protocolClassName",
                params
              FROM protocols
             WHERE "projectId" = %s
               AND id = %s
             LIMIT 1
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        )

        if not row:
            return None

        return dict(row)

    def refreshParentsForChildren(
            self,
            mapper,
            projectId: int,
            childProtocolDbIds: List[int],
    ) -> Dict[str, Any]:
        refreshed = []

        cleanChildDbIds = []
        seen = set()

        for childDbId in childProtocolDbIds or []:
            try:
                childDbId = int(childDbId)
            except Exception:
                continue

            if childDbId <= 0 or childDbId in seen:
                continue

            seen.add(childDbId)
            cleanChildDbIds.append(childDbId)

        for childDbId in cleanChildDbIds:
            parentRefs = self.loadParentRefsForChildProtocol(
                mapper=mapper,
                projectId=projectId,
                childProtocolDbId=childDbId,
            )

            parentDbIds = parentRefs.get("parentProtocolDbIds") or []
            parentProtocolIds = parentRefs.get("parentProtocolIds") or []

            dependenciesSaved = self.replaceDependenciesForProtocol(
                mapper=mapper,
                projectId=projectId,
                childProtocolDbId=int(childDbId),
                parentProtocolDbIds=parentDbIds,
            )

            self.updateProtocolParentIds(
                mapper=mapper,
                projectId=projectId,
                protocolDbId=int(childDbId),
                parentProtocolIds=parentProtocolIds,
            )

            refreshed.append({
                "childProtocolDbId": int(childDbId),
                "parentProtocolDbIds": parentDbIds,
                "parentProtocolIds": parentProtocolIds,
                "dependenciesSaved": dependenciesSaved,
            })

        return {
            "refreshed": refreshed,
            "count": len(refreshed),
        }

    def clearInputRefObjectIdsForParentProtocols(
            self,
            mapper,
            projectId: int,
            parentProtocolDbIds: List[int],
    ) -> int:
        if not parentProtocolDbIds:
            return 0

        cur = mapper.db.execute(
            """
            UPDATE protocol_input_refs
               SET "objectId" = NULL,
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND "parentProtocolDbId" = ANY(%s)
            """,
            (
                int(projectId),
                parentProtocolDbIds,
            ),
        )

        return int(cur.rowcount or 0)

    def deleteProtocolsAndRefreshChildren(
            self,
            mapper,
            projectId: int,
            protocolDbIds: List[int],
    ) -> Dict[str, Any]:
        protocolDbIds = [
            int(protocolDbId)
            for protocolDbId in protocolDbIds or []
            if protocolDbId not in (None, "")
        ]

        if not protocolDbIds:
            return {
                "deletedProtocolDbIds": [],
                "affectedChildren": [],
                "parentsRefresh": {
                    "refreshed": [],
                    "count": 0,
                },
            }

        affectedChildDbIds = self.loadAffectedChildProtocolDbIdsForDeletedParents(
            mapper=mapper,
            projectId=projectId,
            parentProtocolDbIds=protocolDbIds,
        )

        with mapper.db.transaction():
            # Deleting from protocols is enough for protocol_input_refs,
            # protocol_dependencies, scipion_sets and scipion_objects because
            # the schema has ON DELETE CASCADE. Keep this operation focused:
            # do not rebuild the whole graph from SQLite.
            self.deleteProtocolsByDbIds(
                mapper=mapper,
                projectId=projectId,
                protocolDbIds=protocolDbIds,
                commit=False,
            )

        parentsRefresh = self.refreshParentsForChildren(
            mapper=mapper,
            projectId=projectId,
            childProtocolDbIds=affectedChildDbIds,
        )

        return {
            "deletedProtocolDbIds": protocolDbIds,
            "affectedChildren": affectedChildDbIds,
            "parentsRefresh": parentsRefresh,
        }

    def deleteProtocolsByDbIds(
            self,
            mapper,
            projectId: int,
            protocolDbIds: List[int],
            commit: bool = True,
    ) -> int:
        if not protocolDbIds:
            return 0

        cur = mapper.db.execute(
            """
            DELETE FROM protocols
             WHERE "projectId" = %s
               AND id = ANY(%s)
            """,
            (
                int(projectId),
                protocolDbIds,
            ),
            commit=commit,
        )

        return int(cur.rowcount or 0)

    def clearInputRefObjectIdsForParentProtocolDbIds(
            self,
            mapper,
            projectId: int,
            parentProtocolDbIds: List[int],
    ) -> Dict[str, Any]:
        cleanParentDbIds = []
        seen = set()

        for parentDbId in parentProtocolDbIds or []:
            try:
                parentDbId = int(parentDbId)
            except Exception:
                continue

            if parentDbId <= 0:
                continue

            if parentDbId in seen:
                continue

            seen.add(parentDbId)
            cleanParentDbIds.append(parentDbId)

        if not cleanParentDbIds:
            return {
                "parents": [],
                "updatedRefs": 0,
            }

        cur = mapper.db.execute(
            """
            UPDATE protocol_input_refs
               SET "objectId" = NULL,
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND "parentProtocolDbId" = ANY(%s)
            """,
            (
                int(projectId),
                cleanParentDbIds,
            ),
        )

        return {
            "parents": cleanParentDbIds,
            "updatedRefs": int(cur.rowcount or 0),
        }

    def updateProtocolParentIds(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            parentProtocolIds: List[int],
    ) -> None:
        cleanParentIds = []
        seen = set()

        for parentId in parentProtocolIds or []:
            try:
                parentId = int(parentId)
            except Exception:
                continue

            if parentId <= 0:
                continue

            if parentId in seen:
                continue

            seen.add(parentId)
            cleanParentIds.append(parentId)

        mapper.db.execute(
            """
            UPDATE protocols
               SET "parentIds" = %s,
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND id = %s
            """,
            (
                cleanParentIds,
                int(projectId),
                int(protocolDbId),
            ),
        )

    def replaceInputGraphForProtocol(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            parentProtocolDbIds: List[int],
            parentProtocolIds: List[int],
            inputRefs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        dependenciesSaved = self.replaceDependenciesForProtocol(
            mapper=mapper,
            projectId=projectId,
            childProtocolDbId=int(protocolDbId),
            parentProtocolDbIds=parentProtocolDbIds,
        )

        inputRefsSaved = self.replaceInputRefsForProtocol(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(protocolDbId),
            refs=inputRefs,
        )

        self.updateProtocolParentIds(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(protocolDbId),
            parentProtocolIds=parentProtocolIds,
        )

        return {
            "dependencies": dependenciesSaved,
            "inputRefsSaved": inputRefsSaved,
        }

    def replaceDependenciesForProtocol(
            self,
            mapper,
            projectId: int,
            childProtocolDbId: int,
            parentProtocolDbIds: List[int],
    ) -> int:
        cleanParentDbIds = []
        seen = set()

        for parentDbId in parentProtocolDbIds or []:
            try:
                parentDbId = int(parentDbId)
            except Exception:
                continue

            if parentDbId <= 0:
                continue

            if parentDbId == int(childProtocolDbId):
                continue

            if parentDbId in seen:
                continue

            seen.add(parentDbId)
            cleanParentDbIds.append(parentDbId)

        with mapper.db.transaction():
            mapper.db.execute(
                """
                DELETE FROM protocol_dependencies
                 WHERE "projectId" = %s
                   AND "childProtocolDbId" = %s
                """,
                (projectId, childProtocolDbId),
                commit=False,
            )

            if not cleanParentDbIds:
                return 0

            valuesSql = ",".join(["(%s, %s, %s)"] * len(cleanParentDbIds))
            params = []

            for parentDbId in cleanParentDbIds:
                params.extend([
                    int(projectId),
                    int(parentDbId),
                    int(childProtocolDbId),
                ])

            mapper.db.execute(
                f"""
                INSERT INTO protocol_dependencies (
                    "projectId",
                    "parentProtocolDbId",
                    "childProtocolDbId"
                )
                VALUES {valuesSql}
                """,
                tuple(params),
                commit=False,
            )

        return len(cleanParentDbIds)

    def replaceInputRefsForProtocol(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            refs: List[Dict[str, Any]],
    ) -> int:
        cleanRefs = []
        seen = set()

        for ref in refs or []:
            inputName = str(ref.get("inputName") or "").strip()
            if not inputName:
                continue

            itemIndex = self.toOptionalInt(ref.get("itemIndex"))
            if itemIndex is None or itemIndex < 0:
                itemIndex = 0

            protocolId = str(ref.get("protocolId") or "").strip()
            if not protocolId:
                continue

            key = (inputName, itemIndex)
            if key in seen:
                continue

            seen.add(key)

            cleanRefs.append({
                "projectId": int(projectId),
                "protocolDbId": int(protocolDbId),
                "protocolId": protocolId,
                "inputName": inputName,
                "itemIndex": int(itemIndex),
                "parentProtocolDbId": self.toOptionalInt(ref.get("parentProtocolDbId")),
                "parentProtocolId": str(ref.get("parentProtocolId")).strip()
                if ref.get("parentProtocolId") not in (None, "") else None,
                "parentOutputName": str(ref.get("parentOutputName")).strip()
                if ref.get("parentOutputName") not in (None, "") else None,
                "objectClassName": str(ref.get("objectClassName")).strip()
                if ref.get("objectClassName") not in (None, "") else None,
                "objectId": str(ref.get("objectId")).strip()
                if ref.get("objectId") not in (None, "") else None,
            })

        with mapper.db.transaction():
            mapper.db.execute(
                """
                DELETE FROM protocol_input_refs
                 WHERE "projectId" = %s
                   AND "protocolDbId" = %s
                """,
                (projectId, protocolDbId),
                commit=False,
            )

            if not cleanRefs:
                return 0

            valuesSql = ",".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(cleanRefs))
            params = []

            for ref in cleanRefs:
                params.extend([
                    ref["projectId"],
                    ref["protocolDbId"],
                    ref["protocolId"],
                    ref["inputName"],
                    ref["itemIndex"],
                    ref["parentProtocolDbId"],
                    ref["parentProtocolId"],
                    ref["parentOutputName"],
                    ref["objectClassName"],
                    ref["objectId"],
                ])

            mapper.db.execute(
                f"""
                INSERT INTO protocol_input_refs (
                    "projectId",
                    "protocolDbId",
                    "protocolId",
                    "inputName",
                    "itemIndex",
                    "parentProtocolDbId",
                    "parentProtocolId",
                    "parentOutputName",
                    "objectClassName",
                    "objectId"
                )
                VALUES {valuesSql}
                ON CONFLICT ("projectId", "protocolDbId", "inputName", "itemIndex")
                DO UPDATE SET
                    "protocolId" = EXCLUDED."protocolId",
                    "parentProtocolDbId" = EXCLUDED."parentProtocolDbId",
                    "parentProtocolId" = EXCLUDED."parentProtocolId",
                    "parentOutputName" = EXCLUDED."parentOutputName",
                    "objectClassName" = EXCLUDED."objectClassName",
                    "objectId" = EXCLUDED."objectId",
                    "updatedAt" = NOW()
                """,
                tuple(params),
                commit=False,
            )

        return len(cleanRefs)

    @staticmethod
    def toOptionalInt(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None

        try:
            return int(value)
        except Exception:
            pass

        try:
            return int(float(value))
        except Exception:
            return None

    def getPersistedOutputObjectByRuntimeId(
            self,
            mapper,
            projectId: int,
            runtimeObjectId: int,
            extended=None,
    ) -> Optional[Dict[str, Any]]:
        row = mapper.db.fetchOne(
            """
            SELECT
                o.id AS "objectId",
                o."projectId",
                o."protocolDbId",
                p."protocolId",
                o."scipionObjId" AS "runtimeObjectId",
                o."parentObjectId",
                o.name,
                o.path,
                o."className",
                s.id AS "setId",
                s."outputName"
              FROM scipion_objects o
              JOIN protocols p
                ON p."projectId" = o."projectId"
               AND p.id = o."protocolDbId"
         LEFT JOIN scipion_sets s
                ON s."projectId" = o."projectId"
               AND s."objectId" = o.id
             WHERE o."projectId" = %s
               AND o."scipionObjId" = %s
             ORDER BY
                CASE WHEN o."parentObjectId" IS NULL THEN 0 ELSE 1 END,
                o.id
             LIMIT 1
            """,
            (
                int(projectId),
                int(runtimeObjectId),
            ),
        )

        if not row and extended not in (None, ""):
            outputName = str(extended).split(".", 1)[0]

            row = mapper.db.fetchOne(
                """
                SELECT
                    o.id AS "objectId",
                    o."projectId",
                    o."protocolDbId",
                    p."protocolId",
                    o."scipionObjId" AS "runtimeObjectId",
                    o."parentObjectId",
                    o.name,
                    o.path,
                    o."className",
                    s.id AS "setId",
                    s."outputName"
                  FROM protocols p
                  JOIN scipion_objects o
                    ON o."projectId" = p."projectId"
                   AND o."protocolDbId" = p.id
                   AND o."parentObjectId" IS NULL
             LEFT JOIN scipion_sets s
                    ON s."projectId" = o."projectId"
                   AND s."objectId" = o.id
                 WHERE p."projectId" = %s
                   AND p."protocolId"::text = %s
                   AND (
                        s."outputName" = %s
                        OR o.path = %s
                        OR o.name = %s
                   )
                 ORDER BY
                    CASE WHEN s.id IS NOT NULL THEN 0 ELSE 1 END,
                    o.id
                 LIMIT 1
                """,
                (
                    int(projectId),
                    str(runtimeObjectId),
                    outputName,
                    outputName,
                    outputName,
                ),
            )

        if not row:
            return None

        result = dict(row)

        if not result.get("outputName"):
            path = str(result.get("path") or result.get("name") or "")
            result["outputName"] = path.split(".", 1)[0]

        return result

    def insertImportedOutputRelation(
            self,
            mapper,
            projectId: int,
            creatorProtocolDbId: int,
            creatorProtocolId: int,
            relationName: str,
            parentRuntimeObjectId: int,
            childRuntimeObjectId: int,
            parentExtended=None,
            childExtended=None,
            metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        parentObject = self.getPersistedOutputObjectByRuntimeId(
            mapper=mapper,
            projectId=projectId,
            runtimeObjectId=parentRuntimeObjectId,
            extended=parentExtended,
        )

        if not parentObject:
            return {
                "saved": False,
                "reason": "parent_output_not_found",
            }

        childObject = self.getPersistedOutputObjectByRuntimeId(
            mapper=mapper,
            projectId=projectId,
            runtimeObjectId=childRuntimeObjectId,
            extended=childExtended,
        )

        if not childObject:
            return {
                "saved": False,
                "reason": "child_output_not_found",
            }

        with mapper.db.transaction():
            return self._insertImportedOutputRelationRows(
                mapper=mapper,
                projectId=projectId,
                creatorProtocolDbId=creatorProtocolDbId,
                creatorProtocolId=creatorProtocolId,
                relationName=relationName,
                parentRuntimeObjectId=parentRuntimeObjectId,
                childRuntimeObjectId=childRuntimeObjectId,
                parentObject=parentObject,
                childObject=childObject,
                parentExtended=parentExtended,
                childExtended=childExtended,
                metadata=metadata,
            )

    def replaceImportedOutputRelationsForCreator(
            self,
            mapper,
            projectId: int,
            creatorProtocolDbId: int,
            creatorProtocolId: int,
            relations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Replace one protocol relation snapshot atomically.

        All relation objects must be resolved before entering this method.
        Deleting the previous snapshot and inserting every new relation happen
        in one PostgreSQL transaction. Any insertion failure restores the
        complete previous snapshot.
        """
        persistedRelations = []

        with mapper.db.transaction():
            cleanupReport = (
                self._deleteImportedOutputRelationsForCreatorRows(
                    mapper=mapper,
                    projectId=projectId,
                    creatorProtocolDbId=creatorProtocolDbId,
                    creatorProtocolId=creatorProtocolId,
                )
            )

            for relation in relations or []:
                parentObject = relation.get(
                    "parentObject"
                )

                childObject = relation.get(
                    "childObject"
                )

                if not parentObject or not childObject:
                    raise RuntimeError(
                        "Cannot replace imported relation snapshot "
                        "because relation objects were not resolved."
                    )

                relationCreatorProtocolId = relation.get(
                    "creatorProtocolId"
                )

                if relationCreatorProtocolId in (
                        None,
                        "",
                ):
                    relationCreatorProtocolId = (
                        creatorProtocolId
                    )

                persistedRelations.append(
                    self._insertImportedOutputRelationRows(
                        mapper=mapper,
                        projectId=projectId,
                        creatorProtocolDbId=(
                            creatorProtocolDbId
                        ),
                        creatorProtocolId=int(
                            relationCreatorProtocolId
                        ),
                        relationName=relation.get(
                            "relationName"
                        ),
                        parentRuntimeObjectId=int(
                            relation[
                                "parentRuntimeObjectId"
                            ]
                        ),
                        childRuntimeObjectId=int(
                            relation[
                                "childRuntimeObjectId"
                            ]
                        ),
                        parentObject=parentObject,
                        childObject=childObject,
                        parentExtended=relation.get(
                            "parentExtended"
                        ),
                        childExtended=relation.get(
                            "childExtended"
                        ),
                        metadata=relation.get(
                            "metadata"
                        ),
                    )
                )

            self._markImportedRelationSnapshotSynchronized(
                mapper=mapper,
                projectId=projectId,
                creatorProtocolDbId=(
                    creatorProtocolDbId
                ),
                creatorProtocolId=(
                    creatorProtocolId
                ),
            )

        return {
            "saved": True,
            "cleanup": cleanupReport,
            "relations": persistedRelations,
            "snapshotSynchronized": True,
        }

    def deleteImportedOutputRelationsForCreator(
            self,
            mapper,
            projectId: int,
            creatorProtocolDbId: int,
            creatorProtocolId: int,
    ) -> Dict[str, int]:
        """
        Delete the PostgreSQL relation snapshot owned by one Scipion protocol.

        scipion_relations uses native Scipion runtime ids.
        scipion_object_relations uses canonical scipion_objects ids and stores
        creatorProtocolDbId in metadata.
        """
        with mapper.db.transaction():
            return (
                self._deleteImportedOutputRelationsForCreatorRows(
                    mapper=mapper,
                    projectId=projectId,
                    creatorProtocolDbId=creatorProtocolDbId,
                    creatorProtocolId=creatorProtocolId,
                )
            )

    def _markImportedRelationSnapshotSynchronized(
            self,
            mapper,
            projectId: int,
            creatorProtocolDbId: int,
            creatorProtocolId: int,
    ) -> None:
        """
        Mark one complete relation snapshot as PostgreSQL-authoritative.

        The caller owns the transaction. This update must commit or roll back
        together with deletion and insertion of the relation rows.
        """
        markerCursor = mapper.db.execute(
            """
            UPDATE protocols
               SET "relationsSynchronized" = TRUE,
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND id = %s
               AND "protocolId" = %s
            """,
            (
                int(projectId),
                int(creatorProtocolDbId),
                str(
                    creatorProtocolId
                ),
            ),
            commit=False,
        )

        markedProtocolCount = int(
            getattr(
                markerCursor,
                "rowcount",
                0,
            )
            or 0
        )

        if markedProtocolCount != 1:
            raise RuntimeError(
                "Cannot mark relation snapshot as synchronized "
                "for protocol %s."
                % creatorProtocolId
            )

    def _insertImportedOutputRelationRows(
            self,
            mapper,
            projectId: int,
            creatorProtocolDbId: int,
            creatorProtocolId: int,
            relationName: str,
            parentRuntimeObjectId: int,
            childRuntimeObjectId: int,
            parentObject: Dict[str, Any],
            childObject: Dict[str, Any],
            parentExtended=None,
            childExtended=None,
            metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Insert both PostgreSQL relation representations.

        The caller owns the transaction.
        """
        relationMetadata = dict(
            metadata or {}
        )

        relationMetadata.update({
            "creatorProtocolDbId": int(
                creatorProtocolDbId
            ),
            "creatorProtocolId": str(
                creatorProtocolId
            ),
            "parentProtocolDbId": int(
                parentObject["protocolDbId"]
            ),
            "parentProtocolId": str(
                parentObject["protocolId"]
            ),
            "parentOutputName": parentObject.get(
                "outputName"
            ),
            "childProtocolDbId": int(
                childObject["protocolDbId"]
            ),
            "childProtocolId": str(
                childObject["protocolId"]
            ),
            "childOutputName": childObject.get(
                "outputName"
            ),
        })

        legacyParentExtended = (
            ""
            if parentExtended is None
            else str(parentExtended)
        )

        legacyChildExtended = (
            ""
            if childExtended is None
            else str(childExtended)
        )

        mapper.db.execute(
            """
            INSERT INTO scipion_relations (
                "projectId",
                name,
                "creatorObjId",
                "parentObjId",
                "childObjId",
                "parentExtended",
                "childExtended"
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                int(projectId),
                relationName,
                int(creatorProtocolId),
                int(parentRuntimeObjectId),
                int(childRuntimeObjectId),
                legacyParentExtended,
                legacyChildExtended,
            ),
            commit=False,
        )

        mapper.db.execute(
            """
            INSERT INTO scipion_object_relations (
                "projectId",
                "creatorObjectId",
                "parentObjectId",
                "childObjectId",
                name,
                "parentExtended",
                "childExtended",
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT DO NOTHING
            """,
            (
                int(projectId),
                int(parentObject["objectId"]),
                int(parentObject["objectId"]),
                int(childObject["objectId"]),
                relationName,
                parentExtended,
                childExtended,
                json.dumps(
                    relationMetadata
                ),
            ),
            commit=False,
        )

        return {
            "saved": True,
            "relationName": relationName,
            "creatorProtocolId": str(
                creatorProtocolId
            ),
            "parentObjectId": int(
                parentObject["objectId"]
            ),
            "parentRuntimeObjectId": int(
                parentRuntimeObjectId
            ),
            "parentOutputName": parentObject.get(
                "outputName"
            ),
            "childObjectId": int(
                childObject["objectId"]
            ),
            "childRuntimeObjectId": int(
                childRuntimeObjectId
            ),
            "childOutputName": childObject.get(
                "outputName"
            ),
        }

    def _deleteImportedOutputRelationsForCreatorRows(
            self,
            mapper,
            projectId: int,
            creatorProtocolDbId: int,
            creatorProtocolId: int,
    ) -> Dict[str, int]:
        """
        Delete both relation representations.

        The caller owns the transaction.
        """
        legacyCursor = mapper.db.execute(
            """
            DELETE FROM scipion_relations
             WHERE "projectId" = %s
               AND "creatorObjId" = %s
            """,
            (
                int(projectId),
                int(creatorProtocolId),
            ),
            commit=False,
        )

        legacyRelationsDeleted = int(
            getattr(
                legacyCursor,
                "rowcount",
                0,
            )
            or 0
        )

        canonicalCursor = mapper.db.execute(
            """
            DELETE FROM scipion_object_relations
             WHERE "projectId" = %s
               AND metadata ->> 'creatorProtocolDbId' = %s
            """,
            (
                int(projectId),
                str(
                    int(
                        creatorProtocolDbId
                    )
                ),
            ),
            commit=False,
        )

        canonicalRelationsDeleted = int(
            getattr(
                canonicalCursor,
                "rowcount",
                0,
            )
            or 0
        )

        return {
            "legacyRelationsDeleted": (
                legacyRelationsDeleted
            ),
            "canonicalRelationsDeleted": (
                canonicalRelationsDeleted
            ),
        }