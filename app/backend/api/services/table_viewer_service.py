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
from typing import Any, Callable, Dict, List, Optional


class TableViewerService:
    DEFAULT_PAGE_SIZE = 100

    @staticmethod
    def _normalizeClassName(className: Any) -> str:
        return "".join(
            str(className or "").split()
        ).lower()

    @classmethod
    def _isSupportedSetClass(
            cls,
            className: Any,
    ) -> bool:
        normalized = cls._normalizeClassName(
            className
        )

        return (
            normalized.startswith("setof")
            or normalized.startswith(
                "relionsetof"
            )
        )

    @staticmethod
    def _safeInt(
            value: Any,
            default: int = 0,
    ) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _isPropertiesTable(
            tableInfo: Dict[str, Any],
    ) -> bool:
        name = str(
            tableInfo.get("name") or ""
        ).strip().lower()

        alias = str(
            tableInfo.get("alias") or ""
        ).strip().lower()

        return (
            name == "properties"
            or alias == "properties"
        )

    @classmethod
    def _selectPrimaryTable(
            cls,
            tables: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        validTables = [
            tableInfo
            for tableInfo in tables
            if isinstance(tableInfo, dict)
            and str(
                tableInfo.get("name") or ""
            ).strip()
        ]

        if not validTables:
            return None

        dataTables = [
            tableInfo
            for tableInfo in validTables
            if not cls._isPropertiesTable(
                tableInfo
            )
        ]

        tablesWithRows = [
            tableInfo
            for tableInfo in dataTables
            if cls._safeInt(
                tableInfo.get("rowCount"),
                0,
            ) > 0
        ]

        if tablesWithRows:
            return tablesWithRows[0]

        if dataTables:
            return dataTables[0]

        tablesWithRows = [
            tableInfo
            for tableInfo in validTables
            if cls._safeInt(
                tableInfo.get("rowCount"),
                0,
            ) > 0
        ]

        if tablesWithRows:
            return tablesWithRows[0]

        return validTables[0]

    @classmethod
    def _selectColumns(
            cls,
            schema: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        rawColumns = schema.get(
            "columns"
        ) or []

        columns = [
            column
            for column in rawColumns
            if isinstance(column, dict)
            and str(
                column.get("name") or ""
            ).strip()
        ]

        columns.sort(
            key=lambda column: cls._safeInt(
                column.get("index"),
                0,
            )
        )

        visibleColumns = [
            column
            for column in columns
            if column.get("visible") is not False
        ]

        return visibleColumns or columns

    @staticmethod
    def _columnAlign(
            column: Dict[str, Any],
    ) -> str:
        rendererType = str(
            column.get("rendererType")
            or ""
        ).strip().lower()

        if rendererType in (
                "int",
                "float",
        ):
            return "right"

        if rendererType == "bool":
            return "center"

        return "left"

    @classmethod
    def _buildColumn(
            cls,
            column: Dict[str, Any],
    ) -> Dict[str, Any]:
        columnName = str(
            column.get("name") or ""
        ).strip()

        columnLabel = str(
            column.get("alias")
            or columnName
        ).strip()

        return {
            "id": columnName,
            "label": columnLabel,
            "align": cls._columnAlign(
                column
            ),
            "sortable": bool(
                column.get("sortable")
            ),
        }

    @staticmethod
    def _jsonCellText(
            value: Any,
    ) -> str:
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except Exception:
            return str(value)

    @classmethod
    def _normalizeCell(
            cls,
            value: Any,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
                value,
                (
                    str,
                    int,
                    float,
                    bool,
                ),
        ):
            return value

        if isinstance(value, dict):
            kind = str(
                value.get("kind") or ""
            ).strip().lower()

            if kind == "image":
                return str(
                    value.get("path")
                    or "[image]"
                )

            if kind == "matrix":
                return cls._jsonCellText(
                    value.get("value")
                )

            return cls._jsonCellText(
                value
            )

        if isinstance(
                value,
                (
                    list,
                    tuple,
                ),
        ):
            return cls._jsonCellText(
                value
            )

        return str(value)

    @classmethod
    def _resolveSortColumn(
            cls,
            metadataColumns: List[
                Dict[str, Any]
            ],
    ) -> str:
        for column in metadataColumns:
            if str(
                column.get("name") or ""
            ).strip().lower() == "id":
                return str(
                    column.get("name")
                )

        for column in metadataColumns:
            if column.get("sortable"):
                return str(
                    column.get("name")
                )

        return str(
            metadataColumns[0].get("name")
        )

    @classmethod
    def _buildRows(
            cls,
            pageData: Dict[str, Any],
            metadataColumns: List[
                Dict[str, Any]
            ],
    ) -> List[Dict[str, Any]]:
        result = []

        rawRows = pageData.get(
            "rows"
        ) or []

        for localIndex, rawRow in enumerate(
                rawRows
        ):
            if not isinstance(
                    rawRow,
                    dict,
            ):
                continue

            values = rawRow.get(
                "values"
            ) or []

            cells = {}

            for column in metadataColumns:
                columnName = str(
                    column.get("name")
                    or ""
                ).strip()

                columnIndex = cls._safeInt(
                    column.get("index"),
                    -1,
                )

                value = None

                if (
                        columnIndex >= 0
                        and columnIndex < len(values)
                ):
                    value = values[
                        columnIndex
                    ]

                cells[columnName] = (
                    cls._normalizeCell(
                        value
                    )
                )

            rowId = rawRow.get(
                "rowId"
            )

            if rowId in (
                    None,
                    "",
            ):
                rowId = rawRow.get(
                    "id"
                )

            if rowId in (
                    None,
                    "",
            ):
                rowId = localIndex

            result.append({
                "id": rowId,
                "cells": cells,
            })

        return result

    def resolveOutput(
            self,
            *,
            projectId: int,
            protocolId: int,
            ctx: Dict[str, Any],
            mapper,
            listTablesCallback: Callable,
            getSchemaCallback: Callable,
            getPageCallback: Callable,
            listCoordinates3dTomogramsCallback: Callable,
            listTiltSeriesCallback: Callable,
    ) -> Dict[str, Any]:
        outputName = str(
            ctx.get("outputName")
            or ""
        ).strip()

        pointerClass = str(
            ctx.get("pointerClass")
            or ""
        ).strip()

        if (
                not outputName
                or not self._isSupportedSetClass(
                    pointerClass
                )
        ):
            return {
                "handled": False
            }

        normalizedClass = (
            self._normalizeClassName(
                pointerClass
            )
        )

        if "setofcoordinates3d" in normalizedClass:
            return (
                self
                ._resolveCoordinates3dRoot(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    pointerClass=pointerClass,
                    mapper=mapper,
                    listTomogramsCallback=(
                        listCoordinates3dTomogramsCallback
                    ),
                )
            )
        if (
                normalizedClass != "setoftiltseriesm"
                and "setoftiltseries" in normalizedClass
        ):
            return self._resolveTiltSeriesRoot(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                pointerClass=pointerClass,
                mapper=mapper,
                listTiltSeriesCallback=listTiltSeriesCallback,
            )

        tables = (
            listTablesCallback(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                mapper=mapper,
            )
            or []
        )

        primaryTable = (
            self._selectPrimaryTable(
                tables
            )
        )

        if primaryTable is None:
            return {
                "handled": False
            }

        tableName = str(
            primaryTable.get("name")
            or ""
        ).strip()

        schema = (
            getSchemaCallback(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                tableName=tableName,
                mapper=mapper,
            )
            or {}
        )

        metadataColumns = (
            self._selectColumns(
                schema
            )
        )

        if not metadataColumns:
            return {
                "handled": False
            }

        sortBy = (
            self._resolveSortColumn(
                metadataColumns
            )
        )

        pageData = (
            getPageCallback(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                tableName=tableName,
                page=1,
                pageSize=self.DEFAULT_PAGE_SIZE,
                sortBy=sortBy,
                asc=True,
                selectionOnly=False,
                mapper=mapper,
            )
            or {}
        )

        columns = [
            self._buildColumn(
                column
            )
            for column in metadataColumns
        ]

        rows = self._buildRows(
            pageData,
            metadataColumns,
        )

        pageNumber = self._safeInt(
            pageData.get("pageNumber"),
            1,
        )

        pageSize = self._safeInt(
            pageData.get("pageSize"),
            self.DEFAULT_PAGE_SIZE,
        )

        totalRows = self._safeInt(
            pageData.get("totalRows"),
            self._safeInt(
                primaryTable.get(
                    "rowCount"
                ),
                len(rows),
            ),
        )

        tableTitle = str(
            primaryTable.get("alias")
            or tableName
            or outputName
        ).strip()

        return {
            "handled": True,
            "viewer": "table",
            "title": outputName,
            "context": {
                "projectId": projectId,
                "protocolId": protocolId,
                "outputName": outputName,
                "pointerClass": pointerClass,
                "tableKey": tableName,
            },
            "table": {
                "title": tableTitle,
                "columns": columns,
                "rows": rows,
                "actions": [
                    {
                        "id": "metadata",
                        "label": "Metadata",
                    },
                ],
                "page": {
                    "offset": max(
                        0,
                        (
                            pageNumber - 1
                        ) * pageSize,
                    ),
                    "limit": pageSize,
                    "total": totalRows,
                },
            },
        }

    @staticmethod
    def _formatDimensions(
            dimensions: Any,
    ) -> str:
        if not isinstance(
                dimensions,
                (
                        list,
                        tuple,
                ),
        ):
            return str(
                dimensions or ""
            )

        values = [
            str(value)
            for value in dimensions
            if value is not None
        ]

        return " × ".join(values)

    @staticmethod
    def _formatVoxelSize(
            voxelSize: Any,
    ) -> Any:
        if not isinstance(
                voxelSize,
                (
                        list,
                        tuple,
                ),
        ):
            return voxelSize

        values = [
            value
            for value in voxelSize
            if value is not None
        ]

        if not values:
            return None

        if all(
                value == values[0]
                for value in values
        ):
            return values[0]

        return " × ".join(
            str(value)
            for value in values
        )

    def _resolveCoordinates3dRoot(
            self,
            *,
            projectId: int,
            protocolId: int,
            outputName: str,
            pointerClass: str,
            mapper,
            listTomogramsCallback: Callable,
    ) -> Dict[str, Any]:
        tomograms = (
                listTomogramsCallback(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    mapper=mapper,
                )
                or []
        )

        rows = []

        for index, tomogram in enumerate(
                tomograms
        ):
            if not isinstance(
                    tomogram,
                    dict,
            ):
                continue

            tomogramId = (
                    tomogram.get("id")
                    or tomogram.get("tomoId")
                    or tomogram.get("tsId")
                    or index
            )

            name = (
                    tomogram.get("label")
                    or tomogram.get("tsId")
                    or tomogram.get("name")
                    or str(tomogramId)
            )

            coordinatesCount = self._safeInt(
                tomogram.get(
                    "nCoords",
                    tomogram.get(
                        "count",
                        0,
                    ),
                ),
                0,
            )

            rows.append({
                "id": tomogramId,
                "cells": {
                    "tomogram": str(name),
                    "dimensions": self._formatDimensions(
                        tomogram.get("dims")
                    ),
                    "voxelSize": self._formatVoxelSize(
                        tomogram.get("voxelSize")
                    ),
                    "coordinates": coordinatesCount,
                },
                "data": {
                    key: value
                    for key, value in {
                        "tomoId": tomogramId,
                        "tomogramId": tomogram.get(
                            "tomoId"
                        ),
                        "tsId": tomogram.get(
                            "tsId"
                        ),
                        "tiltSeriesId": tomogram.get(
                            "tiltSeriesId"
                        ),
                        "objectId": tomogram.get(
                            "objectId"
                        ),
                        "volumeId": tomogram.get(
                            "volumeId"
                        ),
                        "fileName": tomogram.get(
                            "fileName"
                        ),
                        "sourceProtocolId": tomogram.get(
                            "sourceProtocolId"
                        ),
                        "sourceOutputName": tomogram.get(
                            "sourceOutputName"
                        ),
                    }.items()
                    if value is not None
                },
                "actions": [
                    {
                        "id": "view-coordinates3d",
                        "label": "View coordinates",
                    },
                ],
            })

        return {
            "handled": True,
            "viewer": "table",
            "title": outputName,
            "context": {
                "projectId": projectId,
                "protocolId": protocolId,
                "outputName": outputName,
                "pointerClass": pointerClass,
                "tableKey": "tomograms",
            },
            "table": {
                "title": "Tomograms",
                "columns": [
                    {
                        "id": "tomogram",
                        "label": "Tomogram",
                        "sortable": True,
                        "actions": [
                            {
                                "id": "view-coordinates3d",
                                "label": "View",
                            },
                        ],
                    },
                    {
                        "id": "dimensions",
                        "label": "Dimensions",
                        "sortable": False,
                    },
                    {
                        "id": "voxelSize",
                        "label": "Voxel size",
                        "align": "right",
                        "sortable": False,
                    },
                    {
                        "id": "coordinates",
                        "label": "Coordinates",
                        "align": "right",
                        "sortable": True,
                        "actions": [
                            {
                                "id": "view-coordinates3d",
                                "label": "View",
                            },
                        ],
                    },
                ],
                "rows": rows,
                "actions": [
                    {
                        "id": "metadata",
                        "label": "Metadata",
                    },
                ],
                "page": {
                    "offset": 0,
                    "limit": len(rows),
                    "total": len(rows),
                },
            },
        }

    def _resolveTiltSeriesRoot(
            self,
            *,
            projectId: int,
            protocolId: int,
            outputName: str,
            pointerClass: str,
            mapper,
            listTiltSeriesCallback: Callable,
    ) -> Dict[str, Any]:
        seriesItems = listTiltSeriesCallback(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
        ) or []

        rows = []

        for index, item in enumerate(seriesItems):
            if not isinstance(item, dict):
                continue

            seriesId = item.get("tiltSeriesId")

            if seriesId is None:
                seriesId = item.get("tsId")

            if seriesId is None:
                seriesId = item.get("id")

            if seriesId is None:
                seriesId = item.get("name")

            if seriesId is None:
                seriesId = item.get("label")

            if seriesId is None:
                seriesId = index

            label = (
                    item.get("label")
                    or item.get("name")
                    or item.get("tsLabel")
                    or str(seriesId)
            )

            nViews = item.get("nViews")

            if nViews is None:
                nViews = item.get("count")

            if nViews is None:
                nViews = item.get("nTilts")

            if nViews is None:
                nViews = item.get("n")

            nViews = self._safeInt(nViews, 0)

            dimensions = self._formatDimensions(
                item.get("dims")
                or item.get("shape")
                or item.get("size")
            )

            pixelSize = item.get("pixelSize")

            if pixelSize is None:
                pixelSize = item.get("samplingRate")

            tiltAxisAngle = item.get("tiltAxisAngle")

            if tiltAxisAngle is None:
                tiltAxisAngle = item.get("tilt_axis_angle")

            if tiltAxisAngle is None:
                tiltAxisAngle = item.get("axisAngle")

            rows.append({
                "id": seriesId,
                "cells": {
                    "tiltSeries": str(label),
                    "dimensions": dimensions,
                    "pixelSize": pixelSize,
                    "tiltAxisAngle": tiltAxisAngle,
                    "tiltImages": nViews,
                        },
                "data": {
                    "kind": "tiltSeries",
                    "tiltSeriesId": seriesId,
                    "label": str(label),
                },
                "defaultAction": {
                    "id": "view-tiltseries",
                    "label": "View",
                },
                "children": {
                    "id": "tiltImages",
                    "label": "Tilt images",
                    "count": nViews,
                },
            })

        return {
            "handled": True,
            "viewer": "table",
            "title": outputName,
            "context": {
                "projectId": projectId,
                "protocolId": protocolId,
                "outputName": outputName,
                "pointerClass": pointerClass,
                "tableKey": "tiltSeries",
            },
            "table": {
                "title": "Tilt series",
                "columns": [
                    {
                        "id": "tiltSeries",
                        "label": "Tilt series",
                        "width": "28%",
                        "sortable": True,
                    },
                    {
                        "id": "dimensions",
                        "label": "Dimensions",
                        "width": "22%",
                    },
                    {
                        "id": "pixelSize",
                        "label": "Pixel size (Å/px)",
                        "width": "18%",
                        "align": "right",
                    },
                    {
                        "id": "tiltAxisAngle",
                        "label": "Tilt axis",
                        "width": "17%",
                        "align": "right",
                    },
                    {
                        "id": "tiltImages",
                        "label": "Tilt images",
                        "width": "15%",
                        "align": "right",
                    },
                ],
                "rows": rows,
                "actions": [
                    {
                        "id": "metadata",
                        "label": "Metadata",
                    },
                ],
                "page": {
                    "offset": 0,
                    "limit": len(rows),
                    "total": len(rows),
                },
            },
        }

    def resolveChildren(
            self,
            *,
            projectId: int,
            protocolId: int,
            payload: Dict[str, Any],
            mapper,
            getTiltSeriesFramesCallback: Callable,
    ) -> Dict[str, Any]:
        outputName = str(payload.get("outputName") or "").strip()
        pointerClass = str(payload.get("pointerClass") or "").strip()
        childrenId = str(payload.get("childrenId") or "").strip()
        rowId = payload.get("rowId")

        rowData = payload.get("rowData")

        if not isinstance(rowData, dict):
            rowData = {}

        normalizedClass = self._normalizeClassName(pointerClass)

        if (
                normalizedClass != "setoftiltseriesm"
                and "setoftiltseries" in normalizedClass
                and childrenId == "tiltImages"
        ):
            tiltSeriesId = rowData.get("tiltSeriesId") or rowId

            if tiltSeriesId is None:
                return {"rows": []}

            raw = getTiltSeriesFramesCallback(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                tiltSeriesId=str(tiltSeriesId),
                mapper=mapper,
            ) or {}

            if isinstance(raw, list):
                frames = raw
            elif isinstance(raw, dict):
                frames = (
                        raw.get("frames")
                        or raw.get("views")
                        or raw.get("items")
                        or []
                )
            else:
                frames = []

            rows = []

            for localIndex, frame in enumerate(frames):
                if not isinstance(frame, dict):
                    continue

                viewId = frame.get("viewId")

                if viewId is None:
                    viewId = frame.get("id")

                if viewId is None:
                    viewId = frame.get("index")

                if viewId is None:
                    viewId = localIndex

                frameIndex = frame.get("index")

                if frameIndex is None:
                    frameIndex = localIndex

                rows.append({
                    "id": f"{tiltSeriesId}:{viewId}",
                    "cells": {
                        "index": frameIndex,
                        "order": frame.get("order"),
                        "tiltAngle": frame.get("tiltAngle"),
                        "excluded": bool(
                            frame.get("excluded", False)
                        ),
                        "dose": frame.get("dose"),
                        "path": frame.get("path"),
                        "rot": frame.get("rot"),
                        "shiftX": frame.get("shiftX"),
                        "shiftY": frame.get("shiftY"),
                    },
                    "data": {
                        "kind": "tiltImage",
                        "tiltSeriesId": tiltSeriesId,
                        "viewId": viewId,
                        "frameIndex": frameIndex,
                    },
                    "defaultAction": {
                        "id": "view-tiltseries",
                        "label": "View",
                    },
                })

            return {
                "title": "Tilt images",
                "columns": [
                    {
                        "id": "index",
                        "label": "Index",
                        "width": "8%",
                        "align": "right",
                    },
                    {
                        "id": "order",
                        "label": "Order",
                        "width": "8%",
                        "align": "right",
                    },
                    {
                        "id": "tiltAngle",
                        "label": "Tilt angle",
                        "width": "11%",
                        "align": "right",
                    },
                    {
                        "id": "excluded",
                        "label": "Excl.",
                        "width": "8%",
                        "align": "center",
                    },
                    {
                        "id": "dose",
                        "label": "Dose",
                        "width": "9%",
                        "align": "right",
                    },
                    {
                        "id": "path",
                        "label": "Path",
                        "width": "28%",
                    },
                    {
                        "id": "rot",
                        "label": "Rot",
                        "width": "9%",
                        "align": "right",
                    },
                    {
                        "id": "shiftX",
                        "label": "Shift X",
                        "width": "9%",
                        "align": "right",
                    },
                    {
                        "id": "shiftY",
                        "label": "Shift Y",
                        "width": "10%",
                        "align": "right",
                    },
                ],
                "rows": rows,
            }

        return {
            "columns": [],
            "rows": [],
        }

    def resolveAction(
            self,
            *,
            projectId: int,
            protocolId: int,
            payload: Dict[str, Any],
            mapper=None,
    ) -> Dict[str, Any]:
        outputName = str(
            payload.get("outputName")
            or ""
        ).strip()

        pointerClass = str(
            payload.get("pointerClass")
            or ""
        ).strip()

        actionId = str(
            payload.get("actionId")
            or ""
        ).strip()

        rowId = payload.get(
            "rowId"
        )

        rowData = payload.get(
            "rowData"
        )

        if not isinstance(
                rowData,
                dict,
        ):
            rowData = {}

        if not outputName or not actionId:
            return {
                "kind": "empty",
                "message": (
                    "Missing output or action."
                ),
            }

        normalizedClass = (
            self._normalizeClassName(
                pointerClass
            )
        )

        if (
                "setofcoordinates3d"
                in normalizedClass
                and actionId
                == "view-coordinates3d"
        ):
            tomogramId = (
                    rowData.get("tomoId")
                    or rowData.get("tomogramId")
                    or rowData.get("tsId")
                    or rowId
            )

            if tomogramId in (
                    None,
                    "",
            ):
                return {
                    "kind": "empty",
                    "message": (
                        "Tomogram id is missing."
                    ),
                }

            return {
                "kind": "coords3d",
                "title": "Coordinates 3D · "f"{tomogramId}",
                "projectId": projectId,
                "protocolId": protocolId,
                "outputName": outputName,
                "tomogramId": tomogramId,
            }

        if (
                "setoftiltseries"
                in normalizedClass
                and actionId
                == "view-tiltseries"
        ):
            tiltSeriesId = (
                    rowData.get("tiltSeriesId")
                    or rowId
            )

            if tiltSeriesId in (
                    None,
                    "",
            ):
                return {
                    "kind": "empty",
                    "message": (
                        "Tilt series id is missing."
                    ),
                }

            frameIndex = rowData.get(
                "frameIndex"
            )

            content = {
                "kind": "tiltSeries",
                "title": (
                    f"Tilt series · {tiltSeriesId}"
                ),
                "projectId": projectId,
                "protocolId": protocolId,
                "outputName": outputName,
                "tiltSeriesId": tiltSeriesId,
            }

            if frameIndex is not None:
                content["frameIndex"] = (
                    self._safeInt(
                        frameIndex,
                        0,
                    )
                )

                content["title"] = (
                    f"Tilt image · "
                    f"{tiltSeriesId} · "
                    f"{frameIndex}"
                )

            return content

        return {
            "kind": "empty",
            "message": (
                "No viewer is registered "
                f"for action '{actionId}'."
            ),
        }