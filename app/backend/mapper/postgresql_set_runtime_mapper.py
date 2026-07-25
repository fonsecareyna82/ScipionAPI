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
        "creation": "creation",
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
            itemBuilder: Optional[
                Callable[[Dict[str, Any]], Any]
            ] = None,
            tableId: Optional[int] = None,
    ):
        if db is None:
            raise ValueError("db is required")

        if not callable(itemBuilder):
            raise ValueError("itemBuilder must be callable")

        hasSetId = setId is not None
        hasTableId = tableId is not None

        if hasSetId == hasTableId:
            raise ValueError(
                "Exactly one of setId or tableId is required"
            )

        self.db = db

        self.setId = (
            int(setId)
            if hasSetId
            else None
        )

        self.tableId = (
            int(tableId)
            if hasTableId
            else None
        )

        self.itemBuilder = itemBuilder

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

    # ------------------------------------------------------------------
    # Set properties
    # ------------------------------------------------------------------

    def hasProperty(self, key):
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

    # ------------------------------------------------------------------
    # Pending mapper operations
    # ------------------------------------------------------------------

    def aggregate(
            self,
            operations,
            operationLabel,
            groupByLabels=None,
    ):
        raise NotImplementedError(
            "PostgreSQL set aggregate() will be implemented after the "
            "read and native-object hydration contract is validated."
        )

    def unique(
            self,
            attributes,
            where=None,
    ):
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
    # Read-only lifecycle
    # ------------------------------------------------------------------

    def commit(self):
        pass

    def close(self):
        pass

    def insert(self, item):
        raise RuntimeError(
            "PostgresqlSetRuntimeMapper is read-only. "
            "Set snapshots are persisted by ScipionSetPostgresqlMapper."
        )

    def update(self, item):
        raise RuntimeError(
            "PostgresqlSetRuntimeMapper is read-only. "
            "Set snapshots are persisted by ScipionSetPostgresqlMapper."
        )

    def clear(self):
        raise RuntimeError(
            "PostgresqlSetRuntimeMapper is read-only."
        )

    def enableAppend(self):
        raise RuntimeError(
            "PostgresqlSetRuntimeMapper does not support appending."
        )

    # ------------------------------------------------------------------
    # Storage-scope helpers
    # ------------------------------------------------------------------

    def _buildItemsSelectQuery(self) -> str:
        return """
            SELECT id,
                   "{scopeColumn}",
                   "scipionItemId",
                   {parentItemExpression},
                   enabled,
                   label,
                   comment,
                   creation,
                   "values",
                   "createdAt",
                   "updatedAt"
              FROM {itemsTable}
             WHERE "{scopeColumn}" = %s
        """.format(
            scopeColumn=self._scopeColumn,
            parentItemExpression=(
                self._parentItemExpression
            ),
            itemsTable=self._itemsTable,
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

        return {
            str(
                row["labelProperty"]
            ): dict(row)
            for row in rows or []
        }

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

        directColumn = self.DIRECT_FIELDS.get(
            field
        )

        if directColumn is not None:
            return (
                '"%s"'
                % directColumn,
                [],
            )

        column = self._columns.get(
            field
        )

        if column is None:
            raise ValueError(
                "Unknown Scipion set item field: %s"
                % field
            )

        valueType = str(
            column.get("valueType")
            or ""
        ).lower()

        expression = (
            '"values" ->> %s'
        )

        params = [
            field,
        ]

        if valueType == "integer":
            expression = (
                'NULLIF("values" ->> %s, \'\')::BIGINT'
            )
        elif valueType == "float":
            expression = (
                'NULLIF("values" ->> %s, \'\')::DOUBLE PRECISION'
            )

        return (
            expression,
            params,
        )

    def _normalizeFieldValue(
            self,
            field,
            value,
    ):
        if field in self.ID_FIELDS:
            return int(
                value
            )

        if field == "enabled":
            return self._toBoolean(
                value
            )

        column = self._columns.get(
            str(field)
        )

        if column is None:
            return value

        valueType = str(
            column.get("valueType")
            or ""
        ).lower()

        if valueType == "integer":
            return int(
                value
            )

        if valueType == "float":
            return float(
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