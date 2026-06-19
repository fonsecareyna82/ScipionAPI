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

# ******************************************************************************
# * PostgreSQL DAO for persisted Scipion sets.
# *
# * This DAO implements the metadata-viewer DAO contract so PostgreSQL can be
# * consumed through ObjectManager just like SQLite/STAR metadata sources.
# *
# ******************************************************************************

import logging
from typing import Any, Dict, Iterable, List, Optional

import numpy

from metadataviewer.dao.model import IDAO
from metadataviewer.model import (
    Table,
    Column,
    BoolRenderer,
    FloatRenderer,
    ImageRenderer,
    StrRenderer,
)

from pwem.convert.transformations import euler_from_matrix

from app.backend.mapper import ScipionSetPostgresqlMapper


logger = logging.getLogger(__name__)

ALLOWED_COLUMNS_TYPES = [
    "String",
    "Float",
    "Integer",
    "Boolean",
    "Matrix",
    "CsvList",
]

EXCLUDED_COLUMNS = ["label", "comment", "creation", "_streamState"]
PERMANENT_COLUMNS = ["id", "enabled"]

OBJECT_TABLE = "objects"
ENABLED_COLUMN = "enabled"
EXTENDED_COLUMN_NAME = "stack"


def _guessType(value):
    if value is None:
        return str

    if isinstance(value, bool):
        return bool

    if isinstance(value, int):
        return int

    if isinstance(value, float):
        return float

    try:
        int(value)
        return int
    except Exception:
        pass

    try:
        float(value)
        return float
    except Exception:
        pass

    return str


class ScipionColumn(Column):
    def __init__(self, name, renderer=None, callback=None):
        super().__init__(name, renderer=renderer)
        self.callback = callback

    def setCallback(self, callback):
        self.callback = callback

    def calculate(self, row, values):
        if self.callback is not None:
            self.callback(row, values)


