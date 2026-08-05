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
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


class PostgresqlSetRuntimeMapper:
    """
    Read-only mapper exposing the subset of the SqliteFlatMapper API used by
    pyworkflow.object.Set.

    The mapper supports both:

    - Root set items stored in scipion_set_items/scipion_set_columns.
    - Nested logical-table items stored in
      scipion_set_table_items/scipion_set_table_columns.

    Rows are converted into native Scipion objects by itemBuilder. Runtime
    reads never write into the original Scipion output set; PostgreSQL
    snapshots are persisted by ScipionSetPostgresqlMapper.
    """

    ROOT_ITEMS_TABLE = "scipion_set_items"
    ROOT_COLUMNS_TABLE = "scipion_set_columns"

    LOGICAL_ITEMS_TABLE = "scipion_set_table_items"
    LOGICAL_COLUMNS_TABLE = "scipion_set_table_columns"

    STREAMING_CREATION_EXPRESSION = (
        "("
        "TIMESTAMP '2000-01-01 00:00:00' "
        '+ "scipionItemId" '
        "* INTERVAL '1 microsecond'"
        ")"
    )

    ID_FIELDS = {
        "id",
        "_objId",
        "objId",
        "scipionItemId",
    }

    DIRECT_FIELDS = {
        "enabled": "enabled",
        "label": "label",
        "comment": "comment",
    }

    WHERE_PART_PATTERN = re.compile(
        r"""^\s*
            (?P<field>[A-Za-z_][A-Za-z0-9_.]*)
            \s*(?P<operator><=|>=|!=|<>|==|=|<|>)\s*
            (?P<value>.+?)
            \s*$
        """,
        re.VERBOSE,
    )

    def __init__(
            self,
            db,
            setId: Optional[int] = None,
            rootTableId: Optional[int] = None,
            itemBuilder: Optional[
                Callable[[Dict[str, Any]], Any]
            ] = None,
            tableId: Optional[int] = None,
            tableIdResolver: Optional[
                Callable[[], Optional[int]]
            ] = None,
            parentItemId: Optional[int] = None,
            itemSerializer: Optional[
                Callable[[Any], Dict[str, Any]]
            ] = None,
            itemSchemaSynchronizer: Optional[
                Callable[[Any], Dict[str, Any]]
            ] = None,
            itemColumnsUpdater: Optional[
                Callable[
                    [List[Dict[str, Any]]],
                    None,
                ]
            ] = None,
            nestedItemSynchronizer: Optional[
                Callable[
                    [Any, int],
                    Optional[Dict[str, Any]],
                ]
            ] = None,
            writable: bool = False,
    ):
        if db is None:
            raise ValueError("db is required")

        if not callable(itemBuilder):
            raise ValueError("itemBuilder must be callable")

        if (
                tableIdResolver is not None
                and not callable(tableIdResolver)
        ):
            raise ValueError(
                "tableIdResolver must be callable or None"
            )

        if (
                itemSchemaSynchronizer
                is not None
                and not callable(
            itemSchemaSynchronizer
        )
        ):
            raise ValueError(
                "itemSchemaSynchronizer must "
                "be callable or None."
            )

        if (
                itemColumnsUpdater
                is not None
                and not callable(
            itemColumnsUpdater
        )
        ):
            raise ValueError(
                "itemColumnsUpdater must "
                "be callable or None."
            )

        if (
                nestedItemSynchronizer
                is not None
                and not callable(
            nestedItemSynchronizer
        )
        ):
            raise ValueError(
                "nestedItemSynchronizer must "
                "be callable or None."
            )

        hasSetId = setId is not None
        hasTableId = tableId is not None

        if (
                nestedItemSynchronizer
                is not None
                and not hasSetId
        ):
            raise ValueError(
                "nestedItemSynchronizer is only "
                "supported for root PostgreSQL Sets."
            )

        if (
                rootTableId is not None
                and not hasSetId
        ):
            raise ValueError(
                "rootTableId is only supported "
                "for root PostgreSQL Sets."
            )

        if (
                writable
                and hasSetId
                and rootTableId is None
        ):
            raise ValueError(
                "rootTableId is required for "
                "writable PostgreSQL root Sets."
            )

        if (
                parentItemId is not None
                and not hasTableId
        ):
            raise ValueError(
                "parentItemId is only supported for "
                "PostgreSQL logical-table Sets."
            )

        if (
                writable
                and hasTableId
                and parentItemId is None
        ):
            raise ValueError(
                "parentItemId is required for writable "
                "PostgreSQL logical-table Sets."
            )

        if (
                writable
                and not callable(
            itemSerializer
        )
        ):
            raise ValueError(
                "itemSerializer is required for "
                "writable PostgreSQL Sets."
            )

        if hasSetId == hasTableId:
            raise ValueError(
                "Exactly one of setId or tableId is required"
            )

        if (
                hasSetId
                and tableIdResolver is not None
        ):
            raise ValueError(
                "tableIdResolver is only supported "
                "for logical-table mappers"
            )

        self.tableIdResolver = (
            tableIdResolver
        )

        self.db = db

        self.setId = (
            int(setId)
            if hasSetId
            else None
        )

        self.rootTableId = (
            int(rootTableId)
            if rootTableId is not None
            else None
        )

        self.tableId = (
            int(tableId)
            if hasTableId
            else None
        )

        self.parentItemId = (
            int(parentItemId)
            if parentItemId is not None
            else None
        )

        self.itemBuilder = itemBuilder

        self.itemSerializer = (
            itemSerializer
        )
        self.itemSchemaSynchronizer = (
            itemSchemaSynchronizer
        )
        self.itemColumnsUpdater = (
            itemColumnsUpdater
        )
        self.nestedItemSynchronizer = (
            nestedItemSynchronizer
        )
        self.writable = bool(
            writable
        )

        if self.setId is not None:
            self._scopeId = self.setId
            self._scopeColumn = "setId"
            self._itemsTable = self.ROOT_ITEMS_TABLE
            self._columnsTable = self.ROOT_COLUMNS_TABLE
            self._parentItemExpression = (
                'NULL AS "parentItemId"'
            )
            self._tableProperties = {}
        else:
            self._scopeId = self.tableId
            self._scopeColumn = "tableId"
            self._itemsTable = self.LOGICAL_ITEMS_TABLE
            self._columnsTable = self.LOGICAL_COLUMNS_TABLE
            self._parentItemExpression = '"parentItemId"'
            self._tableProperties = (
                self._loadLogicalTableProperties()
            )

        self._columns = self._loadColumns()
        self._itemSchemaReady = bool(self._columns)
        self._dynamicFieldValueTypes = {}

    def _refreshLogicalTableScope(
            self,
    ) -> bool:
        if (
                self.tableId is None
                or not callable(
                    self.tableIdResolver
                )
        ):
            return False

        currentTableId = (
            self.tableIdResolver()
        )

        if currentTableId in (
                None,
                "",
        ):
            return False

        currentTableId = int(
            currentTableId
        )

        if currentTableId == int(
                self.tableId
        ):
            return False

        self.tableId = currentTableId
        self._scopeId = currentTableId

        # The recreated logical table can have new
        # properties and column rows as well.
        self._tableProperties = (
            self._loadLogicalTableProperties()
        )

        self._replaceColumns(
            self._loadColumns()
        )

        return True

    # ------------------------------------------------------------------
    # pyworkflow.object.Set read contract
    # ------------------------------------------------------------------

    def selectAll(
            self,
            orderBy="id",
            direction="ASC",
            where=None,
            limit=None,
            iterate=True,
            rowFilter=None,
    ):
        self._refreshReadSchema()

        whereSql, whereParams = self._buildWhere(
            where
        )

        orderSql, orderParams = self._buildOrderBy(
            orderBy,
            direction,
        )

        query = self._buildItemsSelectQuery()

        params: List[Any] = [
            self._scopeId,
        ]

        if whereSql:
            query += "\n AND " + whereSql
            params.extend(
                whereParams
            )

        if orderSql:
            query += "\n ORDER BY " + orderSql
            params.extend(
                orderParams
            )

        if limit is not None:
            query += "\n LIMIT %s"
            params.append(
                int(limit)
            )

        rows = self.db.fetchAll(
            query,
            tuple(params),
        )

        items = self._buildItems(
            rows,
            rowFilter=rowFilter,
        )

        if iterate:
            return iter(items)

        return items

    def selectFirst(self):
        items = self.selectAll(
            orderBy="id",
            direction="ASC",
            limit=1,
            iterate=False,
        )

        return (
            items[0]
            if items
            else None
        )

    def selectById(self, itemId):
        self._refreshReadSchema()

        query = (
            self._buildItemsSelectQuery()
            + """
               AND "scipionItemId" = %s
             LIMIT 1
            """
        )

        row = self.db.fetchOne(
            query,
            (
                self._scopeId,
                int(itemId),
            ),
        )

        return (
            self.itemBuilder(
                dict(row)
            )
            if row
            else None
        )

    def selectBy(
            self,
            iterate=True,
            objectFilter=None,
            **conditions,
    ):
        self._refreshReadSchema()

        if not conditions:
            return self.selectAll(
                iterate=iterate,
                rowFilter=objectFilter,
            )

        clauses = []

        params: List[Any] = [
            self._scopeId,
        ]

        for field, value in conditions.items():
            expression, expressionParams = (
                self._fieldExpression(
                    field
                )
            )

            clauses.append(
                "%s = %%s"
                % expression
            )

            params.extend(
                expressionParams
            )

            params.append(
                self._normalizeFieldValue(
                    field,
                    value,
                )
            )

        query = self._buildItemsSelectQuery()

        query += (
            "\n AND "
            + " AND ".join(clauses)
            + '\n ORDER BY "scipionItemId" ASC'
        )

        rows = self.db.fetchAll(
            query,
            tuple(params),
        )

        items = self._buildItems(
            rows,
            rowFilter=objectFilter,
        )

        if iterate:
            return iter(items)

        return items

    def exists(self, itemId):
        self._refreshLogicalTableScope()
        query = """
            SELECT 1
              FROM {itemsTable}
             WHERE "{scopeColumn}" = %s
               AND "scipionItemId" = %s
             LIMIT 1
        """.format(
            itemsTable=self._itemsTable,
            scopeColumn=self._scopeColumn,
        )

        row = self.db.fetchOne(
            query,
            (
                self._scopeId,
                int(itemId),
            ),
        )

        return row is not None

    def count(self):
        self._refreshLogicalTableScope()
        query = """
            SELECT COUNT(*) AS count
              FROM {itemsTable}
             WHERE "{scopeColumn}" = %s
        """.format(
            itemsTable=self._itemsTable,
            scopeColumn=self._scopeColumn,
        )

        row = self.db.fetchOne(
            query,
            (self._scopeId,),
        )

        return (
            int(row.get("count") or 0)
            if row
            else 0
        )

    def maxId(self):
        self._refreshLogicalTableScope()
        query = """
            SELECT MAX("scipionItemId") AS "maxItemId"
              FROM {itemsTable}
             WHERE "{scopeColumn}" = %s
        """.format(
            itemsTable=self._itemsTable,
            scopeColumn=self._scopeColumn,
        )

        row = self.db.fetchOne(
            query,
            (self._scopeId,),
        )

        if (
                not row
                or row.get("maxItemId") is None
        ):
            return 0

        return int(
            row["maxItemId"]
        )

    def getRevisionToken(self):
        """
        Return a token that changes whenever the current
        PostgreSQL Set scope changes.

        For root Sets this also includes nested logical tables,
        so changes inside Classes, TiltSeries, CTF series, etc.
        invalidate the compatibility snapshot.
        """
        self._refreshLogicalTableScope()

        if self.setId is not None:
            row = self.db.fetchOne(
                """
                SELECT
                    s."updatedAt"
                        AS "scopeUpdatedAt",

                    COALESCE(
                        (
                            SELECT COUNT(*)
                              FROM scipion_set_items i
                             WHERE i."setId" = s.id
                        ),
                        0
                    ) AS "itemsCount",

                    COALESCE(
                        (
                            SELECT MAX(
                                i."scipionItemId"
                            )
                              FROM scipion_set_items i
                             WHERE i."setId" = s.id
                        ),
                        0
                    ) AS "maxItemId",

                    (
                        SELECT MAX(
                            i."updatedAt"
                        )
                          FROM scipion_set_items i
                         WHERE i."setId" = s.id
                    ) AS "itemsUpdatedAt",

                    (
                        SELECT MAX(
                            t."updatedAt"
                        )
                          FROM scipion_set_tables t
                         WHERE t."setId" = s.id
                    ) AS "tablesUpdatedAt",

                    (
                        SELECT MAX(
                            ti."updatedAt"
                        )
                          FROM scipion_set_table_items ti
                          JOIN scipion_set_tables t
                            ON t.id = ti."tableId"
                         WHERE t."setId" = s.id
                    ) AS "tableItemsUpdatedAt"

                  FROM scipion_sets s
                 WHERE s.id = %s
                """,
                (
                    int(self.setId),
                ),
            ) or {}

            return (
                "root",
                int(self.setId),
                int(
                    row.get(
                        "itemsCount"
                    )
                    or 0
                ),
                int(
                    row.get(
                        "maxItemId"
                    )
                    or 0
                ),
                str(
                    row.get(
                        "scopeUpdatedAt"
                    )
                    or ""
                ),
                str(
                    row.get(
                        "itemsUpdatedAt"
                    )
                    or ""
                ),
                str(
                    row.get(
                        "tablesUpdatedAt"
                    )
                    or ""
                ),
                str(
                    row.get(
                        "tableItemsUpdatedAt"
                    )
                    or ""
                ),
            )

        row = self.db.fetchOne(
            """
            SELECT
                t."updatedAt"
                    AS "scopeUpdatedAt",

                COALESCE(
                    (
                        SELECT COUNT(*)
                          FROM scipion_set_table_items i
                         WHERE i."tableId" = t.id
                    ),
                    0
                ) AS "itemsCount",

                COALESCE(
                    (
                        SELECT MAX(
                            i."scipionItemId"
                        )
                          FROM scipion_set_table_items i
                         WHERE i."tableId" = t.id
                    ),
                    0
                ) AS "maxItemId",

                (
                    SELECT MAX(
                        i."updatedAt"
                    )
                      FROM scipion_set_table_items i
                     WHERE i."tableId" = t.id
                ) AS "itemsUpdatedAt"

              FROM scipion_set_tables t
             WHERE t.id = %s
            """,
            (
                int(self.tableId),
            ),
        ) or {}

        return (
            "logical",
            int(self.tableId),
            int(
                row.get(
                    "itemsCount"
                )
                or 0
            ),
            int(
                row.get(
                    "maxItemId"
                )
                or 0
            ),
            str(
                row.get(
                    "scopeUpdatedAt"
                )
                or ""
            ),
            str(
                row.get(
                    "itemsUpdatedAt"
                )
                or ""
            ),
        )

    # ------------------------------------------------------------------
    # PostgreSQL write contract
    # ------------------------------------------------------------------

    def isWritable(self) -> bool:
        return self.writable

    def enableAppend(self) -> None:
        self._requireWritable()

    def appendItem(
            self,
            item,
    ) -> int:
        """
        Atomically allocate an item id and persist the item
        inside the current PostgreSQL storage scope.

        Root Sets allocate ids inside scipion_set_items.
        Nested Sets allocate ids inside their logical table.
        """
        self._requireWritable()

        with self.db.transaction():
            self.db.fetchOne(
                """
                SELECT pg_advisory_xact_lock(
                    %s
                ) AS locked
                """,
                (
                    self._getAdvisoryLockKey(),
                ),
            )

            itemId = self._getItemId(
                item
            )

            if itemId is None:
                query = """
                    SELECT
                        COALESCE(
                            MAX("scipionItemId"),
                            0
                        ) + 1 AS "nextItemId"
                      FROM {itemsTable}
                     WHERE "{scopeColumn}" = %s
                """.format(
                    itemsTable=self._itemsTable,
                    scopeColumn=self._scopeColumn,
                )

                row = self.db.fetchOne(
                    query,
                    (
                        int(self._scopeId),
                    ),
                )

                itemId = int(
                    row["nextItemId"]
                )

                self._setItemId(
                    item,
                    itemId,
                )

            self._upsertItem(
                item
            )

            self._refreshSetCounters()

        return int(
            itemId
        )

    def insert(
            self,
            item,
    ) -> None:
        """
        Insert an item whose id has already been assigned.

        Normal PostgreSQL appends should use appendItem()
        so id allocation remains concurrency-safe.
        """
        self._requireWritable()

        if self._getItemId(item) is None:
            raise ValueError(
                "PostgreSQL Set insert requires "
                "an existing item id. Use appendItem()."
            )

        with self.db.transaction():
            self._upsertItem(
                item
            )
            self._refreshSetCounters()

    def update(
            self,
            item,
    ) -> None:
        self._requireWritable()

        if self._getItemId(item) is None:
            raise ValueError(
                "PostgreSQL Set update requires "
                "an existing item id."
            )

        with self.db.transaction():
            self._upsertItem(
                item
            )
            self._refreshSetCounters()

    def delete(
            self,
            item,
    ) -> None:
        self._requireWritable()

        itemId = self._getItemId(
            item
        )

        if itemId is None:
            raise ValueError(
                "PostgreSQL Set delete requires "
                "an existing item id."
            )

        with self.db.transaction():
            if self.setId is not None:
                self.db.execute(
                    """
                    DELETE FROM scipion_set_tables
                     WHERE "setId" = %s
                       AND "parentTableId" = %s
                       AND "parentItemId" = %s
                       AND "tableKind" = 'child'
                    """,
                    (
                        int(self.setId),
                        int(self.rootTableId),
                        int(itemId),
                    ),
                    commit=False,
                )
                self.db.execute(
                    """
                    DELETE FROM scipion_set_table_items
                     WHERE "tableId" = %s
                       AND "scipionItemId" = %s
                    """,
                    (
                        int(self.rootTableId),
                        int(itemId),
                    ),
                    commit=False,
                )

                self.db.execute(
                    """
                    DELETE FROM scipion_set_items
                     WHERE "setId" = %s
                       AND "scipionItemId" = %s
                    """,
                    (
                        int(self.setId),
                        int(itemId),
                    ),
                    commit=False,
                )

            else:
                self.db.execute(
                    """
                    DELETE FROM scipion_set_table_items
                     WHERE "tableId" = %s
                       AND "scipionItemId" = %s
                    """,
                    (
                        int(self.tableId),
                        int(itemId),
                    ),
                    commit=False,
                )

            self._refreshSetCounters()

    def clear(self) -> None:
        self._requireWritable()

        with self.db.transaction():
            if self.setId is not None:
                self.db.execute(
                    """
                    DELETE FROM scipion_set_tables
                     WHERE "setId" = %s
                       AND "parentTableId" = %s
                       AND "tableKind" = 'child'
                    """,
                    (
                        int(self.setId),
                        int(self.rootTableId),
                    ),
                    commit=False,
                )
                self.db.execute(
                    """
                    DELETE FROM scipion_set_table_items
                     WHERE "tableId" = %s
                    """,
                    (
                        int(self.rootTableId),
                    ),
                    commit=False,
                )

                self.db.execute(
                    """
                    DELETE FROM scipion_set_items
                     WHERE "setId" = %s
                    """,
                    (
                        int(self.setId),
                    ),
                    commit=False,
                )

            else:
                self.db.execute(
                    """
                    DELETE FROM scipion_set_table_items
                     WHERE "tableId" = %s
                    """,
                    (
                        int(self.tableId),
                    ),
                    commit=False,
                )

            self._refreshSetCounters()

    def setProperty(
            self,
            key,
            value,
    ) -> None:
        self._requireWritable()

        jsonValue = json.dumps(
            value,
            default=str,
        )

        propertyValue = (
            None
            if value is None
            else (
                jsonValue
                if isinstance(
                    value,
                    (
                        dict,
                        list,
                        tuple,
                    ),
                )
                else str(value)
            )
        )

        if self.tableId is not None:
            self.db.execute(
                """
                UPDATE scipion_set_tables
                   SET properties = (
                           COALESCE(
                               properties,
                               '{}'::jsonb
                           )
                           || jsonb_build_object(
                               %s,
                               %s::jsonb
                           )
                       ),
                       "updatedAt" = NOW()
                 WHERE id = %s
                """,
                (
                    str(key),
                    jsonValue,
                    int(self.tableId),
                ),
                commit=False,
            )

            self._tableProperties[
                str(key)
            ] = value

            return

        self.db.execute(
            """
            INSERT INTO scipion_set_properties (
                "setId",
                key,
                value
            )
            VALUES (
                %s,
                %s,
                %s
            )
            ON CONFLICT (
                "setId",
                key
            )
            DO UPDATE SET
                value = EXCLUDED.value
            """,
            (
                int(self.setId),
                str(key),
                propertyValue,
            ),
            commit=False,
        )

        self.db.execute(
            """
            UPDATE scipion_sets
               SET properties = (
                       COALESCE(
                           properties,
                           '{}'::jsonb
                       )
                       || jsonb_build_object(
                           %s,
                           %s::jsonb
                       )
                   ),
                   "updatedAt" = NOW()
             WHERE id = %s
            """,
            (
                str(key),
                jsonValue,
                int(self.setId),
            ),
            commit=False,
        )

    def deleteProperty(
            self,
            key,
    ) -> None:
        self._requireWritable()

        if self.tableId is not None:
            self.db.execute(
                """
                UPDATE scipion_set_tables
                   SET properties = (
                           COALESCE(
                               properties,
                               '{}'::jsonb
                           )
                           - %s
                       ),
                       "updatedAt" = NOW()
                 WHERE id = %s
                """,
                (
                    str(key),
                    int(self.tableId),
                ),
                commit=False,
            )

            self._tableProperties.pop(
                str(key),
                None,
            )

            return

        self.db.execute(
            """
            DELETE FROM scipion_set_properties
             WHERE "setId" = %s
               AND key = %s
            """,
            (
                int(self.setId),
                str(key),
            ),
            commit=False,
        )

        self.db.execute(
            """
            UPDATE scipion_sets
               SET properties = (
                       COALESCE(
                           properties,
                           '{}'::jsonb
                       )
                       - %s
                   ),
                   "updatedAt" = NOW()
             WHERE id = %s
            """,
            (
                str(key),
                int(self.setId),
            ),
            commit=False,
        )

    def commit(self) -> None:
        self._requireWritable()
        self.db.conn.commit()

    def close(self) -> None:
        """
        The PostgreSQL connection belongs to the project mapper.

        Closing one runtime Set must not close the shared
        project-level PostgreSQL connection.
        """
        return None

    def _requireWritable(self) -> None:
        if not self.writable:
            raise RuntimeError(
                "PostgreSQL runtime Set is read-only."
            )

        if self.tableId is not None:
            self._refreshLogicalTableScope()

        if self._scopeId is None:
            raise RuntimeError(
                "Writable PostgreSQL Set does not "
                "have an active storage scope."
            )

        if (
                self.setId is not None
                and self.rootTableId is None
        ):
            raise RuntimeError(
                "Writable PostgreSQL root Set does not "
                "have a root logical table."
            )

        if (
                self.tableId is not None
                and self.parentItemId is None
        ):
            raise RuntimeError(
                "Writable PostgreSQL logical-table Set "
                "does not have a parent item id."
            )

    def _getAdvisoryLockKey(
            self,
    ) -> int:
        """
        Keep root and logical-table lock namespaces separate.

        PostgreSQL identifiers are positive, so negative table
        ids cannot collide with root Set ids.
        """
        if self.setId is not None:
            return int(
                self.setId
            )

        return -int(
            self.tableId
        )

    def _getItemId(
            self,
            item,
    ) -> Optional[int]:
        getter = getattr(
            item,
            "getObjId",
            None,
        )

        if not callable(getter):
            return None

        value = getter()

        if value in (
                None,
                "",
        ):
            return None

        return int(
            value
        )

    def _setItemId(
            self,
            item,
            itemId: int,
    ) -> None:
        setter = getattr(
            item,
            "setObjId",
            None,
        )

        if not callable(setter):
            raise TypeError(
                "Runtime Set item does not expose "
                "setObjId()."
            )

        setter(
            int(itemId)
        )

    def _ensureItemSchema(
            self,
            item,
            serialized: Dict[str, Any],
    ) -> None:
        serializedSchema = serialized.get(
            "_schema"
        )

        hasSerializedSchema = isinstance(
            serializedSchema,
            dict,
        )

        requiredPaths = {
            str(path)
            for path in (
                    serializedSchema or {}
            )
            if str(path) != "self"
        }

        if self._itemSchemaReady:
            # Third-party/custom serializers may not expose _schema.
            # Preserve the previous one-time synchronization contract
            # for those serializers.
            if not hasSerializedSchema:
                return

            # The existing Set schema already covers this item.
            if requiredPaths.issubset(
                    self._columns
            ):
                return

        synchronizer = (
            self.itemSchemaSynchronizer
        )

        if not callable(
                synchronizer
        ):
            raise RuntimeError(
                "Writable PostgreSQL Set does not "
                "have an item schema synchronizer."
            )

        schemaInfo = dict(
            synchronizer(
                item
            )
            or {}
        )

        columns = schemaInfo.get(
            "columns"
        )

        if columns is None:
            raise RuntimeError(
                "PostgreSQL item schema "
                "synchronizer did not return columns."
            )

        self._replaceColumns(
            columns
        )

        # Empty schemas are valid. This flag records that
        # synchronization completed successfully.
        self._itemSchemaReady = True

        missingPaths = (
                requiredPaths
                - set(
            self._columns
        )
        )

        if missingPaths:
            raise RuntimeError(
                "PostgreSQL item schema synchronization "
                "did not persist all Scipion paths. "
                "missingPaths=%s"
                % sorted(
                    missingPaths
                )
            )

    def _serializeItem(
            self,
            item,
    ) -> Dict[str, Any]:
        self._requireWritable()

        serialized = dict(
            self.itemSerializer(
                item
            )
            or {}
        )

        itemId = serialized.get(
            "scipionItemId"
        )

        if itemId in (
                None,
                "",
        ):
            raise ValueError(
                "Serialized PostgreSQL Set item "
                "does not contain scipionItemId."
            )

        serialized[
            "scipionItemId"
        ] = int(
            itemId
        )

        serialized[
            "values"
        ] = dict(
            serialized.get(
                "values"
            )
            or {}
        )

        return serialized

    def _upsertItem(
            self,
            item,
    ) -> None:
        serialized = self._serializeItem(
            item
        )

        self._ensureItemSchema(
            item=item,
            serialized=serialized,
        )

        itemId = int(
            serialized[
                "scipionItemId"
            ]
        )

        enabled = bool(
            serialized.get(
                "enabled",
                True,
            )
        )

        label = serialized.get(
            "label"
        )

        comment = serialized.get(
            "comment"
        )

        creation = serialized.get(
            "creation"
        )

        jsonValues = json.dumps(
            serialized.get(
                "values"
            )
            or {},
            default=str,
        )

        if self.setId is not None:
            self._upsertRootItem(
                itemId=itemId,
                enabled=enabled,
                label=label,
                comment=comment,
                creation=creation,
                jsonValues=jsonValues,
            )

            if (
                    self.nestedItemSynchronizer
                    is not None
            ):
                self.nestedItemSynchronizer(
                    item,
                    int(itemId),
                )

        else:
            self._upsertLogicalItem(
                itemId=itemId,
                enabled=enabled,
                label=label,
                comment=comment,
                creation=creation,
                jsonValues=jsonValues,
            )

    def _upsertRootItem(
            self,
            *,
            itemId: int,
            enabled: bool,
            label,
            comment,
            creation,
            jsonValues: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO scipion_set_items (
                "setId",
                "scipionItemId",
                enabled,
                label,
                comment,
                creation,
                "values"
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb
            )
            ON CONFLICT ON CONSTRAINT
                ux_scipion_set_items_set_item
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                label = EXCLUDED.label,
                comment = EXCLUDED.comment,
                creation = EXCLUDED.creation,
                "values" = EXCLUDED."values",
                "updatedAt" = NOW()
            """,
            (
                int(self.setId),
                int(itemId),
                enabled,
                label,
                comment,
                creation,
                jsonValues,
            ),
            commit=False,
        )

        self.db.execute(
            """
            INSERT INTO scipion_set_table_items (
                "tableId",
                "scipionItemId",
                "parentItemId",
                enabled,
                label,
                comment,
                creation,
                "values"
            )
            VALUES (
                %s,
                %s,
                NULL,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb
            )
            ON CONFLICT ON CONSTRAINT
                ux_scipion_set_table_items_table_item
            DO UPDATE SET
                "parentItemId" = NULL,
                enabled = EXCLUDED.enabled,
                label = EXCLUDED.label,
                comment = EXCLUDED.comment,
                creation = EXCLUDED.creation,
                "values" = EXCLUDED."values",
                "updatedAt" = NOW()
            """,
            (
                int(self.rootTableId),
                int(itemId),
                enabled,
                label,
                comment,
                creation,
                jsonValues,
            ),
            commit=False,
        )

    def _upsertLogicalItem(
            self,
            *,
            itemId: int,
            enabled: bool,
            label,
            comment,
            creation,
            jsonValues: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO scipion_set_table_items (
                "tableId",
                "scipionItemId",
                "parentItemId",
                enabled,
                label,
                comment,
                creation,
                "values"
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb
            )
            ON CONFLICT ON CONSTRAINT
                ux_scipion_set_table_items_table_item
            DO UPDATE SET
                "parentItemId" =
                    EXCLUDED."parentItemId",
                enabled = EXCLUDED.enabled,
                label = EXCLUDED.label,
                comment = EXCLUDED.comment,
                creation = EXCLUDED.creation,
                "values" = EXCLUDED."values",
                "updatedAt" = NOW()
            """,
            (
                int(self.tableId),
                int(itemId),
                int(self.parentItemId),
                enabled,
                label,
                comment,
                creation,
                jsonValues,
            ),
            commit=False,
        )

    def _refreshSetCounters(
            self,
    ) -> None:
        query = """
            SELECT
                COUNT(*) AS "itemsCount",
                MAX(
                    "scipionItemId"
                ) AS "maxItemId"
              FROM {itemsTable}
             WHERE "{scopeColumn}" = %s
        """.format(
            itemsTable=self._itemsTable,
            scopeColumn=self._scopeColumn,
        )

        row = self.db.fetchOne(
            query,
            (
                int(self._scopeId),
            ),
        ) or {}

        itemsCount = int(
            row.get(
                "itemsCount"
            )
            or 0
        )

        maxItemId = row.get(
            "maxItemId"
        )

        normalizedMaxItemId = (
            int(maxItemId)
            if maxItemId is not None
            else None
        )

        if self.setId is not None:
            self.db.execute(
                """
                UPDATE scipion_sets
                   SET properties = (
                           COALESCE(
                               properties,
                               '{}'::jsonb
                           )
                           || jsonb_build_object(
                               'itemsCount',
                               %s,
                               'maxItemId',
                               %s,
                               'incremental',
                               TRUE
                           )
                       ),
                       "updatedAt" = NOW()
                 WHERE id = %s
                """,
                (
                    itemsCount,
                    normalizedMaxItemId,
                    int(self.setId),
                ),
                commit=False,
            )

            self.db.execute(
                """
                UPDATE scipion_set_tables
                   SET properties = (
                           COALESCE(
                               properties,
                               '{}'::jsonb
                           )
                           || jsonb_build_object(
                               'itemsCount',
                               %s,
                               'maxItemId',
                               %s,
                               'incremental',
                               TRUE
                           )
                       ),
                       "updatedAt" = NOW()
                 WHERE id = %s
                   AND "setId" = %s
                   AND "tableKind" = 'root'
                """,
                (
                    itemsCount,
                    normalizedMaxItemId,
                    int(self.rootTableId),
                    int(self.setId),
                ),
                commit=False,
            )

            return

        self.db.execute(
            """
            UPDATE scipion_set_tables
               SET properties = (
                       COALESCE(
                           properties,
                           '{}'::jsonb
                       )
                       || jsonb_build_object(
                           'itemsCount',
                           %s,
                           'maxItemId',
                           %s,
                           'incremental',
                           TRUE
                       )
                   ),
                   "updatedAt" = NOW()
             WHERE id = %s
            """,
            (
                itemsCount,
                normalizedMaxItemId,
                int(self.tableId),
            ),
            commit=False,
        )

        self._tableProperties.update({
            "itemsCount": itemsCount,
            "maxItemId": normalizedMaxItemId,
            "incremental": True,
        })

    # ------------------------------------------------------------------
    # Set properties
    # ------------------------------------------------------------------

    def hasProperty(self, key):
        self._refreshLogicalTableScope()
        if self.tableId is not None:
            return (
                str(key)
                in self._tableProperties
            )

        row = self.db.fetchOne(
            """
            SELECT 1
              FROM scipion_set_properties
             WHERE "setId" = %s
               AND key = %s
             LIMIT 1
            """,
            (
                self.setId,
                str(key),
            ),
        )

        return row is not None

    def getProperty(
            self,
            key,
            defaultValue=None,
    ):
        self._refreshLogicalTableScope()
        if self.tableId is not None:
            return self._tableProperties.get(
                str(key),
                defaultValue,
            )

        row = self.db.fetchOne(
            """
            SELECT value
              FROM scipion_set_properties
             WHERE "setId" = %s
               AND key = %s
             LIMIT 1
            """,
            (
                self.setId,
                str(key),
            ),
        )

        return (
            row.get("value")
            if row
            else defaultValue
        )

    def getPropertyKeys(self):
        self._refreshLogicalTableScope()
        if self.tableId is not None:
            return sorted(
                self._tableProperties
            )

        rows = self.db.fetchAll(
            """
            SELECT key
              FROM scipion_set_properties
             WHERE "setId" = %s
             ORDER BY key ASC
            """,
            (self.setId,),
        )

        return [
            row["key"]
            for row in rows or []
        ]

    def refreshProperties(self):
        """
        Refresh properties cached by logical-table mappers.

        Root Set properties are queried directly from PostgreSQL
        and therefore do not need a local refresh.
        """
        self._refreshLogicalTableScope()

        if self.tableId is not None:
            self._tableProperties = (
                self._loadLogicalTableProperties()
            )
    # ------------------------------------------------------------------
    # Pending mapper operations
    # ------------------------------------------------------------------

    def aggregate(
            self,
            operations,
            operationLabel,
            groupByLabels=None,
    ):
        """
        Execute read-only aggregate queries over PostgreSQL Set snapshots.

        The returned rows follow the SqliteFlatMapper contract used by
        pyworkflow.object.Set.aggregate().
        """
        self._refreshReadSchema()

        operations = self._normalizeAggregateArguments(
            operations
        )

        operationLabels = (
            self._normalizeAggregateArguments(
                operationLabel
            )
        )

        groupByLabels = (
            self._normalizeAggregateArguments(
                groupByLabels
            )
        )

        if not operations:
            raise ValueError(
                "At least one aggregate operation is required"
            )

        if not operationLabels:
            raise ValueError(
                "At least one aggregate operation label is required"
            )

        selectParts = []
        selectParams = []

        for labelIndex, label in enumerate(
                operationLabels
        ):
            label = str(label)

            expression, expressionParams = (
                self._fieldExpression(
                    label
                )
            )

            for operation in operations:
                operationText = str(
                    operation
                ).strip()

                normalizedOperation = (
                    operationText.lower()
                )

                aggregateExpression = (
                    self._buildAggregateExpression(
                        operation=normalizedOperation,
                        expression=expression,
                    )
                )

                if labelIndex == 0:
                    alias = operationText
                else:
                    alias = (
                            operationText
                            + label
                    )

                selectParts.append(
                    "%s AS %s"
                    % (
                        aggregateExpression,
                        self._quoteSqlIdentifier(
                            alias
                        ),
                    )
                )

                selectParams.extend(
                    expressionParams
                )

        aggregateColumnsCount = len(
            selectParts
        )

        groupByOrdinals = []

        for groupIndex, groupByLabel in enumerate(
                groupByLabels
        ):
            groupByLabel = str(
                groupByLabel
            )

            expression, expressionParams = (
                self._fieldExpression(
                    groupByLabel
                )
            )

            selectParts.append(
                "%s AS %s"
                % (
                    expression,
                    self._quoteSqlIdentifier(
                        groupByLabel
                    ),
                )
            )

            selectParams.extend(
                expressionParams
            )

            groupByOrdinals.append(
                aggregateColumnsCount
                + groupIndex
                + 1
            )

        query = """
            SELECT {selectParts}
              FROM {itemsTable}
             WHERE "{scopeColumn}" = %s
        """.format(
            selectParts=", ".join(
                selectParts
            ),
            itemsTable=self._itemsTable,
            scopeColumn=self._scopeColumn,
        )

        params = list(
            selectParams
        )

        params.append(
            self._scopeId
        )

        if groupByOrdinals:
            query += (
                    "\n GROUP BY "
                    + ", ".join(
                str(ordinal)
                for ordinal
                in groupByOrdinals
            )
            )

        rows = self.db.fetchAll(
            query,
            tuple(params),
        )

        return [
            dict(row)
            for row in rows or []
        ]

    @staticmethod
    def _normalizeAggregateArguments(
            value,
    ) -> List[Any]:
        if value is None:
            return []

        if isinstance(
                value,
                (list, tuple),
        ):
            return list(value)

        return [value]

    @staticmethod
    def _quoteSqlIdentifier(
            value,
    ) -> str:
        identifier = str(
            value
        ).replace(
            '"',
            '""',
        )

        return '"%s"' % identifier

    @staticmethod
    def _buildAggregateExpression(
            *,
            operation,
            expression,
    ) -> str:
        aggregateFunctions = {
            "count": "COUNT",
            "min": "MIN",
            "max": "MAX",
            "sum": "SUM",
        }

        functionName = aggregateFunctions.get(
            operation
        )

        if functionName is not None:
            return "%s(%s)" % (
                functionName,
                expression,
            )

        if operation == "avg":
            return (
                "AVG(%s)::DOUBLE PRECISION"
                % expression
            )

        if operation == "total":
            return (
                "COALESCE(SUM(%s), 0)"
                "::DOUBLE PRECISION"
                % expression
            )

        if operation == "group_concat":
            return (
                "STRING_AGG("
                "(%s)::TEXT, ','"
                ")"
                % expression
            )

        raise ValueError(
            "Unsupported PostgreSQL aggregate "
            "operation: %s"
            % operation
        )

    def unique(
            self,
            attributes,
            where=None,
    ):
        self._refreshReadSchema()
        if isinstance(
                attributes,
                str,
        ):
            labels = [
                attributes,
            ]
        else:
            labels = [
                str(attribute)
                for attribute
                in attributes or []
            ]

        if not labels:
            raise ValueError(
                "At least one attribute is required"
            )

        selectParts = []
        selectParams = []
        aliases = []

        for index, label in enumerate(
                labels
        ):
            expression, expressionParams = (
                self._fieldExpression(
                    label
                )
            )

            alias = (
                    "value_%d"
                    % index
            )

            selectParts.append(
                '%s AS "%s"'
                % (
                    expression,
                    alias,
                )
            )

            selectParams.extend(
                expressionParams
            )

            aliases.append(
                alias
            )

        whereSql, whereParams = (
            self._buildWhere(
                where
            )
        )

        query = """
            SELECT DISTINCT {selectParts}
              FROM {itemsTable}
             WHERE "{scopeColumn}" = %s
        """.format(
            selectParts=", ".join(
                selectParts
            ),
            itemsTable=self._itemsTable,
            scopeColumn=self._scopeColumn,
        )

        params = list(
            selectParams
        )

        params.append(
            self._scopeId
        )

        if whereSql:
            query += (
                    "\n AND "
                    + whereSql
            )

            params.extend(
                whereParams
            )

        rows = self.db.fetchAll(
            query,
            tuple(params),
        )

        result = {
            label: []
            for label in labels
        }

        for row in rows or []:
            for label, alias in zip(
                    labels,
                    aliases,
            ):
                result[label].append(
                    row.get(alias)
                )

        if len(labels) == 1:
            return result[
                labels[0]
            ]

        return result

    # ------------------------------------------------------------------
    # Storage-scope helpers
    # ------------------------------------------------------------------

    def _buildItemsSelectQuery(
            self,
    ) -> str:
        return """
            SELECT id,
                   "{scopeColumn}",
                   "scipionItemId",
                   {parentItemExpression},
                   enabled,
                   label,
                   comment,
                   {creationExpression}
                       AS creation,
                   "values",
                   "createdAt",
                   "updatedAt"
              FROM {itemsTable}
             WHERE "{scopeColumn}" = %s
        """.format(
            scopeColumn=(
                self._scopeColumn
            ),
            parentItemExpression=(
                self._parentItemExpression
            ),
            creationExpression=(
                self
                .STREAMING_CREATION_EXPRESSION
            ),
            itemsTable=(
                self._itemsTable
            ),
        )

    def _loadLogicalTableProperties(
            self,
    ) -> Dict[str, Any]:
        row = self.db.fetchOne(
            """
            SELECT properties
              FROM scipion_set_tables
             WHERE id = %s
             LIMIT 1
            """,
            (self.tableId,),
        )

        if not row:
            return {}

        properties = row.get(
            "properties"
        )

        if isinstance(
                properties,
                dict,
        ):
            return dict(
                properties
            )

        if isinstance(
                properties,
                str,
        ):
            try:
                parsed = json.loads(
                    properties
                )
            except Exception:
                return {}

            if isinstance(
                    parsed,
                    dict,
            ):
                return dict(
                    parsed
                )

        return {}

    # ------------------------------------------------------------------
    # Query construction
    # ------------------------------------------------------------------

    @staticmethod
    def _indexColumns(
            columns,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Normalize PostgreSQL Set column metadata into the
        label-indexed representation used by query builders.
        """
        indexedColumns = {}

        for rawColumn in columns or []:
            column = dict(
                rawColumn or {}
            )

            labelProperty = column.get(
                "labelProperty"
            )

            if labelProperty in (
                    None,
                    "",
            ):
                raise ValueError(
                    "PostgreSQL Set column does not "
                    "define labelProperty."
                )

            indexedColumns[
                str(labelProperty)
            ] = column

        return indexedColumns

    def _replaceColumns(
            self,
            columns,
    ) -> bool:
        if isinstance(
                columns,
                dict,
        ):
            indexedColumns = {
                str(label): dict(
                    column or {}
                )
                for label, column
                in columns.items()
            }
        else:
            indexedColumns = (
                self._indexColumns(
                    columns
                )
            )

        if indexedColumns == self._columns:
            return False

        self._columns = indexedColumns
        self._itemSchemaReady = bool(
            self._columns
        )

        updater = self.itemColumnsUpdater

        if callable(
                updater
        ):
            updater([
                dict(column)
                for column in sorted(
                    self._columns.values(),
                    key=lambda column: (
                        int(
                            column.get(
                                "position"
                            )
                            or 0
                        ),
                        str(
                            column.get(
                                "labelProperty"
                            )
                            or ""
                        ),
                    ),
                )
            ])

        return True

    def _mergeColumns(
            self,
            columns,
    ) -> bool:
        """
        Merge newly persisted columns into the runtime Set schema.

        A PostgreSQL Set schema is cumulative while the storage scope
        remains active. A temporarily empty or stale database read must
        not discard columns already discovered by a successful runtime
        item-schema synchronization.
        """
        if isinstance(
                columns,
                dict,
        ):
            indexedColumns = {
                str(label): dict(
                    column or {}
                )
                for label, column
                in columns.items()
            }
        else:
            indexedColumns = (
                self._indexColumns(
                    columns
                )
            )

        if not indexedColumns:
            return False

        mergedColumns = dict(
            self._columns
        )

        mergedColumns.update(
            indexedColumns
        )

        return self._replaceColumns(
            mergedColumns
        )

    def _refreshColumns(
            self,
    ) -> bool:
        return self._mergeColumns(
            self._loadColumns()
        )

    def _refreshReadSchema(
            self,
    ) -> None:
        self._dynamicFieldValueTypes.clear()

        scopeChanged = (
            self
            ._refreshLogicalTableScope()
        )

        if not scopeChanged:
            self._refreshColumns()

    def _loadColumns(
            self,
    ) -> Dict[str, Dict[str, Any]]:
        query = """
            SELECT "labelProperty",
                   "className",
                   "valueType",
                   position
              FROM {columnsTable}
             WHERE "{scopeColumn}" = %s
             ORDER BY position ASC
        """.format(
            columnsTable=self._columnsTable,
            scopeColumn=self._scopeColumn,
        )

        rows = self.db.fetchAll(
            query,
            (self._scopeId,),
        )

        return self._indexColumns(
            rows
        )

    def _buildItems(
            self,
            rows,
            rowFilter=None,
    ):
        items = []

        for row in rows or []:
            item = self.itemBuilder(
                dict(row)
            )

            if (
                    rowFilter is not None
                    and not rowFilter(item)
            ):
                continue

            items.append(
                item
            )

        return items

    def _buildWhere(
            self,
            where,
    ) -> Tuple[str, List[Any]]:
        if where is None:
            return "", []

        whereText = str(
            where
        ).strip()

        if whereText in (
                "",
                "1",
                "1=1",
        ):
            return "", []

        clauses = []
        params: List[Any] = []

        parts = re.split(
            r"\s+AND\s+",
            whereText,
            flags=re.IGNORECASE,
        )

        for part in parts:
            match = self.WHERE_PART_PATTERN.match(
                part
            )

            if match is None:
                raise NotImplementedError(
                    "Unsupported PostgreSQL set where expression: %s"
                    % whereText
                )

            field = match.group(
                "field"
            )

            operator = match.group(
                "operator"
            )

            if operator == "==":
                operator = "="
            elif operator == "<>":
                operator = "!="

            value = self._parseWhereValue(
                match.group("value")
            )

            expression, expressionParams = (
                self._fieldExpression(
                    field
                )
            )

            clauses.append(
                "%s %s %%s"
                % (
                    expression,
                    operator,
                )
            )

            params.extend(
                expressionParams
            )

            params.append(
                self._normalizeFieldValue(
                    field,
                    value,
                )
            )

        return (
            " AND ".join(clauses),
            params,
        )

    def _buildOrderBy(
            self,
            orderBy,
            direction,
    ) -> Tuple[str, List[Any]]:
        if orderBy is None:
            return "", []

        fields: Sequence[Any]

        if isinstance(
                orderBy,
                (list, tuple),
        ):
            fields = orderBy
        else:
            fields = [
                orderBy,
            ]

        normalizedDirection = str(
            direction or "ASC"
        ).upper()

        if normalizedDirection not in (
                "ASC",
                "DESC",
        ):
            raise ValueError(
                "Invalid order direction: %s"
                % direction
            )

        expressions = []
        params: List[Any] = []

        for field in fields:
            expression, expressionParams = (
                self._fieldExpression(
                    str(field)
                )
            )

            expressions.append(
                "%s %s"
                % (
                    expression,
                    normalizedDirection,
                )
            )

            params.extend(
                expressionParams
            )

        return (
            ", ".join(expressions),
            params,
        )

    def _fieldExpression(
            self,
            field: str,
    ) -> Tuple[str, List[Any]]:
        field = str(
            field
        )

        if field in self.ID_FIELDS:
            return (
                '"scipionItemId"',
                [],
            )

        if field == "creation":
            return (
                self.STREAMING_CREATION_EXPRESSION,
                [],
            )

        directColumn = self.DIRECT_FIELDS.get(
            field
        )

        if directColumn is not None:
            return (
                '"%s"' % directColumn,
                [],
            )

        column = self._columns.get(
            field
        )

        if column is None:
            valueType = self._resolveDynamicFieldValueType(
                field
            )

            if valueType is None:
                raise ValueError(
                    "Unknown Scipion set item field: %s"
                    % field
                )

        else:
            valueType = self._getColumnQueryValueType(
                column
            )

        return self._jsonFieldExpression(
            field=field,
            valueType=valueType,
        )

    @staticmethod
    def _getColumnQueryValueType(
            column: Dict[str, Any],
    ) -> str:
        className = str(
            column.get("className")
            or ""
        )

        if className == "Boolean":
            return "boolean"

        return str(
            column.get("valueType")
            or ""
        ).lower()

    @staticmethod
    def _jsonFieldExpression(
            *,
            field: str,
            valueType: str,
    ) -> Tuple[str, List[Any]]:
        expression = '"values" ->> %s'

        if valueType == "integer":
            expression = (
                'NULLIF("values" ->> %s, \'\')::BIGINT'
            )

        elif valueType == "float":
            expression = (
                'NULLIF("values" ->> %s, \'\')::DOUBLE PRECISION'
            )

        elif valueType == "boolean":
            expression = (
                'NULLIF("values" ->> %s, \'\')::BOOLEAN'
            )

        return (
            expression,
            [
                field,
            ],
        )

    def _resolveDynamicFieldValueType(
            self,
            field: str,
    ) -> Optional[str]:
        field = str(
            field
        )

        cachedValueType = self._dynamicFieldValueTypes.get(
            field
        )

        if cachedValueType is not None:
            return cachedValueType

        row = self.db.fetchOne(
            """
            SELECT ARRAY_AGG(
                       DISTINCT "jsonType"
                   ) AS "jsonTypes",
                   BOOL_OR(
                       "jsonType" = 'number'
                       AND "valueText" ~ '[.eE]'
                   ) AS "hasFloatingNumber"
              FROM (
                    SELECT jsonb_typeof(
                               "values" -> %s
                           ) AS "jsonType",
                           "values" ->> %s AS "valueText"
                      FROM {itemsTable}
                     WHERE "{scopeColumn}" = %s
                       AND "values" ? %s
                       AND jsonb_typeof(
                               "values" -> %s
                           ) <> 'null'
                   ) AS "fieldValues"
            """.format(
                itemsTable=self._itemsTable,
                scopeColumn=self._scopeColumn,
            ),
            (
                field,
                field,
                self._scopeId,
                field,
                field,
            ),
        ) or {}

        rawJsonTypes = row.get(
            "jsonTypes"
        ) or []

        if isinstance(rawJsonTypes, str):
            rawJsonTypes = [
                rawJsonTypes,
            ]

        jsonTypes = {
            str(jsonType).lower()
            for jsonType in rawJsonTypes
            if jsonType not in (
                None,
                "",
            )
        }

        if not jsonTypes:
            return None

        unsupportedTypes = (
            jsonTypes
            - {
                "string",
                "number",
                "boolean",
            }
        )

        if unsupportedTypes:
            raise ValueError(
                "Scipion set item field is not scalar: %s. "
                "jsonTypes=%s"
                % (
                    field,
                    sorted(jsonTypes),
                )
            )

        if len(jsonTypes) != 1:
            raise ValueError(
                "Inconsistent Scipion set item field types: %s. "
                "jsonTypes=%s"
                % (
                    field,
                    sorted(jsonTypes),
                )
            )

        jsonType = next(
            iter(jsonTypes)
        )

        if jsonType == "string":
            valueType = "text"

        elif jsonType == "boolean":
            valueType = "boolean"

        elif row.get(
                "hasFloatingNumber"
        ):
            valueType = "float"

        else:
            valueType = "integer"

        self._dynamicFieldValueTypes[
            field
        ] = valueType

        return valueType

    def _normalizeFieldValue(
            self,
            field,
            value,
    ):
        field = str(
            field
        )

        if field in self.ID_FIELDS:
            return int(
                value
            )

        if field == "enabled":
            return self._toBoolean(
                value
            )

        if (
                field in self.DIRECT_FIELDS
                or field == "creation"
        ):
            return value

        column = self._columns.get(
            field
        )

        if column is not None:
            valueType = self._getColumnQueryValueType(
                column
            )

        else:
            valueType = self._dynamicFieldValueTypes.get(
                field
            )

        if valueType == "integer":
            return int(
                value
            )

        if valueType == "float":
            return float(
                value
            )

        if valueType == "boolean":
            return self._toBoolean(
                value
            )

        return (
            str(value)
            if value is not None
            else None
        )

    def _parseWhereValue(
            self,
            valueText,
    ):
        valueText = str(
            valueText
        ).strip()

        if (
                len(valueText) >= 2
                and valueText[0] == valueText[-1]
                and valueText[0] in (
                    "'",
                    '"',
                )
        ):
            return valueText[1:-1]

        lowerValue = valueText.lower()

        if lowerValue == "true":
            return True

        if lowerValue == "false":
            return False

        if lowerValue in (
                "none",
                "null",
        ):
            return None

        try:
            return int(
                valueText
            )
        except ValueError:
            pass

        try:
            return float(
                valueText
            )
        except ValueError:
            return valueText

    def _toBoolean(
            self,
            value,
    ):
        if isinstance(
                value,
                bool,
        ):
            return value

        if isinstance(
                value,
                (int, float),
        ):
            return bool(
                value
            )

        return str(
            value
        ).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
            "enabled",
        )