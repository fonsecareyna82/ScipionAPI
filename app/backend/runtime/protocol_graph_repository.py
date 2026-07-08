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
from typing import Any, Dict, List, Optional


class ProtocolGraphRepository:
    """
    Persist PostgreSQL runtime protocol graph data.

    This repository owns:
      - protocol_dependencies
      - protocol_input_refs
      - protocols.parentIds
    """

    @staticmethod
    def _rowsToDicts(rows) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in rows or []
        ]

    def getPersistedOutputInfoForInputRef(
            self,
            mapper,
            projectId: int,
            parentProtocolDbId: int,
            outputName: str,
    ) -> Dict[str, Any]:
        row = mapper.db.fetchOne(
            """
            SELECT
                s."objectId"::text AS "objectId",
                s."setClassName" AS "className"
              FROM scipion_sets s
             WHERE s."projectId" = %s
               AND s."protocolDbId" = %s
               AND s."outputName" = %s

            UNION ALL

            SELECT
                o."scipionObjId"::text AS "objectId",
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
                "objectId": None,
                "className": None,
            }

        return {
            "objectId": row.get("objectId"),
            "className": row.get("className"),
        }

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