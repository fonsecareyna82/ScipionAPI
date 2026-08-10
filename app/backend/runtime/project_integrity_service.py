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
class RuntimeProjectIntegrityService:
    """Inspect PostgreSQL runtime integrity without modifying persisted state."""

    def checkProject(self, *, mapper, projectId: int):
        db = getattr(mapper, "db", None)

        if db is None:
            raise ValueError("mapper.db is required")

        projectId = int(projectId)

        project = db.fetchOne(
            """
            SELECT id
              FROM projects
             WHERE id = %s
            """,
            (projectId,),
        )

        if project is None:
            raise ValueError("PostgreSQL project %s was not found" % projectId)

        checks = {}
        issues = []

        for checkName, checker in (
            ("protocolRuntimeIds", self._checkProtocolRuntimeIds),
            ("protocolSteps", self._checkProtocolSteps),
            ("setOwnership", self._checkSetOwnership),
            ("setCounters", self._checkSetCounters),
            ("logicalTables", self._checkLogicalTables),
            ("logicalTableCounters", self._checkLogicalTableCounters),
            ("inputRefs", self._checkInputRefs),
            ("objectRelations", self._checkObjectRelations),
        ):
            checkIssues = checker(db=db, projectId=projectId)
            checks[checkName] = {"issuesCount": len(checkIssues)}
            issues.extend(checkIssues)

        issueCounts = {}

        for issue in issues:
            code = issue["code"]
            issueCounts[code] = issueCounts.get(code, 0) + 1

        return {
            "projectId": projectId,
            "healthy": len(issues) == 0,
            "issuesCount": len(issues),
            "issueCounts": issueCounts,
            "checks": checks,
            "issues": issues,
            "readOnly": True,
        }

    @staticmethod
    def _issue(code, resource, resourceId, message, **details):
        return {
            "code": code,
            "resource": resource,
            "resourceId": resourceId,
            "message": message,
            "details": details,
        }

    @staticmethod
    def _optionalInt(value):
        if value is None:
            return None

        if isinstance(value, bool):
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _checkProtocolRuntimeIds(self, *, db, projectId):
        issues = []

        rows = db.fetchAll(
            """
            SELECT id,
                   "protocolId"
              FROM protocols
             WHERE "projectId" = %s
             ORDER BY id
            """,
            (projectId,),
        ) or []

        for row in rows:
            protocolId = str(row.get("protocolId") or "").strip()

            try:
                runtimeId = int(protocolId)
            except (TypeError, ValueError):
                runtimeId = None

            if runtimeId is None or runtimeId <= 0 or str(runtimeId) != protocolId:
                issues.append(
                    self._issue(
                        "invalid_protocol_runtime_id",
                        "protocol",
                        int(row["id"]),
                        "Protocol does not expose a valid positive integer runtime protocolId.",
                        protocolId=protocolId,
                    )
                )

        return issues

    def _checkProtocolSteps(self, *, db, projectId):
        rows = db.fetchAll(
            """
            SELECT ps.id,
                   ps."protocolDbId",
                   ps."protocolId" AS "storedProtocolId",
                   ps."projectId" AS "stepProjectId",
                   p."projectId" AS "protocolProjectId",
                   p."protocolId" AS "expectedProtocolId"
              FROM protocol_steps ps
              JOIN protocols p
                ON p.id = ps."protocolDbId"
             WHERE ps."projectId" = %s
               AND (
                       p."projectId" <> ps."projectId"
                       OR p."protocolId" <> ps."protocolId"
                   )
             ORDER BY ps.id
            """,
            (projectId,),
        ) or []

        return [
            self._issue(
                "protocol_step_identity_mismatch",
                "protocol_step",
                int(row["id"]),
                "Protocol step runtime identity does not match its owning protocol row.",
                protocolDbId=int(row["protocolDbId"]),
                storedProtocolId=str(row["storedProtocolId"]),
                expectedProtocolId=str(row["expectedProtocolId"]),
                stepProjectId=int(row["stepProjectId"]),
                protocolProjectId=int(row["protocolProjectId"]),
            )
            for row in rows
        ]

    def _checkSetOwnership(self, *, db, projectId):
        rows = db.fetchAll(
            """
            SELECT s.id AS "setId",
                   s."protocolDbId",
                   s."objectId",
                   p."projectId" AS "protocolProjectId",
                   o."projectId" AS "objectProjectId",
                   o."protocolDbId" AS "objectProtocolDbId"
              FROM scipion_sets s
              LEFT JOIN protocols p
                ON p.id = s."protocolDbId"
              LEFT JOIN scipion_objects o
                ON o.id = s."objectId"
             WHERE s."projectId" = %s
               AND (
                       (
                           s."protocolDbId" IS NOT NULL
                           AND (
                               p.id IS NULL
                               OR p."projectId" <> s."projectId"
                           )
                       )
                       OR
                       (
                           s."objectId" IS NOT NULL
                           AND (
                               o.id IS NULL
                               OR o."projectId" <> s."projectId"
                               OR o."protocolDbId" IS DISTINCT FROM s."protocolDbId"
                           )
                       )
                   )
             ORDER BY s.id
            """,
            (projectId,),
        ) or []

        return [
            self._issue(
                "set_owner_mismatch",
                "scipion_set",
                int(row["setId"]),
                "PostgreSQL Set ownership does not match its protocol/object identity.",
                protocolDbId=row.get("protocolDbId"),
                objectId=row.get("objectId"),
                protocolProjectId=row.get("protocolProjectId"),
                objectProjectId=row.get("objectProjectId"),
                objectProtocolDbId=row.get("objectProtocolDbId"),
            )
            for row in rows
        ]

    def _checkSetCounters(self, *, db, projectId):
        rows = db.fetchAll(
            """
            SELECT s.id AS "setId",
                   s."outputName",
                   s.properties,
                   COUNT(i.id)::integer AS "actualItemsCount",
                   MAX(i."scipionItemId") AS "actualMaxItemId"
              FROM scipion_sets s
              LEFT JOIN scipion_set_items i
                ON i."setId" = s.id
             WHERE s."projectId" = %s
             GROUP BY s.id,
                      s."outputName",
                      s.properties
             ORDER BY s.id
            """,
            (projectId,),
        ) or []

        issues = []

        for row in rows:
            properties = row.get("properties") or {}
            actualItemsCount = int(row.get("actualItemsCount") or 0)
            actualMaxItemId = int(row.get("actualMaxItemId") or 0)

            if "itemsCount" in properties:
                storedItemsCount = self._optionalInt(properties.get("itemsCount"))

                if storedItemsCount is None:
                    storedItemsCount = 0

                if storedItemsCount != actualItemsCount:
                    issues.append(
                        self._issue(
                            "set_counter_mismatch",
                            "scipion_set",
                            int(row["setId"]),
                            "Stored Set itemsCount does not match persisted PostgreSQL items.",
                            outputName=row.get("outputName"),
                            counter="itemsCount",
                            stored=storedItemsCount,
                            actual=actualItemsCount,
                        )
                    )

            if "maxItemId" in properties:
                storedMaxItemId = self._optionalInt(properties.get("maxItemId"))

                if storedMaxItemId is None:
                    storedMaxItemId = 0

                if storedMaxItemId != actualMaxItemId:
                    issues.append(
                        self._issue(
                            "set_counter_mismatch",
                            "scipion_set",
                            int(row["setId"]),
                            "Stored Set maxItemId does not match persisted PostgreSQL items.",
                            outputName=row.get("outputName"),
                            counter="maxItemId",
                            stored=storedMaxItemId,
                            actual=actualMaxItemId,
                        )
                    )

        return issues

    def _checkLogicalTables(self, *, db, projectId):
        issues = []

        rootCounts = db.fetchAll(
            """
            SELECT s.id AS "setId",
                   COUNT(t.id)::integer AS "tablesCount",
                   COUNT(t.id) FILTER (
                       WHERE t."tableKind" = 'root'
                   )::integer AS "rootTablesCount"
              FROM scipion_sets s
              LEFT JOIN scipion_set_tables t
                ON t."setId" = s.id
             WHERE s."projectId" = %s
             GROUP BY s.id
             ORDER BY s.id
            """,
            (projectId,),
        ) or []

        for row in rootCounts:
            tablesCount = int(row.get("tablesCount") or 0)
            rootTablesCount = int(row.get("rootTablesCount") or 0)

            if tablesCount > 0 and rootTablesCount != 1:
                issues.append(
                    self._issue(
                        "logical_root_table_count_mismatch",
                        "scipion_set",
                        int(row["setId"]),
                        "Persisted logical tables do not contain exactly one root table.",
                        tablesCount=tablesCount,
                        rootTablesCount=rootTablesCount,
                    )
                )

        rows = db.fetchAll(
            """
            SELECT t.id AS "tableId",
                   t."setId",
                   t."tableKind",
                   t."parentTableId",
                   t."parentItemId",
                   pt."setId" AS "parentSetId",
                   pt."tableKind" AS "parentTableKind",
                   ri.id AS "parentRootItemRowId"
              FROM scipion_set_tables t
              JOIN scipion_sets s
                ON s.id = t."setId"
              LEFT JOIN scipion_set_tables pt
                ON pt.id = t."parentTableId"
              LEFT JOIN scipion_set_items ri
                ON ri."setId" = t."setId"
               AND ri."scipionItemId" = t."parentItemId"
             WHERE s."projectId" = %s
             ORDER BY t."setId", t.id
            """,
            (projectId,),
        ) or []

        for row in rows:
            tableKind = row.get("tableKind")

            if tableKind == "root":
                if row.get("parentTableId") is not None or row.get("parentItemId") is not None:
                    issues.append(
                        self._issue(
                            "logical_root_table_invalid",
                            "scipion_set_table",
                            int(row["tableId"]),
                            "Root logical table unexpectedly contains parent metadata.",
                            setId=int(row["setId"]),
                            parentTableId=row.get("parentTableId"),
                            parentItemId=row.get("parentItemId"),
                        )
                    )

                continue

            if tableKind != "child":
                continue

            parentTableId = row.get("parentTableId")
            parentItemId = row.get("parentItemId")

            if parentTableId is None or parentItemId is None:
                issues.append(
                    self._issue(
                        "logical_child_table_invalid",
                        "scipion_set_table",
                        int(row["tableId"]),
                        "Child logical table does not expose its complete parent identity.",
                        setId=int(row["setId"]),
                        parentTableId=parentTableId,
                        parentItemId=parentItemId,
                    )
                )

                continue

            if row.get("parentSetId") != row.get("setId") or row.get("parentTableKind") != "root":
                issues.append(
                    self._issue(
                        "logical_child_table_invalid",
                        "scipion_set_table",
                        int(row["tableId"]),
                        "Child logical table points to a root table owned by another logical structure.",
                        setId=int(row["setId"]),
                        parentTableId=int(parentTableId),
                        parentSetId=row.get("parentSetId"),
                        parentTableKind=row.get("parentTableKind"),
                    )
                )

            if row.get("parentRootItemRowId") is None:
                issues.append(
                    self._issue(
                        "logical_child_parent_item_missing",
                        "scipion_set_table",
                        int(row["tableId"]),
                        "Child logical table parentItemId does not exist in the root Set.",
                        setId=int(row["setId"]),
                        parentItemId=int(parentItemId),
                    )
                )

        return issues

    def _checkLogicalTableCounters(self, *, db, projectId):
        rows = db.fetchAll(
            """
            SELECT t.id AS "tableId",
                   t."setId",
                   t.properties,
                   COUNT(i.id)::integer AS "actualItemsCount",
                   MAX(i."scipionItemId") AS "actualMaxItemId"
              FROM scipion_set_tables t
              JOIN scipion_sets s
                ON s.id = t."setId"
              LEFT JOIN scipion_set_table_items i
                ON i."tableId" = t.id
             WHERE s."projectId" = %s
               AND t."tableKind" = 'child'
             GROUP BY t.id,
                      t."setId",
                      t.properties
             ORDER BY t.id
            """,
            (projectId,),
        ) or []

        issues = []

        for row in rows:
            properties = row.get("properties") or {}
            actualItemsCount = int(row.get("actualItemsCount") or 0)
            actualMaxItemId = int(row.get("actualMaxItemId") or 0)

            for counterName, actualValue in (
                ("itemsCount", actualItemsCount),
                ("maxItemId", actualMaxItemId),
            ):
                if counterName not in properties:
                    continue

                storedValue = self._optionalInt(properties.get(counterName))

                if storedValue is None:
                    storedValue = 0

                if storedValue == actualValue:
                    continue

                issues.append(
                    self._issue(
                        "logical_table_counter_mismatch",
                        "scipion_set_table",
                        int(row["tableId"]),
                        "Logical table counter does not match persisted PostgreSQL items.",
                        setId=int(row["setId"]),
                        counter=counterName,
                        stored=storedValue,
                        actual=actualValue,
                    )
                )

        return issues

    def _checkInputRefs(self, *, db, projectId):
        rows = db.fetchAll(
            """
            SELECT r."protocolDbId",
                   r."protocolId",
                   r."inputName",
                   r."itemIndex",
                   r."parentProtocolDbId",
                   r."parentProtocolId",
                   r."parentOutputName",
                   r."objectId",
                   cp."projectId" AS "childProjectId",
                   cp."protocolId" AS "expectedChildProtocolId",
                   pp."projectId" AS "parentProjectId",
                   pp."protocolId" AS "expectedParentProtocolId",
                   o.id AS "referencedObjectRowId"
              FROM protocol_input_refs r
              LEFT JOIN protocols cp
                ON cp.id = r."protocolDbId"
              LEFT JOIN protocols pp
                ON pp.id = r."parentProtocolDbId"
              LEFT JOIN scipion_objects o
                ON o."projectId" = r."projectId"
               AND o."protocolDbId" = r."parentProtocolDbId"
               AND o.path = r."parentOutputName"
               AND o."scipionObjId"::text = r."objectId"
             WHERE r."projectId" = %s
             ORDER BY r."protocolDbId",
                      r."inputName",
                      r."itemIndex"
            """,
            (projectId,),
        ) or []

        issues = []

        for row in rows:
            resourceId = "%s:%s:%s" % (
                row["protocolDbId"],
                row["inputName"],
                row["itemIndex"],
            )

            if row.get("childProjectId") != projectId or str(row.get("expectedChildProtocolId")) != str(row.get("protocolId")):
                issues.append(
                    self._issue(
                        "input_ref_identity_mismatch",
                        "protocol_input_ref",
                        resourceId,
                        "Input reference child runtime identity does not match protocolDbId.",
                        protocolDbId=row.get("protocolDbId"),
                        storedProtocolId=row.get("protocolId"),
                        expectedProtocolId=row.get("expectedChildProtocolId"),
                    )
                )

            if row.get("parentProtocolDbId") is not None:
                if row.get("parentProjectId") != projectId or str(row.get("expectedParentProtocolId")) != str(row.get("parentProtocolId")):
                    issues.append(
                        self._issue(
                            "input_ref_identity_mismatch",
                            "protocol_input_ref",
                            resourceId,
                            "Input reference parent runtime identity does not match parentProtocolDbId.",
                            parentProtocolDbId=row.get("parentProtocolDbId"),
                            storedParentProtocolId=row.get("parentProtocolId"),
                            expectedParentProtocolId=row.get("expectedParentProtocolId"),
                        )
                    )

            if row.get("parentProtocolDbId") is not None and row.get("parentOutputName") and row.get("objectId"):
                if row.get("referencedObjectRowId") is None:
                    issues.append(
                        self._issue(
                            "dangling_input_ref_object",
                            "protocol_input_ref",
                            resourceId,
                            "Input reference objectId does not resolve to the persisted parent output.",
                            parentProtocolDbId=row.get("parentProtocolDbId"),
                            parentOutputName=row.get("parentOutputName"),
                            objectId=row.get("objectId"),
                        )
                    )

        return issues

    def _checkObjectRelations(self, *, db, projectId):
        rows = db.fetchAll(
            """
            SELECT r.id AS "relationId",
                   r.name,
                   r."creatorObjId",
                   r."parentObjId",
                   r."childObjId",
                   (
                       EXISTS (
                           SELECT 1
                             FROM protocols p
                            WHERE p."projectId" = r."projectId"
                              AND p."protocolId" = r."creatorObjId"::text
                       )
                       OR EXISTS (
                           SELECT 1
                             FROM scipion_objects o
                            WHERE o."projectId" = r."projectId"
                              AND o."scipionObjId" = r."creatorObjId"
                       )
                   ) AS "creatorExists",
                   (
                       EXISTS (
                           SELECT 1
                             FROM protocols p
                            WHERE p."projectId" = r."projectId"
                              AND p."protocolId" = r."parentObjId"::text
                       )
                       OR EXISTS (
                           SELECT 1
                             FROM scipion_objects o
                            WHERE o."projectId" = r."projectId"
                              AND o."scipionObjId" = r."parentObjId"
                       )
                   ) AS "parentExists",
                   (
                       EXISTS (
                           SELECT 1
                             FROM protocols p
                            WHERE p."projectId" = r."projectId"
                              AND p."protocolId" = r."childObjId"::text
                       )
                       OR EXISTS (
                           SELECT 1
                             FROM scipion_objects o
                            WHERE o."projectId" = r."projectId"
                              AND o."scipionObjId" = r."childObjId"
                       )
                   ) AS "childExists"
              FROM scipion_relations r
             WHERE r."projectId" = %s
             ORDER BY r.id
            """,
            (projectId,),
        ) or []

        issues = []

        for row in rows:
            missingRoles = []

            if not row.get("creatorExists"):
                missingRoles.append("creator")

            if not row.get("parentExists"):
                missingRoles.append("parent")

            if not row.get("childExists"):
                missingRoles.append("child")

            if not missingRoles:
                continue

            issues.append(
                self._issue(
                    "dangling_runtime_relation",
                    "scipion_relation",
                    int(row["relationId"]),
                    "Runtime relation references PostgreSQL objects that cannot be resolved.",
                    name=row.get("name"),
                    creatorObjId=int(row["creatorObjId"]),
                    parentObjId=int(row["parentObjId"]),
                    childObjId=int(row["childObjId"]),
                    missingRoles=missingRoles,
                )
            )

        return issues