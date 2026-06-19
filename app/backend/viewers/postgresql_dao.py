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


# *******************************************************************************
# * PostgreSQL metadata DAO for persisted Scipion sets.
# *
# * This DAO adapts Scipion sets persisted in PostgreSQL to the metadata-table
# * response shape already consumed by the web metadata viewer.
# *******************************************************************************

from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.mapper import ScipionSetPostgresqlMapper


class PostgresqlMetadataDAO:
    """
    Read persisted Scipion SetOf... outputs from PostgreSQL and expose them with
    the same API shape used by the metadata viewer endpoints.

    This class intentionally hides PostgreSQL persistence details from
    ProjectService.
    """

    OBJECTS_TABLE = "objects"
    SOURCE = "postgresql"

    def __init__(self, db):
        self.db = db
        self.setMapper = ScipionSetPostgresqlMapper(db)

    # -------------------------------------------------------------------------
    # Public API used by ProjectService
    # -------------------------------------------------------------------------

    def hasOutput(self, projectId: int, protocolId: int, outputName: str) -> bool:
        try:
            storedSet = self._getStoredSet(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                limit=0,
                offset=0,
            )
            return storedSet is not None
        except Exception:
            return False

    def canServeTable(self, tableName: str) -> bool:
        return str(tableName or "").strip() == self.OBJECTS_TABLE

    def listTables(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
    ) -> List[Dict[str, Any]]:
        storedSet = self._requireStoredSet(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            limit=0,
            offset=0,
        )

        rowCount = self._getStoredSetItemsCount(storedSet)

        return [
            {
                "name": self.OBJECTS_TABLE,
                "alias": storedSet.get("setClassName") or outputName,
                "rowCount": int(rowCount),
                "hasColumnId": True,
                "persisted": True,
                "source": self.SOURCE,
                "setId": storedSet.get("id"),
                "setClassName": storedSet.get("setClassName"),
                "itemClassName": storedSet.get("itemClassName"),
            }
        ]

    def getSchema(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tableName: str,
    ) -> Dict[str, Any]:
        self._requireObjectsTable(tableName)

        storedSet = self._requireStoredSet(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            limit=0,
            offset=0,
        )

        columns = self._normalizeColumns(storedSet.get("columns") or [])

        return {
            "name": self.OBJECTS_TABLE,
            "alias": storedSet.get("setClassName") or outputName,
            "hasColumnId": True,
            "actions": [],
            "columns": [
                self._columnToSchemaItem(column, index)
                for index, column in enumerate(columns)
            ],
            "persisted": True,
            "source": self.SOURCE,
            "setId": storedSet.get("id"),
            "setClassName": storedSet.get("setClassName"),
            "itemClassName": storedSet.get("itemClassName"),
        }

    def getWindow(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tableName: str,
            offset: int,
            limit: int,
            selectionOnly: bool = False,
            sortBy: str = "id",
            asc: bool = True,
    ) -> Dict[str, Any]:
        self._requireObjectsTable(tableName)

        offset = max(0, int(offset or 0))
        limit = max(1, int(limit or 1))

        if selectionOnly:
            return {
                "offset": offset,
                "limit": limit,
                "totalRows": 0,
                "rows": [],
                "persisted": True,
                "source": self.SOURCE,
            }

        storedSet = self._requireStoredSet(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            limit=limit,
            offset=offset,
        )

        columns = self._normalizeColumns(storedSet.get("columns") or [])
        items = storedSet.get("items") or []
        totalRows = self._getStoredSetItemsCount(storedSet)

        resultRows = []
        for localIndex, item in enumerate(items):
            globalIndex = offset + localIndex
            valuesPayload = self._itemToValuesPayload(item, columns)

            logicalId = item.get("scipionItemId")
            if logicalId is None:
                logicalId = item.get("id")

            resultRows.append(
                {
                    "id": globalIndex,
                    "index": globalIndex,
                    "rowId": logicalId,
                    "values": valuesPayload,
                    "enabled": bool(item.get("enabled", True)),
                }
            )

        return {
            "offset": offset,
            "limit": limit,
            "totalRows": int(totalRows),
            "rows": resultRows,
            "persisted": True,
            "source": self.SOURCE,
            "setId": storedSet.get("id"),
        }

    # -------------------------------------------------------------------------
    # Stored set resolution
    # -------------------------------------------------------------------------

    def _getStoredSet(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            limit: Optional[int],
            offset: int,
    ) -> Optional[Dict[str, Any]]:
        return self.setMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolId,
            outputName=outputName,
            limit=limit,
            offset=offset,
        )

    def _requireStoredSet(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            limit: Optional[int],
            offset: int,
    ) -> Dict[str, Any]:
        try:
            storedSet = self._getStoredSet(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Persisted Scipion set not found: %s" % exc,
            )

        if storedSet is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Persisted Scipion set not found",
            )

        return storedSet

    def _requireObjectsTable(self, tableName: str) -> None:
        if not self.canServeTable(tableName):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Persisted metadata table '%s' not found" % tableName,
            )

    # -------------------------------------------------------------------------
    # Shape adapters
    # -------------------------------------------------------------------------

    def _normalizeColumns(self, columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def sortKey(column: Dict[str, Any]):
            try:
                return int(column.get("position") or 0)
            except Exception:
                return 0

        return sorted(columns or [], key=sortKey)

    def _columnToSchemaItem(
            self,
            column: Dict[str, Any],
            index: int,
    ) -> Dict[str, Any]:
        rawName = (
                column.get("labelProperty")
                or column.get("columnName")
                or "column_%s" % index
        )
        name = str(rawName)

        return {
            "name": name,
            "alias": self._getColumnAlias(name),
            "index": index,
            "sortable": bool(column.get("indexed", False)) or name in ("id", "_objId"),
            "visible": True,
            "rendererType": self._getRendererType(column),
            "decimals": self._getDecimals(column),
            "hasTransformation": False,
            "persisted": True,
            "source": self.SOURCE,
        }

    def _itemToValuesPayload(
            self,
            item: Dict[str, Any],
            columns: List[Dict[str, Any]],
    ) -> List[Any]:
        values = item.get("values") or {}
        if not isinstance(values, dict):
            values = {}

        payload = []
        for column in columns:
            label = column.get("labelProperty")
            value = values.get(label)

            if value is None and label is not None:
                value = values.get(str(label).strip())

            payload.append(self._normalizeCellValue(value))

        return payload

    def _normalizeCellValue(self, value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, list):
            return [self._normalizeCellValue(item) for item in value]

        if isinstance(value, tuple):
            return [self._normalizeCellValue(item) for item in value]

        if isinstance(value, dict):
            return {
                str(key): self._normalizeCellValue(item)
                for key, item in value.items()
            }

        return str(value)

    # -------------------------------------------------------------------------
    # Metadata helpers
    # -------------------------------------------------------------------------

    def _getStoredSetItemsCount(self, storedSet: Dict[str, Any]) -> int:
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

    def _getColumnAlias(self, name: str) -> str:
        clean = str(name or "").strip()
        if clean.startswith("_"):
            clean = clean[1:]
        return clean or str(name)

    def _getRendererType(self, column: Dict[str, Any]) -> str:
        valueType = str(column.get("valueType") or "").lower()
        className = str(column.get("className") or "").lower()

        text = "%s %s" % (valueType, className)

        if "bool" in text:
            return "bool"

        if "float" in text or "decimal" in text:
            return "float"

        if "integer" in text or "long" in text or className == "int":
            return "int"

        if "matrix" in text:
            return "matrix"

        if "image" in text or "filename" in text or "file" in text:
            return "image"

        return "str"

    def _getDecimals(self, column: Dict[str, Any]) -> Optional[int]:
        rendererType = self._getRendererType(column)
        if rendererType == "float":
            return 2
        return None

    def _toInt(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None