class PostgresqlDAO(IDAO):
    """
    DAO compatible with metadata-viewer ObjectManager.

    It reads persisted Scipion SetOf... outputs from PostgreSQL using
    ScipionSetPostgresqlMapper, but exposes them as metadata-viewer Tables,
    Columns and Pages.
    """

    def __init__(
            self,
            db,
            projectId: int,
            protocolId: int,
            outputName: str,
    ):
        self.db = db
        self.projectId = int(projectId)
        self.protocolId = int(protocolId)
        self.outputName = str(outputName)

        self.setMapper = ScipionSetPostgresqlMapper(db)

        self._tables: Dict[str, Table] = {}
        self._tableCount: Dict[str, int] = {}
        self._labels: Dict[str, List[str]] = {}
        self._labelsTypes: Dict[str, List[Any]] = {}
        self._columns: List[Dict[str, Any]] = []
        self._storedSet: Optional[Dict[str, Any]] = None

        self._logicalTables: Dict[str, Dict[str, Any]] = {}
        self._tableColumns: Dict[str, List[Dict[str, Any]]] = {}
        self._useLogicalTables = False

    # -------------------------------------------------------------------------
    # metadata-viewer DAO API
    # -------------------------------------------------------------------------

    @classmethod
    def getCompatibleFileTypes(cls):
        # Kept for compatibility with ObjectManager.selectDAO(), even though
        # ScipionWeb injects this DAO directly.
        return ["pgset"]

    def hasOutput(self) -> bool:
        try:
            return self._getStoredSet(limit=0, offset=0) is not None
        except Exception:
            return False

    def getTables(self):
        if self._tables:
            return self._tables

        storedSet = self._requireStoredSet(limit=0, offset=0)
        setId = int(storedSet["id"])

        logicalTables = []
        try:
            logicalTables = self.setMapper.listStoredSetTables(setId) or []
        except Exception:
            logicalTables = []

        if logicalTables:
            self._useLogicalTables = True

            for logicalTable in logicalTables:
                tableName = logicalTable.get("name")
                if not tableName:
                    continue

                table = Table(tableName)
                table.setAlias(logicalTable.get("alias") or tableName)

                self._tables[tableName] = table
                self._logicalTables[tableName] = logicalTable
                self._tableColumns[tableName] = self.setMapper.getStoredSetTableColumns(
                    int(logicalTable["id"])
                )

            return self._tables

        table = Table(OBJECT_TABLE)
        table.setAlias(storedSet.get("setClassName") or self.outputName)

        self._tables[OBJECT_TABLE] = table
        self._columns = self._normalizeColumns(storedSet.get("columns") or [])

        return self._tables

    def fillTable(self, table, objectManager):
        tableName = table.getName()
        if tableName != OBJECT_TABLE and not self._useLogicalTables:
            return

        firstRow = self.getTableRow(tableName, 0)
        columns = self._getColumnsForTable(tableName)

        if "id" not in firstRow:
            table.setHasColumnId(False)

        labels = [
            key
            for key in firstRow.keys()
            if key not in EXCLUDED_COLUMNS
        ]

        self._labels[tableName] = labels
        self._labelsTypes[tableName] = [
            _guessType(firstRow.get(key))
            for key in labels
        ]

        imgRenderer = None
        computedColsCount = 0

        for index, colName in enumerate(labels):
            value = firstRow.get(colName)
            isFileNameCol = imgRenderer is None and colName.endswith("_filename")

            if colName == ENABLED_COLUMN:
                renderer = BoolRenderer()
            elif isFileNameCol:
                renderer = StrRenderer()
            else:
                renderer = table.guessRenderer("" if value is None else str(value))

            newCol = ScipionColumn(colName, renderer)
            newCol.setIsSorteable(True)

            if tableName == OBJECT_TABLE:
                newCol.setIsVisible(objectManager.isLabelVisible(colName))
            else:
                newCol.setIsVisible(True)

            table.addColumn(newCol)

            if isFileNameCol:
                previousCol = labels[index - 1] if index > 0 else ""
                if previousCol.endswith("_index"):
                    extraRenderer = renderer
                    imageValue = "" if value is None else str(value)

                    try:
                        if imageValue and ImageRenderer().getImageReader(imageValue) is not None:
                            extraRenderer = ImageRenderer()
                            imgRenderer = extraRenderer
                    except Exception:
                        pass

                    extraCol = ScipionColumn(EXTENDED_COLUMN_NAME, extraRenderer)
                    extraCol.setCallback(self.composeImageFilename)
                    extraCol.setIsVisible(newCol.isVisible())
                    extraCol.setIsSorteable(False)

                    table.addColumn(extraCol)
                    newCol.setIsVisible(False)
                    computedColsCount += 1

            elif colName.endswith("_matrix"):

                def addAlignmentColumn(name, offset, position):
                    extraCol = ScipionColumn(name, renderer=FloatRenderer())
                    extraCol.setIsSorteable(False)
                    extraCol.setIsVisible(newCol.isVisible())
                    extraCol.setCallback(
                        lambda row, values, off=offset, pos=position:
                        self.extractAngularValue(values, off, pos)
                    )
                    table.addColumn(extraCol)

                def addShiftColumn(name, offset, position):
                    extraCol = ScipionColumn(name, renderer=FloatRenderer())
                    extraCol.setIsVisible(newCol.isVisible())
                    extraCol.setIsSorteable(False)
                    extraCol.setCallback(
                        lambda row, values, off=offset, pos=position:
                        self.extractShift(values, off, pos)
                    )
                    table.addColumn(extraCol)

                colNamePrefix = colName.split("_matrix")[0]

                addAlignmentColumn(colNamePrefix + "_rot", -1, 0)
                computedColsCount += 1

                if imgRenderer:
                    imgRenderer.setRotationColumnIndex(index + computedColsCount)

                addAlignmentColumn(colNamePrefix + "_tilt", -2, 1)
                computedColsCount += 1

                addAlignmentColumn(colNamePrefix + "_psi", -3, 2)
                computedColsCount += 1

                addShiftColumn(colNamePrefix + "_shiftX", -4, 0)
                computedColsCount += 1

                addShiftColumn(colNamePrefix + "_shiftY", -5, 1)
                computedColsCount += 1

        if table.getColumns():
            table.setSortingColumn(table.getColumns()[0].getName())

    def _getColumnsForTable(self, tableName: str) -> List[Dict[str, Any]]:
        if self._useLogicalTables:
            return self._normalizeColumns(self._tableColumns.get(tableName) or [])
        return self._columns

    def _getLogicalTable(self, tableName: str) -> Optional[Dict[str, Any]]:
        if not self._useLogicalTables:
            return None
        return self._logicalTables.get(tableName)

    def fillPage(self, page, actualColumn: str, orderAsc=True):
        table = page.getTable()
        tableName = table.getName()

        pageNumber = page.getPageNumber()
        pageSize = page.getPageSize()
        firstRow = pageNumber * pageSize - pageSize

        columnLabel = actualColumn or "id"
        mode = "ASC" if orderAsc else "DESC"

        for rowCount, row in enumerate(
                self.iterTable(
                    tableName,
                    start=firstRow,
                    limit=pageSize,
                    orderBy=columnLabel,
                    mode=mode,
                )
        ):
            values = []

            for column in page.getTable().getColumns():
                if column.isSorteable():
                    values.append(row.get(column.getName()))
                else:
                    column.calculate(row, values)

            idValue = row.get("id", firstRow + rowCount + 1)
            page.addRow((int(idValue), values))

    def getTableRow(self, tableName, rowIndex):
        rows = self._getRows(
            tableName=tableName,
            start=max(0, int(rowIndex or 0)),
            limit=1,
            orderBy="id",
            orderAsc=True,
        )

        if rows:
            return rows[0]

        return self._emptyRow(tableName)

    def getSelectedRangeRowsIds(
            self,
            tableName,
            startRow,
            numberOfRows,
            column,
            reverse=True,
    ):
        rows = list(
            self.iterTable(
                tableName,
                start=max(0, int(startRow) - 1),
                limit=int(numberOfRows),
                orderBy=column or "id",
                mode="ASC" if reverse else "DESC",
            )
        )
        return [int(row.get("id")) for row in rows if row.get("id") is not None]

    def getColumnsValues(
            self,
            tableName,
            columns,
            xAxis,
            selection,
            limit,
            useSelection,
            reverse=True,
    ):
        selectedColumns = list(columns or [])
        if xAxis and xAxis not in selectedColumns:
            selectedColumns.append(xAxis)
        if "id" not in selectedColumns:
            selectedColumns.append("id")

        rows = list(
            self.iterTable(
                tableName,
                start=0,
                limit=limit,
                orderBy=xAxis or "id",
                mode="ASC" if reverse else "DESC",
            )
        )

        if useSelection and selection is not None:
            try:
                selectedIds = set(selection.getSelection().keys())
                rows = [row for row in rows if row.get("id") in selectedIds]
            except Exception:
                pass

        values = {col: [] for col in selectedColumns}
        for row in rows:
            for col in selectedColumns:
                values[col].append(row.get(col))

        return values

    def getTableWithAdditionalInfo(self):
        return None

    def close(self):
        # Do not close the shared PostgreSQL connection here.
        pass

    # -------------------------------------------------------------------------
    # Row/table helpers
    # -------------------------------------------------------------------------

    def iterTable(self, tableName, **kwargs):
        start = max(0, int(kwargs.get("start", 0) or 0))
        limit = kwargs.get("limit", None)
        limit = int(limit) if limit is not None else None

        orderBy = kwargs.get("orderBy") or "id"
        mode = str(kwargs.get("mode") or "ASC").upper()
        orderAsc = mode != "DESC"

        rows = self._getRows(
            tableName=tableName,
            start=start,
            limit=limit,
            orderBy=orderBy,
            orderAsc=orderAsc,
        )

        for row in rows:
            yield row

    def composeImageFilename(self, row, values):
        if len(values) < 2:
            values.append("")
            return

        indexValue = values[-2]
        filenameValue = values[-1]

        if filenameValue is None:
            values.append("")
            return

        indexStr = ""
        try:
            if int(indexValue) != 0:
                indexStr = "%s@" % indexValue
        except Exception:
            if indexValue not in (None, "", 0, "0"):
                indexStr = "%s@" % indexValue

        values.append("%s%s" % (indexStr, filenameValue))

    def extractAngularValue(self, values, offset, position):
        matrix = values[offset]
        matrix = self._toNumpyMatrix(matrix)

        matrixI = numpy.linalg.inv(matrix)
        eulerData = euler_from_matrix(matrix=matrixI, axes="szyz")
        values.append(numpy.rad2deg(eulerData[position]))

    def extractShift(self, values, offset, position):
        matrix = values[offset]
        matrix = self._toNumpyMatrix(matrix)

        shape = matrix.shape[0]
        values.append(matrix[position, shape - 1])

    # -------------------------------------------------------------------------
    # PostgreSQL-backed loading
    # -------------------------------------------------------------------------

    def _getStoredSet(
            self,
            limit: Optional[int],
            offset: int,
    ) -> Optional[Dict[str, Any]]:
        return self.setMapper.getStoredSet(
            projectId=self.projectId,
            protocolDbId=self.protocolId,
            outputName=self.outputName,
            limit=limit,
            offset=offset,
        )

    def _requireStoredSet(
            self,
            limit: Optional[int],
            offset: int,
    ) -> Dict[str, Any]:
        storedSet = self._getStoredSet(limit=limit, offset=offset)
        if storedSet is None:
            raise ValueError(
                "Persisted Scipion set was not found: projectId=%s protocolId=%s outputName=%s"
                % (self.projectId, self.protocolId, self.outputName)
            )
        return storedSet

    def _getStoredSetHeader(self) -> Dict[str, Any]:
        if self._storedSet is None:
            self._storedSet = self._requireStoredSet(limit=0, offset=0)
            self._columns = self._normalizeColumns(self._storedSet.get("columns") or [])
        return self._storedSet

    def _getRows(
            self,
            tableName: str,
            start: int,
            limit: Optional[int],
            orderBy: str,
            orderAsc: bool,
    ) -> List[Dict[str, Any]]:
        orderBy = str(orderBy or "id")

        if self._useLogicalTables:
            logicalTable = self._getLogicalTable(tableName)
            if logicalTable is None:
                return []

            tableId = int(logicalTable["id"])
            columns = self._getColumnsForTable(tableName)

            canUsePagedRead = orderAsc and orderBy in ("id", "_objId", "SCIPION_OBJECT_ID")

            if canUsePagedRead:
                items = self.setMapper.getStoredSetTableItems(
                    tableId=tableId,
                    limit=limit,
                    offset=start,
                )
                return [self._itemToRow(item, columns) for item in items]

            items = self.setMapper.getStoredSetTableItems(
                tableId=tableId,
                limit=None,
                offset=0,
            )
            rows = [self._itemToRow(item, columns) for item in items]
            rows.sort(
                key=lambda row: self._sortValue(row.get(orderBy)),
                reverse=not orderAsc,
            )

            if limit is None:
                return rows[start:]

            return rows[start:start + limit]

        canUsePagedRead = orderAsc and orderBy in ("id", "_objId", "SCIPION_OBJECT_ID")

        if canUsePagedRead:
            storedSet = self._requireStoredSet(limit=limit, offset=start)
            items = storedSet.get("items") or []
            self._columns = self._normalizeColumns(storedSet.get("columns") or self._columns)
            return [self._itemToRow(item, self._columns) for item in items]

        storedSet = self._requireStoredSet(limit=None, offset=0)
        items = storedSet.get("items") or []
        self._columns = self._normalizeColumns(storedSet.get("columns") or self._columns)

        rows = [self._itemToRow(item, self._columns) for item in items]
        rows.sort(
            key=lambda row: self._sortValue(row.get(orderBy)),
            reverse=not orderAsc,
        )

        if limit is None:
            return rows[start:]

        return rows[start:start + limit]

    def _itemToRow(
            self,
            item: Dict[str, Any],
            columns: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        values = item.get("values") or {}
        if not isinstance(values, dict):
            values = {}

        itemId = item.get("scipionItemId")
        if itemId is None:
            itemId = item.get("id")

        row: Dict[str, Any] = {
            "id": itemId,
            "enabled": bool(item.get("enabled", True)),
        }

        for column in columns:
            label = column.get("labelProperty")
            if not label:
                continue

            value = values.get(label)
            if value is None:
                value = values.get(str(label).strip())

            row[str(label)] = self._normalizeValue(str(label), value)

        return row

    def _emptyRow(self, tableName: str) -> Dict[str, Any]:
        row = {
            "id": 0,
            "enabled": True,
        }

        for column in self._getColumnsForTable(tableName):
            label = column.get("labelProperty")
            if label:
                row[str(label)] = None

        return row

    def getTableRowCount(self, tableName):
        if tableName not in self._tableCount:
            if self._useLogicalTables:
                logicalTable = self._getLogicalTable(tableName)
                if logicalTable is None:
                    self._tableCount[tableName] = 0
                else:
                    self._tableCount[tableName] = self._getStoredSetTableItemsCount(
                        int(logicalTable["id"])
                    )
            else:
                self._tableCount[tableName] = self._getStoredSetItemsCount()

        return self._tableCount[tableName]

    def _getStoredSetTableItemsCount(self, tableId: int) -> int:
        row = self.db.fetchOne(
            """
            SELECT COUNT(*) AS count
              FROM scipion_set_table_items
             WHERE "tableId" = %s
            """,
            (tableId,),
        )
        if not row:
            return 0
        return int(row.get("count") or 0)

    # -------------------------------------------------------------------------
    # Metadata helpers
    # -------------------------------------------------------------------------

    def _normalizeColumns(self, columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def sortKey(column: Dict[str, Any]):
            try:
                return int(column.get("position") or 0)
            except Exception:
                return 0

        return sorted(columns or [], key=sortKey)

    def _getStoredSetItemsCount(self) -> int:
        storedSet = self._getStoredSetHeader()
        properties = storedSet.get("properties") or {}

        if isinstance(properties, dict):
            count = self._toInt(properties.get("itemsCount"))
            if count is not None:
                return count

        for prop in storedSet.get("setProperties") or []:
            if str(prop.get("key")) == "itemsCount":
                count = self._toInt(prop.get("value"))
                if count is not None:
                    return count

        return 0

    def _normalizeValue(self, label: str, value: Any) -> Any:
        if value is None:
            return None

        if label.endswith("_matrix"):
            return self._toNumpyMatrix(value)

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, list):
            return [
                self._normalizeValue(label, item)
                for item in value
            ]

        if isinstance(value, tuple):
            return [
                self._normalizeValue(label, item)
                for item in value
            ]

        if isinstance(value, dict):
            return {
                str(key): self._normalizeValue(label, item)
                for key, item in value.items()
            }

        return str(value)

    def _toNumpyMatrix(self, value: Any):
        if isinstance(value, numpy.ndarray):
            return value

        if isinstance(value, str):
            try:
                value = eval(value)
            except Exception:
                value = []

        return numpy.array(value)

    def _sortValue(self, value: Any):
        if value is None:
            return ""

        if isinstance(value, numpy.ndarray):
            return str(value.tolist())

        if isinstance(value, (list, tuple, dict)):
            return str(value)

        return value

    def _toInt(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None

        try:
            return int(value)
        except Exception:
            return None


# Backward-compatible alias while project_service.py is migrated.
PostgresqlMetadataDAO = PostgresqlDAO