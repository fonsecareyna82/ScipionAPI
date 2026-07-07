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

        return [
            dict(row)
            for row in rows or []
        ]

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

        return [
            dict(row)
            for row in rows or []
        ]

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

        return [
            dict(row)
            for row in rows or []
        ]

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