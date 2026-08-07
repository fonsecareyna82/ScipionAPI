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
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import psycopg2.extras


class ScipionObjectPostgresqlMapper:
    """Register and store Scipion data objects in PostgreSQL."""

    RUNTIME_ONLY_ATTRIBUTE_NAMES = frozenset({
        "_objParent",
    })

    def __init__(self, db):
        self.db = db

    def registerObjectTypeFromObject(
        self,
        scipionObj: Any,
        mapperKind: Optional[str] = None,
        includeProperties: bool = True,
        includeNestedProperties: bool = True,
        classSchema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        typeId = self.registerObjectType(scipionObj, mapperKind=mapperKind, classSchema=classSchema)
        propertiesCount = 0
        if includeProperties:
            propertiesCount = self.registerObjectTypeProperties(
                typeId,
                scipionObj,
                includeNestedProperties=includeNestedProperties,
            )
        return {
            "typeId": typeId,
            "className": self._getClassName(scipionObj),
            "propertiesCount": propertiesCount,
        }

    def registerObjectType(
        self,
        scipionObj: Any,
        mapperKind: Optional[str] = None,
        classSchema: Optional[Dict[str, Any]] = None,
    ) -> int:
        className = self._getClassName(scipionObj)
        if not className:
            raise ValueError("Cannot register a Scipion object type without className")

        cur = self.db.execute(
            """
            INSERT INTO scipion_object_types (
                "className", "moduleName", "baseClassName", "mapperKind", "schema"
            )
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT ("className")
            DO UPDATE SET
                "moduleName" = EXCLUDED."moduleName",
                "baseClassName" = EXCLUDED."baseClassName",
                "mapperKind" = EXCLUDED."mapperKind",
                "schema" = scipion_object_types."schema" || EXCLUDED."schema",
                "updatedAt" = NOW()
            RETURNING id
            """,
            (
                className,
                self._getModuleName(scipionObj),
                self._getBaseClassName(scipionObj),
                mapperKind or self._guessMapperKind(scipionObj),
                self._jsonParam(classSchema or {}),
            ),
        )
        return int(cur.fetchone()["id"])

    def registerObjectTypeProperties(
        self,
        typeId: int,
        scipionObj: Any,
        includeNestedProperties: bool = True,
    ) -> int:
        properties = list(self._iterProperties(scipionObj, includeNestedProperties=includeNestedProperties))
        if not properties:
            return 0

        with self.db.transaction():
            for prop in properties:
                self.db.execute(
                    """
                    INSERT INTO scipion_object_type_properties (
                        "typeId", "propertyPath", "className", "valueKind",
                        "isPointer", "isNested", "schema"
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT ("typeId", "propertyPath")
                    DO UPDATE SET
                        "className" = EXCLUDED."className",
                        "valueKind" = EXCLUDED."valueKind",
                        "isPointer" = EXCLUDED."isPointer",
                        "isNested" = EXCLUDED."isNested",
                        "schema" = scipion_object_type_properties."schema" || EXCLUDED."schema",
                        "updatedAt" = NOW()
                    """,
                    (
                        typeId,
                        prop["propertyPath"],
                        prop["className"],
                        prop["valueKind"],
                        prop["isPointer"],
                        prop["isNested"],
                        self._jsonParam(prop.get("schema") or {}),
                    ),
                    commit=False,
                )
        return len(properties)

    def storeObjectTree(
        self,
        projectId: int,
        protocolDbId: int,
        outputName: str,
        scipionObj: Any,
        registerType: bool = True,
        includeNestedProperties: bool = True,
        scipionObjectIdsByPath: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        if not projectId:
            raise ValueError("projectId is required")
        if not protocolDbId:
            raise ValueError("protocolDbId is required")
        if not outputName:
            raise ValueError("outputName is required")

        if registerType:
            self.registerObjectTypeFromObject(scipionObj, includeNestedProperties=includeNestedProperties)

        storedPaths: List[str] = []

        with self.db.transaction():
            conflictingSetsDeleted = (
                self._deleteStoredSetForOutput(
                    projectId=projectId,
                    protocolDbId=protocolDbId,
                    outputName=outputName,
                )
            )

            storeNodeKwargs = {
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "scipionObj": scipionObj,
                "name": outputName,
                "path": outputName,
                "parentObjectId": None,
                "storedPaths": storedPaths,
                "includeNestedProperties": includeNestedProperties,
                "visited": set(),
            }

            if isinstance(scipionObjectIdsByPath, dict):
                storeNodeKwargs["scipionObjectIdsByPath"] = scipionObjectIdsByPath

            rootObjectId = self._storeObjectNode(**storeNodeKwargs)
            staleObjectsDeleted = (
                self._deleteStaleObjectTreePaths(
                    projectId=projectId,
                    protocolDbId=protocolDbId,
                    outputName=outputName,
                    storedPaths=storedPaths,
                )
            )

        return {
            "rootObjectId": rootObjectId,
            "projectId": projectId,
            "protocolDbId": protocolDbId,
            "outputName": outputName,
            "storedObjectsCount": len(storedPaths),
            "storedPaths": storedPaths,
            "staleObjectsDeleted": staleObjectsDeleted,
            "conflictingSetsDeleted": conflictingSetsDeleted,
        }

    def getStoredObjectTree(self, projectId: int, protocolDbId: int, outputName: str) -> List[Dict[str, Any]]:
        rootPath = str(outputName)
        return self.db.fetchAll(
            """
            SELECT id, "projectId", "protocolDbId", "scipionObjId", "parentObjectId",
                   name, path, "className", value, label, comment, creation,
                   metadata, "createdAt", "updatedAt"
              FROM scipion_objects
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND (path = %s OR path LIKE %s)
             ORDER BY path ASC
            """,
            (projectId, protocolDbId, rootPath, f"{rootPath}.%"),
        )

    def mergeStoredObjectMetadata(
            self,
            projectId: int,
            protocolDbId: int,
            objectDbId: int,
            metadata: Dict[str, Any],
    ) -> int:
        with self.db.transaction():
            cursor = self.db.execute(
                """
                UPDATE scipion_objects
                   SET metadata = (
                           COALESCE(
                               metadata,
                               '{}'::jsonb
                           )
                           || %s::jsonb
                       ),
                       "updatedAt" = NOW()
                 WHERE id = %s
                   AND "projectId" = %s
                   AND "protocolDbId" = %s
                """,
                (
                    json.dumps(metadata or {}),
                    int(objectDbId),
                    int(projectId),
                    int(protocolDbId),
                ),
                commit=False,
            )

        return int(cursor.rowcount or 0)

    def getStoredObjectSubtreeByScipionObjId(
            self,
            projectId: int,
            scipionObjId: int,
    ) -> List[Dict[str, Any]]:
        """
        Return one stored object and all its descendants.

        The latest matching PostgreSQL row is selected to preserve the same
        resolution policy used by canonical runtime relations.
        """
        return self.db.fetchAll(
            """
            WITH RECURSIVE selected_root AS (
                SELECT
                    object_row.id,
                    object_row."projectId",
                    object_row."protocolDbId",
                    object_row."scipionObjId",
                    object_row."parentObjectId",
                    parent_row."scipionObjId" AS "rootParentScipionObjId",
                    object_row.name,
                    object_row.path,
                    object_row."className",
                    object_row.value,
                    object_row.label,
                    object_row.comment,
                    object_row.creation,
                    object_row.metadata,
                    object_row."createdAt",
                    object_row."updatedAt",
                    protocol."protocolId"
                        AS "ownerProtocolId",
                    0 AS depth
                  FROM scipion_objects object_row
            LEFT JOIN scipion_objects parent_row
                    ON parent_row.id = object_row."parentObjectId"
             LEFT JOIN protocols protocol
                    ON protocol.id = object_row."protocolDbId"
                 WHERE object_row."projectId" = %s
                   AND object_row."scipionObjId" = %s
              ORDER BY object_row.id DESC
                 LIMIT 1
            ),
                        object_tree AS (
                SELECT
                    selected_root.id,
                    selected_root."projectId",
                    selected_root."protocolDbId",
                    selected_root."scipionObjId",
                    selected_root."parentObjectId",
                    selected_root."rootParentScipionObjId",
                    selected_root.name,
                    selected_root.path,
                    selected_root."className",
                    selected_root.value,
                    selected_root.label,
                    selected_root.comment,
                    selected_root.creation,
                    selected_root.metadata,
                    selected_root."createdAt",
                    selected_root."updatedAt",
                    selected_root."ownerProtocolId",
                    selected_root.depth
                  FROM selected_root

                UNION ALL

                SELECT
                    child.id,
                    child."projectId",
                    child."protocolDbId",
                    child."scipionObjId",
                    child."parentObjectId",
                    object_tree."rootParentScipionObjId",
                    child.name,
                    child.path,
                    child."className",
                    child.value,
                    child.label,
                    child.comment,
                    child.creation,
                    child.metadata,
                    child."createdAt",
                    child."updatedAt",
                    object_tree."ownerProtocolId",
                    object_tree.depth + 1
                  FROM scipion_objects child
                  JOIN object_tree
                    ON child."parentObjectId" = object_tree.id
            )
            SELECT
                id,
                "projectId",
                "protocolDbId",
                "scipionObjId",
                "parentObjectId",
                "rootParentScipionObjId",
                name,
                path,
                "className",
                value,
                label,
                comment,
                creation,
                metadata,
                "createdAt",
                "updatedAt",
                "ownerProtocolId",
                depth
              FROM object_tree
          ORDER BY depth ASC,
                   path ASC
            """,
            (
                int(projectId),
                int(scipionObjId),
            ),
        )

    def listCanonicalStoredObjectRows(
            self,
            projectId: int,
            className: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return the latest stored row for every runtime object id.

        Set roots are excluded because they are reconstructed by the dedicated
        PostgreSQL set reader. The class filter is applied after canonical row
        selection so an older version of an object is never returned.
        """
        values = [int(projectId)]
        classFilter = ""

        if className:
            classFilter = '\n               AND canonical."className" = %s'
            values.append(str(className))

        return self.db.fetchAll(
            f"""
            WITH canonical_objects AS (
                SELECT DISTINCT ON (object_row."scipionObjId")
                    object_row.id,
                    object_row."scipionObjId" AS "runtimeObjectId",
                    object_row."className",
                    EXISTS (
                        SELECT 1
                          FROM scipion_sets stored_set
                         WHERE stored_set."objectId" = object_row.id
                    ) AS "isStoredSet"
                  FROM scipion_objects object_row
                 WHERE object_row."projectId" = %s
                   AND object_row."scipionObjId" IS NOT NULL
              ORDER BY object_row."scipionObjId",
                       object_row.id DESC
            )
            SELECT
                canonical.id,
                canonical."runtimeObjectId",
                canonical."className"
              FROM canonical_objects canonical
             WHERE NOT canonical."isStoredSet"{classFilter}
          ORDER BY canonical.id ASC
            """,
            tuple(values),
        )

    def listProtocolStoredObjects(self, projectId: int, protocolDbId: int) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT id, "projectId", "protocolDbId", "scipionObjId", "parentObjectId",
                   name, path, "className", value, label, comment, creation,
                   metadata, "createdAt", "updatedAt"
              FROM scipion_objects
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY path ASC
            """,
            (projectId, protocolDbId),
        )

    def listProtocolTreeOutputRows(
            self,
            projectId: int,
            protocolDbId: int,
    ) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT
                COALESCE(
                    NULLIF(object_row.path, ''),
                    object_row.name
                ) AS "outputName",
                object_row.id AS "rootObjectId",
                object_row."scipionObjId",
                object_row."className",
                object_row.value,
                object_row.label,
                object_row.comment,
                object_row.metadata
              FROM scipion_objects object_row
             WHERE object_row."projectId" = %s
               AND object_row."protocolDbId" = %s
               AND object_row."parentObjectId" IS NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM scipion_sets stored_set
                     WHERE stored_set."objectId" = object_row.id
               )
             ORDER BY "outputName"
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        ) or []

    def listProtocolTreeOutputNameRows(
            self,
            projectId: int,
            protocolDbId: int,
    ) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT COALESCE(
                       NULLIF(object_row.path, ''),
                       object_row.name
                   ) AS "outputName"
              FROM scipion_objects object_row
             WHERE object_row."projectId" = %s
               AND object_row."protocolDbId" = %s
               AND object_row."parentObjectId" IS NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM scipion_sets stored_set
                     WHERE stored_set."objectId" = object_row.id
               )
            """,
            (int(projectId), int(protocolDbId)),
        ) or []

    def listProtocolOutputFileRows(
            self,
            projectId: int,
            protocolDbId: int,
    ) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT DISTINCT file_name
              FROM (
                    SELECT root_object.metadata ->> 'fileName' AS file_name
                      FROM scipion_sets stored_set
                      LEFT JOIN scipion_objects root_object
                        ON root_object.id = stored_set."objectId"
                     WHERE stored_set."projectId" = %s
                       AND stored_set."protocolDbId" = %s

                    UNION

                    SELECT object_row.metadata ->> 'fileName' AS file_name
                      FROM scipion_objects object_row
                     WHERE object_row."projectId" = %s
                       AND object_row."protocolDbId" = %s
                       AND object_row."parentObjectId" IS NULL
              ) stored_files
             WHERE file_name IS NOT NULL
               AND file_name <> ''
            """,
            (int(projectId), int(protocolDbId), int(projectId), int(protocolDbId)),
        ) or []

    def listProjectTreeOutputRows(self, projectId: int) -> List[Dict[str, Any]]:
        query = """
            SELECT
                protocol_row."protocolId",
                object_row.id,
                object_row."scipionObjId",
                object_row.name,
                object_row.path,
                object_row."className",
                object_row.value,
                object_row.label,
                object_row.comment,
                object_row.metadata,
                object_row."createdAt",
                object_row."updatedAt"
              FROM scipion_objects object_row
              JOIN protocols protocol_row
                ON protocol_row.id = object_row."protocolDbId"
             WHERE object_row."projectId" = %s
               AND object_row."parentObjectId" IS NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM scipion_sets stored_set
                     WHERE stored_set."objectId" = object_row.id
               )
             ORDER BY protocol_row."protocolId", object_row.path
        """
        return self.db.fetchAll(query, (int(projectId),)) or []

    def deleteProtocolOutputSnapshots(
            self,
            projectId: int,
            protocolDbId: int,
            outputNames: List[str],
    ) -> List[Dict[str, Any]]:
        removedOutputs: List[Dict[str, Any]] = []

        with self.db.transaction():
            for outputName in outputNames:
                outputName = str(outputName)

                setCursor = self.db.execute(
                    """
                    DELETE FROM scipion_sets
                     WHERE "projectId" = %s
                       AND "protocolDbId" = %s
                       AND "outputName" = %s
                    """,
                    (int(projectId), int(protocolDbId), outputName),
                    commit=False,
                )

                objectCursor = self.db.execute(
                    """
                    DELETE FROM scipion_objects
                     WHERE "projectId" = %s
                       AND "protocolDbId" = %s
                       AND (
                            path = %s
                            OR LEFT(
                                path,
                                CHAR_LENGTH(%s) + 1
                            ) = %s || '.'
                       )
                    """,
                    (int(projectId), int(protocolDbId), outputName, outputName, outputName),
                    commit=False,
                )

                removedOutputs.append({
                    "outputName": outputName,
                    "setsDeleted": int(setCursor.rowcount or 0),
                    "objectsDeleted": int(objectCursor.rowcount or 0),
                })

        return removedOutputs

    def deleteProtocolOutputMetadata(
            self,
            projectId: int,
            protocolDbId: int,
    ) -> Dict[str, int]:
        projectId = int(projectId)
        protocolDbId = int(protocolDbId)
        setsDeleted = 0
        objectsDeleted = 0

        with self.db.transaction():
            setRows = self.db.fetchAll(
                """
                SELECT id
                  FROM scipion_sets
                 WHERE "projectId" = %s
                   AND "protocolDbId" = %s
                """,
                (projectId, protocolDbId),
            ) or []

            setIds = [
                int(row.get("id") if isinstance(row, dict) else row[0])
                for row in setRows
                if (row.get("id") if isinstance(row, dict) else row[0]) is not None
            ]

            if setIds:
                self.db.execute(
                    """
                    DELETE FROM scipion_set_table_items
                     WHERE "tableId" IN (
                           SELECT id
                             FROM scipion_set_tables
                            WHERE "setId" = ANY(%s)
                     )
                    """,
                    (setIds,),
                    commit=False,
                )

                self.db.execute(
                    """
                    DELETE FROM scipion_set_table_columns
                     WHERE "tableId" IN (
                           SELECT id
                             FROM scipion_set_tables
                            WHERE "setId" = ANY(%s)
                     )
                    """,
                    (setIds,),
                    commit=False,
                )

                self.db.execute(
                    """
                    DELETE FROM scipion_set_tables
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                self.db.execute(
                    """
                    DELETE FROM scipion_set_items
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                self.db.execute(
                    """
                    DELETE FROM scipion_set_columns
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                self.db.execute(
                    """
                    DELETE FROM scipion_set_properties
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                setCursor = self.db.execute(
                    """
                    DELETE FROM scipion_sets
                     WHERE id = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                setsDeleted = int(setCursor.rowcount or 0)

            objectCursor = self.db.execute(
                """
                WITH RECURSIVE object_tree AS (
                    SELECT object_row.id
                      FROM scipion_objects object_row
                     WHERE object_row."projectId" = %s
                       AND object_row."protocolDbId" = %s

                    UNION

                    SELECT child.id
                      FROM scipion_objects child
                      JOIN object_tree parent
                        ON child."parentObjectId" = parent.id
                     WHERE child."projectId" = %s
                       AND child."protocolDbId" = %s
                )
                DELETE FROM scipion_objects
                 WHERE id IN (
                       SELECT id
                         FROM object_tree
                 )
                """,
                (projectId, protocolDbId, projectId, protocolDbId),
                commit=False,
            )

            objectsDeleted = int(objectCursor.rowcount or 0)

        return {
            "setsDeleted": setsDeleted,
            "objectsDeleted": objectsDeleted,
        }

    def deleteStoredObjectSubtreesByScipionObjId(
            self,
            projectId: int,
            scipionObjId: int,
    ) -> Dict[str, int]:
        """
        Delete every generic object subtree whose root uses the supplied
        Scipion runtime object id.

        Stored Set roots are deliberately excluded. Deleting a Set root from
        scipion_objects would leave scipion_sets.objectId set to NULL instead
        of removing the complete PostgreSQL Set representation.

        Descendants are selected recursively. Runtime relations involving any
        deleted node are removed explicitly from scipion_relations.
        """
        projectId = int(projectId)
        scipionObjId = int(scipionObjId)

        with self.db.transaction():
            result = self.db.fetchOne(
                """
                WITH RECURSIVE selected_roots AS (
                    SELECT
                        object_row.id,
                        object_row."scipionObjId"
                      FROM scipion_objects object_row
                     WHERE object_row."projectId" = %s
                       AND object_row."scipionObjId" = %s
                       AND NOT EXISTS (
                            SELECT 1
                              FROM scipion_sets stored_set
                             WHERE stored_set."objectId" = object_row.id
                       )
                ),
                object_tree AS (
                    SELECT
                        selected_roots.id,
                        selected_roots."scipionObjId"
                      FROM selected_roots

                    UNION

                    SELECT
                        child.id,
                        child."scipionObjId"
                      FROM scipion_objects child
                      JOIN object_tree
                        ON child."parentObjectId" = object_tree.id
                     WHERE child."projectId" = %s
                       AND NOT EXISTS (
                            SELECT 1
                              FROM scipion_sets stored_set
                             WHERE stored_set."objectId" = child.id
                       )
                ),
                runtime_ids AS (
                    SELECT DISTINCT
                        "scipionObjId" AS "runtimeObjectId"
                      FROM object_tree
                     WHERE "scipionObjId" IS NOT NULL
                ),
                deleted_runtime_relations AS (
                    DELETE FROM scipion_relations relation_row
                     WHERE relation_row."projectId" = %s
                       AND (
                            relation_row."creatorObjId" IN (
                                SELECT "runtimeObjectId"
                                  FROM runtime_ids
                            )
                            OR relation_row."parentObjId" IN (
                                SELECT "runtimeObjectId"
                                  FROM runtime_ids
                            )
                            OR relation_row."childObjId" IN (
                                SELECT "runtimeObjectId"
                                  FROM runtime_ids
                            )
                       )
                    RETURNING relation_row.id
                ),
                deleted_objects AS (
                    DELETE FROM scipion_objects object_row
                     WHERE object_row."projectId" = %s
                       AND object_row.id IN (
                            SELECT id
                              FROM object_tree
                       )
                    RETURNING object_row.id
                )
                SELECT
                    (
                        SELECT COUNT(*)
                          FROM deleted_objects
                    )::integer AS "deletedObjectsCount",
                    (
                        SELECT COUNT(*)
                          FROM deleted_runtime_relations
                    )::integer AS "deletedRelationsCount"
                """,
                (
                    projectId,
                    scipionObjId,
                    projectId,
                    projectId,
                    projectId,
                ),
            )

        result = result or {}

        return {
            "deletedObjectsCount": int(
                result.get("deletedObjectsCount") or 0
            ),
            "deletedRelationsCount": int(
                result.get("deletedRelationsCount") or 0
            ),
        }

    def _deleteStoredSetForOutput(
            self,
            projectId: int,
            protocolDbId: int,
            outputName: str,
    ) -> int:
        """
        Remove a previously persisted flat-set representation when the same
        protocol output is now being stored as an object tree.

        Child set rows are removed through PostgreSQL foreign-key cascades.
        The associated root scipion_object is kept because scipion_sets.objectId
        uses ON DELETE SET NULL and will be reused by storeObjectTree().
        """
        cursor = self.db.execute(
            """
            DELETE FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND "outputName" = %s
            """,
            (
                projectId,
                protocolDbId,
                str(outputName),
            ),
            commit=False,
        )

        return int(cursor.rowcount or 0)

    def _deleteStaleObjectTreePaths(
            self,
            projectId: int,
            protocolDbId: int,
            outputName: str,
            storedPaths: List[str],
    ) -> int:
        """
        Remove persisted paths belonging to one output that were not produced
        by the current object-tree traversal.
        """
        normalizedPaths = [
            str(path)
            for path in storedPaths or []
            if str(path or "").strip()
        ]

        if not normalizedPaths:
            return 0

        outputRoot = str(outputName)

        cursor = self.db.execute(
            """
            DELETE FROM scipion_objects
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND (
                    path = %s
                    OR LEFT(
                        path,
                        CHAR_LENGTH(%s) + 1
                    ) = %s || '.'
               )
               AND NOT (
                    path = ANY(%s)
               )
            """,
            (
                projectId,
                protocolDbId,
                outputRoot,
                outputRoot,
                outputRoot,
                normalizedPaths,
            ),
            commit=False,
        )

        return int(cursor.rowcount or 0)

    def getObjectType(self, className: str) -> Optional[Dict[str, Any]]:
        return self.db.fetchOne(
            """
            SELECT id, "className", "moduleName", "baseClassName", "mapperKind", "schema", "createdAt", "updatedAt"
              FROM scipion_object_types
             WHERE "className" = %s
            """,
            (className,),
        )

    def listObjectTypeProperties(self, className: str) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT p.id, p."typeId", p."propertyPath", p."className", p."valueKind",
                   p."isPointer", p."isNested", p."schema", p."createdAt", p."updatedAt"
              FROM scipion_object_type_properties p
              JOIN scipion_object_types t
                ON t.id = p."typeId"
             WHERE t."className" = %s
             ORDER BY p."propertyPath" ASC
            """,
            (className,),
        )

    def _storeObjectNode(
        self,
        projectId: int,
        protocolDbId: int,
        scipionObj: Any,
        name: str,
        path: str,
        parentObjectId: Optional[int],
        storedPaths: List[str],
        includeNestedProperties: bool,
        visited: Set[int],
        scipionObjectIdsByPath: Optional[Dict[str, int]] = None,
    ) -> int:
        objIdentity = id(scipionObj)
        if objIdentity in visited:
            return parentObjectId or 0
        visited.add(objIdentity)

        scipionObjectId = None

        if isinstance(scipionObjectIdsByPath, dict):
            scipionObjectId = scipionObjectIdsByPath.get(path)

        if scipionObjectId is None:
            scipionObjectId = self._getScipionObjId(scipionObj, path)

        attributes = self._getAttributesToStore(scipionObj)
        metadata = {
            "moduleName": self._getModuleName(scipionObj),
            "baseClassName": self._getBaseClassName(scipionObj),
            "mapperKind": self._guessMapperKind(scipionObj),
            "displayText": self._getObjectDisplayText(scipionObj),
            "fileName": self._getObjectFileName(scipionObj),
            "isPointer": self._isPointer(scipionObj),
            "isNested": bool(attributes),
            "hasSourceObjId": self._getSourceObjId(scipionObj) is not None,
        }

        if metadata["isPointer"]:
            metadata["pointerReference"] = self._serializePointerReference(scipionObj)

        cur = self.db.execute(
            """
            INSERT INTO scipion_objects (
                "projectId", "protocolDbId", "scipionObjId", "parentObjectId",
                name, path, "className", value, label, comment, creation, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT ON CONSTRAINT ux_scipion_objects_project_protocol_path
            DO UPDATE SET
                "scipionObjId" = EXCLUDED."scipionObjId",
                "parentObjectId" = EXCLUDED."parentObjectId",
                name = EXCLUDED.name,
                "className" = EXCLUDED."className",
                value = EXCLUDED.value,
                label = EXCLUDED.label,
                comment = EXCLUDED.comment,
                creation = EXCLUDED.creation,
                metadata = scipion_objects.metadata || EXCLUDED.metadata,
                "updatedAt" = NOW()
            RETURNING id
            """,
            (
                projectId,
                protocolDbId,
                scipionObjectId,
                parentObjectId,
                name,
                path,
                self._getClassName(scipionObj),
                self._getObjectValueText(scipionObj),
                self._getObjectLabel(scipionObj),
                self._getObjectComment(scipionObj),
                self._getObjectCreation(scipionObj),
                self._jsonParam(metadata),
            ),
            commit=False,
        )
        objectId = int(cur.fetchone()["id"])
        storedPaths.append(path)

        if includeNestedProperties:
            for attrName, attrValue in attributes:
                self._storeObjectNode(
                    projectId=projectId,
                    protocolDbId=protocolDbId,
                    scipionObj=attrValue,
                    name=attrName,
                    path=f"{path}.{attrName}",
                    parentObjectId=objectId,
                    storedPaths=storedPaths,
                    includeNestedProperties=includeNestedProperties,
                    visited=visited,
                    scipionObjectIdsByPath=scipionObjectIdsByPath,
                )

        visited.discard(objIdentity)

        return objectId

    def _iterProperties(
        self,
        scipionObj: Any,
        prefix: str = "",
        includeNestedProperties: bool = True,
        visited: Optional[Set[int]] = None,
    ) -> Iterable[Dict[str, Any]]:
        visited = visited or set()
        objIdentity = id(scipionObj)
        if objIdentity in visited:
            return
        visited.add(objIdentity)

        for attrName, attrValue in self._getAttributesToStore(scipionObj):
            propertyPath = f"{prefix}.{attrName}" if prefix else str(attrName)
            childAttributes = self._getAttributesToStore(attrValue)
            isPointer = self._isPointer(attrValue)
            isNested = bool(childAttributes)
            yield {
                "propertyPath": propertyPath,
                "className": self._getClassName(attrValue),
                "valueKind": self._getValueKind(attrValue, isPointer=isPointer, isNested=isNested),
                "isPointer": isPointer,
                "isNested": isNested,
                "schema": {
                    "moduleName": self._getModuleName(attrValue),
                    "baseClassName": self._getBaseClassName(attrValue),
                },
            }
            if includeNestedProperties and isNested:
                yield from self._iterProperties(
                    attrValue,
                    prefix=propertyPath,
                    includeNestedProperties=includeNestedProperties,
                    visited=visited,
                )

        visited.discard(objIdentity)

    def _getAttributesToStore(
            self,
            scipionObj: Any,
    ) -> List[Tuple[str, Any]]:
        getter = getattr(
            scipionObj,
            "getAttributesToStore",
            None,
        )

        if not callable(getter):
            return []

        try:
            return [
                (str(name), value)
                for name, value in getter()
                if str(name)
                   not in self.RUNTIME_ONLY_ATTRIBUTE_NAMES
            ]
        except Exception:
            return []

    def _getClassName(self, scipionObj: Any) -> Optional[str]:
        getter = getattr(scipionObj, "getClassName", None)
        if callable(getter):
            try:
                className = getter()
                if className:
                    return str(className)
            except Exception:
                pass
        if scipionObj is None:
            return None
        return scipionObj.__class__.__name__

    def _getModuleName(self, scipionObj: Any) -> Optional[str]:
        if scipionObj is None:
            return None
        moduleName = getattr(scipionObj.__class__, "__module__", None)
        return str(moduleName) if moduleName else None

    def _getBaseClassName(self, scipionObj: Any) -> Optional[str]:
        if scipionObj is None:
            return None
        bases = getattr(scipionObj.__class__, "__bases__", None) or []
        return bases[0].__name__ if bases else None

    def _guessMapperKind(self, scipionObj: Any) -> str:
        className = self._getClassName(scipionObj) or ""
        if self._isPointer(scipionObj):
            return "pointer"
        if className.startswith("SetOf") or "SetOf" in className:
            return "flat_set"
        if self._getAttributesToStore(scipionObj):
            return "tree"
        return "scalar"

    def _getValueKind(self, scipionObj: Any, isPointer: bool, isNested: bool) -> str:
        if isPointer:
            return "pointer"
        if isNested:
            return "object"
        return self._getClassName(scipionObj) or "scalar"

    def _getSourceObjId(self, scipionObj: Any) -> Optional[int]:
        for getterName in ("getObjId", "getId"):
            getter = getattr(scipionObj, getterName, None)
            if not callable(getter):
                continue
            try:
                value = getter()
            except Exception:
                continue
            if value is None:
                continue
            try:
                return int(value)
            except Exception:
                continue
        return None

    def _getScipionObjId(self, scipionObj: Any, path: str) -> Optional[int]:
        return self._getSourceObjId(scipionObj)

    def _serializePointerReference(self, pointer) -> Dict[str, Any]:
        targetObject = None

        try:
            if pointer.hasValue():
                targetObject = pointer.getObjValue()
        except Exception:
            targetObject = None

        targetParent = None

        if targetObject is not None:
            getObjParent = getattr(targetObject, "getObjParent", None)

            if callable(getObjParent):
                try:
                    targetParent = getObjParent()
                except Exception:
                    targetParent = None

            if targetParent is None:
                targetParent = getattr(targetObject, "_objParent", None)

        targetObjectId = self._getSourceObjId(targetObject)
        targetParentObjectId = self._getSourceObjId(targetParent)

        if targetParentObjectId is None and targetObject is not None:
            getObjParentId = getattr(targetObject, "getObjParentId", None)

            if callable(getObjParentId):
                try:
                    parentObjectId = getObjParentId()
                    targetParentObjectId = int(parentObjectId) if parentObjectId not in (None, "") else None
                except Exception:
                    targetParentObjectId = None

        extended = ""

        getExtended = getattr(pointer, "getExtended", None)

        if callable(getExtended):
            try:
                extended = str(getExtended() or "")
            except Exception:
                extended = ""

        uniqueId = None

        getUniqueId = getattr(pointer, "getUniqueId", None)

        if callable(getUniqueId):
            try:
                value = getUniqueId()
                uniqueId = str(value) if value else None
            except Exception:
                uniqueId = None

        targetObjectName = None

        if targetObject is not None:
            getObjName = getattr(targetObject, "getObjName", None)

            if callable(getObjName):
                try:
                    value = getObjName()
                    targetObjectName = str(value) if value else None
                except Exception:
                    targetObjectName = None

        return {
            "version": 1,
            "kind": "pointer",
            "targetObjectId": targetObjectId,
            "targetClassName": self._getClassName(targetObject) if targetObject is not None else None,
            "targetObjectName": targetObjectName,
            "targetParentObjectId": targetParentObjectId,
            "targetParentClassName": self._getClassName(targetParent) if targetParent is not None else None,
            "extended": extended,
            "uniqueId": uniqueId,
        }

    def _getObjectValueText(self, scipionObj: Any) -> Optional[str]:
        if self._isPointer(scipionObj):
            pointedObj = self._getPointerValue(scipionObj)
            pointedId = self._getSourceObjId(pointedObj)
            if pointedId is not None:
                return str(pointedId)
            if pointedObj is not None:
                return str(pointedObj)

        value = None
        for methodName in ("getObjValue", "get"):
            getter = getattr(scipionObj, methodName, None)
            if not callable(getter):
                continue
            try:
                value = getter()
                break
            except Exception:
                continue

        if value is None:
            return None
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _getPointerValue(self, scipionObj: Any) -> Any:
        hasValue = getattr(scipionObj, "hasValue", None)
        if callable(hasValue):
            try:
                if not hasValue():
                    return None
            except Exception:
                return None
        getter = getattr(scipionObj, "get", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _getObjectLabel(self, scipionObj: Any) -> Optional[str]:
        return self._getOptionalObjectText(scipionObj, "getObjLabel", "_objLabel")

    def _getObjectComment(self, scipionObj: Any) -> Optional[str]:
        return self._getOptionalObjectText(scipionObj, "getObjComment", "_objComment")

    def _getObjectCreation(self, scipionObj: Any) -> Any:
        getter = getattr(scipionObj, "getObjCreation", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                pass
        return getattr(scipionObj, "_objCreation", None)

    def _getObjectDisplayText(self, scipionObj: Any) -> Optional[str]:
        if scipionObj is None:
            return None

        try:
            text = str(scipionObj)
        except Exception:
            return None

        text = str(text or "").strip()
        return text or None

    def _getObjectFileName(self, scipionObj: Any) -> Optional[str]:
        getter = getattr(scipionObj, "getFileName", None)
        if not callable(getter):
            return None

        try:
            value = getter()
        except Exception:
            return None

        text = str(value or "").strip()
        return text or None

    def _getOptionalObjectText(self, scipionObj: Any, getterName: str, attributeName: str) -> Optional[str]:
        getter = getattr(scipionObj, getterName, None)
        if callable(getter):
            try:
                value = getter()
                return str(value) if value else None
            except Exception:
                pass
        value = getattr(scipionObj, attributeName, None)
        return str(value) if value else None

    def _isPointer(self, scipionObj: Any) -> bool:
        checker = getattr(scipionObj, "isPointer", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _jsonParam(self, value: Dict[str, Any]) -> Any:
        return psycopg2.extras.Json(value or {}, dumps=json.dumps)
