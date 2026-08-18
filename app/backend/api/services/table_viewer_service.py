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
import logging
from typing import Any, Callable, Dict, List, Optional
from app.backend.api.services.output_viewer_descriptor import (
    OutputViewerDescriptor,
    VIEWER_CAPABILITY_SET,
    VIEWER_CAPABILITY_COORDINATES3D,
    VIEWER_CAPABILITY_TILT_SERIES,
    VIEWER_CAPABILITY_CTF_TOMO,
    VIEWER_CAPABILITY_TOMOGRAMS,
)


logger = logging.getLogger(__name__)


class TableViewerService:
    DEFAULT_PAGE_SIZE = 100

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
            descriptor: OutputViewerDescriptor,
            mapper,
            listTablesCallback: Callable,
            getSchemaCallback: Callable,
            getPageCallback: Callable,
            listCoordinates3dTomogramsCallback: Callable,
            listTiltSeriesCallback: Callable,
            listCtftomoSeriesCallback: Callable,
            listVolumesCallback: Callable,
            listRelatedOutputsCallback: Callable,
    ) -> Dict[str, Any]:
        outputName = str(
            ctx.get("outputName")
            or ""
        ).strip()

        pointerClass = (
                descriptor.className
                or str(
            ctx.get("pointerClass")
            or ""
        ).strip()
        )

        if (
                not outputName
                or not descriptor.hasCapability(
            VIEWER_CAPABILITY_SET
        )
        ):
            return {
                "handled": False
            }

        resolverRegistry = (
            (
                VIEWER_CAPABILITY_COORDINATES3D,
                lambda:
                self._resolveCoordinates3dRoot(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    pointerClass=pointerClass,
                    mapper=mapper,
                    listTomogramsCallback=(
                        listCoordinates3dTomogramsCallback
                    ),
                ),
            ),
            (
                VIEWER_CAPABILITY_TILT_SERIES,
                lambda:
                self._resolveTiltSeriesRoot(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    pointerClass=pointerClass,
                    mapper=mapper,
                    listTiltSeriesCallback=(
                        listTiltSeriesCallback
                    ),
                ),
            ),
            (
                VIEWER_CAPABILITY_CTF_TOMO,
                lambda:
                self._resolveCtftomoRoot(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    pointerClass=pointerClass,
                    mapper=mapper,
                    listCtftomoSeriesCallback=(
                        listCtftomoSeriesCallback
                    ),
                ),
            ),
            (
                VIEWER_CAPABILITY_TOMOGRAMS,
                lambda:
                self._resolveTomogramsRoot(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    pointerClass=pointerClass,
                    mapper=mapper,
                    listVolumesCallback=(
                        listVolumesCallback
                    ),
                    listRelatedOutputsCallback=listRelatedOutputsCallback,
                    listCoordinates3dTomogramsCallback=listCoordinates3dTomogramsCallback,
                    listTiltSeriesCallback=listTiltSeriesCallback,
                    listCtftomoSeriesCallback=listCtftomoSeriesCallback,
                ),
            ),
        )

        for capability, resolver in resolverRegistry:
            if not descriptor.hasCapability(
                    capability
            ):
                continue

            try:
                decision = resolver()

                if (
                        isinstance(
                            decision,
                            dict,
                        )
                        and decision.get(
                    "handled"
                )
                ):
                    return decision

            except Exception:
                logger.warning(
                    "Specialized table viewer failed. "
                    "Falling back to generic table. "
                    "projectId=%s protocolId=%s "
                    "outputName=%s capability=%s "
                    "className=%s",
                    projectId,
                    protocolId,
                    outputName,
                    capability,
                    descriptor.className,
                    exc_info=True,
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

            tomogramId = tomogram.get(
                "id"
            )

            if tomogramId is None:
                tomogramId = tomogram.get(
                    "tomoId"
                )

            if tomogramId is None:
                tomogramId = tomogram.get(
                    "tsId"
                )

            if tomogramId is None:
                tomogramId = index

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

    @staticmethod
    def _normalizeRelationKey(value: Any) -> Optional[str]:
        if value is None:
            return None

        text = str(value).strip()
        return text if text else None

    @classmethod
    def _buildRelationKeys(
            cls,
            item: Dict[str, Any],
            fields: List[str],
    ) -> List[str]:
        result = []
        seen = set()

        for field in fields:
            key = cls._normalizeRelationKey(item.get(field))

            if key is None or key in seen:
                continue

            seen.add(key)
            result.append(key)

        return result

    @classmethod
    def _buildRelatedItemIndex(
            cls,
            items: List[Dict[str, Any]],
            fields: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        result = {}

        for item in items or []:
            if not isinstance(item, dict):
                continue

            for key in cls._buildRelationKeys(item, fields):
                result.setdefault(key, []).append(item)

        return result

    @classmethod
    def _findUniqueRelatedMatch(
            cls,
            sourceKeys: List[str],
            catalogs: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        matches = []

        for catalog in catalogs:
            index = catalog.get("index") or {}
            matchedItems = {}

            for key in sourceKeys:
                for item in index.get(key, []):
                    matchedItems[id(item)] = item

            if len(matchedItems) != 1:
                continue

            distance = catalog.get("distance")

            try:
                distance = int(distance)
            except (TypeError, ValueError):
                distance = 1

            if distance < 1:
                distance = 1

            matches.append({
                "target": catalog.get("target") or {},
                "item": next(iter(matchedItems.values())),
                "distance": distance,
            })

        if not matches:
            return None

        minimumDistance = min(
            match["distance"]
            for match in matches
        )

        nearestMatches = [
            match
            for match in matches
            if match["distance"] == minimumDistance
        ]

        if len(nearestMatches) != 1:
            return None

        return nearestMatches[0]

    def _resolveTomogramsRoot(
            self,
            *,
            projectId: int,
            protocolId: int,
            outputName: str,
            pointerClass: str,
            mapper,
            listVolumesCallback: Callable,
            listRelatedOutputsCallback: Callable,
            listCoordinates3dTomogramsCallback: Callable,
            listTiltSeriesCallback: Callable,
            listCtftomoSeriesCallback: Callable,
    ) -> Dict[str, Any]:
        volumes = listVolumesCallback(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
        ) or []

        relatedCatalogs = {
            VIEWER_CAPABILITY_TILT_SERIES: [],
            VIEWER_CAPABILITY_CTF_TOMO: [],
            VIEWER_CAPABILITY_COORDINATES3D: [],
        }

        relationConfigs = (
            (
                VIEWER_CAPABILITY_TILT_SERIES,
                listTiltSeriesCallback,
                [
                    "tiltSeriesId",
                    "tsId",
                    "label",
                    "name",
                ],
            ),
            (
                VIEWER_CAPABILITY_CTF_TOMO,
                listCtftomoSeriesCallback,
                [
                    "ctfSeriesId",
                    "tiltSeriesId",
                    "tsId",
                    "label",
                    "name",
                ],
            ),
            (
                VIEWER_CAPABILITY_COORDINATES3D,
                listCoordinates3dTomogramsCallback,
                [
                    "tomoId",
                    "tomogramId",
                    "sourceTomoId",
                    "coordinatesTomogramId",
                    "id",
                    "tsId",
                    "tiltSeriesId",
                    "label",
                    "name",
                ],
            ),
        )

        try:
            relatedOutputs = listRelatedOutputsCallback(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                mapper=mapper,
            ) or []
        except Exception:
            logger.warning(
                "Could not resolve related outputs for tomogram table. "
                "projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
                exc_info=True,
            )
            relatedOutputs = []

        for relatedOutput in relatedOutputs:
            if not isinstance(relatedOutput, dict):
                continue

            target = relatedOutput.get("target")

            if not isinstance(target, dict):
                continue

            targetProtocolId = target.get("protocolId")
            targetOutputName = str(target.get("outputName") or "").strip()

            if targetProtocolId is None or targetProtocolId == "" or not targetOutputName:
                continue

            capabilities = set(relatedOutput.get("capabilities") or [])

            for capability, callback, fields in relationConfigs:
                if capability not in capabilities:
                    continue

                try:
                    items = callback(
                        projectId=projectId,
                        protocolId=targetProtocolId,
                        outputName=targetOutputName,
                        mapper=mapper,
                    ) or []
                except Exception:
                    logger.warning(
                        "Could not load related output for tomogram table. "
                        "projectId=%s protocolId=%s outputName=%s capability=%s",
                        projectId,
                        targetProtocolId,
                        targetOutputName,
                        capability,
                        exc_info=True,
                    )
                    continue

                itemIndex = self._buildRelatedItemIndex(
                    items,
                    fields,
                )

                if not itemIndex:
                    continue

                relatedCatalogs[capability].append({
                    "target": dict(target),
                    "index": itemIndex,
                    "distance": relatedOutput.get("distance", 1),
                })

        rows = []

        hasTiltSeries = False
        hasCtf = False
        hasCoordinates = False

        for index, volume in enumerate(volumes):
            if not isinstance(volume, dict):
                continue

            volumeId = volume.get("id")

            if volumeId is None:
                volumeId = volume.get("index")

            if volumeId is None:
                volumeId = index

            tomogramId = volume.get("tomoId")

            if tomogramId is None:
                tomogramId = volume.get("tomogramId")

            if tomogramId is None:
                tomogramId = volume.get("tsId")

            if tomogramId is None:
                tomogramId = volume.get("tiltSeriesId")

            if tomogramId is None:
                tomogramId = volume.get("label")

            if tomogramId is None:
                tomogramId = volume.get("name")

            if tomogramId is None:
                tomogramId = volumeId

            label = volume.get("label")

            if label is None or label == "":
                label = volume.get("name")

            if label is None or label == "":
                label = str(tomogramId)

            voxelSize = volume.get("samplingRate")

            if voxelSize is None:
                voxelSize = volume.get("pixelSize")

            if voxelSize is None:
                voxelSize = volume.get("voxelSize")

            sourceKeys = self._buildRelationKeys(
                volume,
                [
                    "tiltSeriesId",
                    "tsId",
                    "tomoId",
                    "tomogramId",
                    "label",
                    "name",
                ],
            )

            cells = {
                "tomogram": str(label),
                "dimensions": self._formatDimensions(volume.get("dims")),
                "voxelSize": self._formatVoxelSize(voxelSize),
            }

            cellContexts = {
                "tomogram": {
                    "target": {
                        "protocolId": protocolId,
                        "outputName": outputName,
                        "pointerClass": pointerClass,
                    },
                    "data": {
                        "kind": "tomogram",
                        "volumeId": volumeId,
                        "tomogramId": tomogramId,
                        "label": str(label),
                    },
                    "defaultAction": {
                        "id": "view-volume",
                        "label": "View",
                    },
                },
            }

            tiltMatch = self._findUniqueRelatedMatch(
                sourceKeys,
                relatedCatalogs[VIEWER_CAPABILITY_TILT_SERIES],
            )

            if tiltMatch is not None:
                tiltItem = tiltMatch["item"]
                tiltSeriesId = tiltItem.get("tiltSeriesId")

                if tiltSeriesId is None:
                    tiltSeriesId = tiltItem.get("tsId")

                if tiltSeriesId is not None:
                    tiltLabel = tiltItem.get("label")

                    if tiltLabel is None or tiltLabel == "":
                        tiltLabel = tiltItem.get("name")

                    if tiltLabel is None or tiltLabel == "":
                        tiltLabel = str(tiltSeriesId)

                    tiltViewsCount = tiltItem.get(
                        "nViews"
                    )

                    if tiltViewsCount is None:
                        tiltViewsCount = tiltItem.get(
                            "count"
                        )

                    if tiltViewsCount is None:
                        tiltViewsCount = tiltItem.get(
                            "nTilts"
                        )

                    tiltViewsCount = self._safeInt(
                        tiltViewsCount,
                        0,
                    )

                    tiltExcluded = bool(
                        tiltItem.get(
                            "excluded",
                            False,
                        )
                    )

                    cells["tiltSeries"] = str(
                        tiltLabel
                    )

                    cellContexts["tiltSeries"] = {
                        "target": tiltMatch[
                            "target"
                        ],
                        "data": {
                            "kind": "tiltSeries",
                            "tiltSeriesId":
                                tiltSeriesId,
                            "excluded":
                                tiltExcluded,
                        },
                        "defaultAction": {
                            "id":
                                "view-tiltseries",
                            "label":
                                "View",
                        },
                        "children": {
                            "id":
                                "tiltImages",
                            "label":
                                "Tilt images",
                            "count":
                                tiltViewsCount,
                            "readOnly":
                                True,
                        },
                    }

                    hasTiltSeries = True

            ctfMatch = self._findUniqueRelatedMatch(
                sourceKeys,
                relatedCatalogs[VIEWER_CAPABILITY_CTF_TOMO],
            )

            if ctfMatch is not None:
                ctfItem = ctfMatch["item"]
                ctfSeriesId = ctfItem.get("ctfSeriesId")

                if ctfSeriesId is None:
                    ctfSeriesId = ctfItem.get("tiltSeriesId")

                if ctfSeriesId is None:
                    ctfSeriesId = ctfItem.get("tsId")

                if ctfSeriesId is not None:
                    ctfLabel = ctfItem.get("label")

                    if ctfLabel is None or ctfLabel == "":
                        ctfLabel = str(ctfSeriesId)

                    ctfTiltSeriesId = (
                        ctfItem.get(
                            "tiltSeriesId"
                        )
                    )

                    if ctfTiltSeriesId is None:
                        ctfTiltSeriesId = (
                            ctfItem.get(
                                "tsId"
                            )
                        )

                    ctfViewsCount = ctfItem.get(
                        "nViews"
                    )

                    if ctfViewsCount is None:
                        ctfViewsCount = ctfItem.get(
                            "count"
                        )

                    if ctfViewsCount is None:
                        ctfViewsCount = ctfItem.get(
                            "nTilts"
                        )

                    ctfViewsCount = self._safeInt(
                        ctfViewsCount,
                        0,
                    )

                    ctfExcluded = bool(
                        ctfItem.get(
                            "excluded",
                            False,
                        )
                    )

                    cells["ctf"] = str(
                        ctfLabel
                    )

                    cellContexts["ctf"] = {
                        "target": ctfMatch[
                            "target"
                        ],
                        "data": {
                            "kind":
                                "ctfTomo",
                            "ctfSeriesId":
                                ctfSeriesId,
                            "tiltSeriesId":
                                ctfTiltSeriesId,
                            "excluded":
                                ctfExcluded,
                        },
                        "defaultAction": {
                            "id":
                                "view-ctftomo",
                            "label":
                                "View",
                        },
                        "children": {
                            "id":
                                "ctfViews",
                            "label":
                                "CTF views",
                            "count":
                                ctfViewsCount,
                            "readOnly":
                                True,
                        },
                    }

                    hasCtf = True

            coordinatesMatch = self._findUniqueRelatedMatch(
                sourceKeys,
                relatedCatalogs[VIEWER_CAPABILITY_COORDINATES3D],
            )

            if coordinatesMatch is not None:
                coordinatesItem = coordinatesMatch["item"]
                coordinatesTomogramId = coordinatesItem.get("tomoId")

                if coordinatesTomogramId is None:
                    coordinatesTomogramId = coordinatesItem.get("tomogramId")

                if coordinatesTomogramId is None:
                    coordinatesTomogramId = coordinatesItem.get("id")

                if coordinatesTomogramId is not None:
                    coordinatesCount = coordinatesItem.get("nCoords")

                    if coordinatesCount is None:
                        coordinatesCount = coordinatesItem.get("count")

                    if coordinatesCount is None:
                        coordinatesCount = coordinatesTomogramId

                    cells["coordinates"] = coordinatesCount
                    cellContexts["coordinates"] = {
                        "target": coordinatesMatch["target"],
                        "data": {
                            "tomoId": coordinatesTomogramId,
                            "tomogramId": coordinatesTomogramId,
                        },
                        "defaultAction": {
                            "id": "view-coordinates3d",
                            "label": "View",
                        },
                    }
                    hasCoordinates = True

            rowData = {
                "kind": "tomogram",
                "volumeId": volumeId,
                "tomogramId": tomogramId,
                "label": str(label),
            }

            for key in (
                    "tomoId",
                    "tsId",
                    "tiltSeriesId",
                    "objectId",
            ):
                value = volume.get(key)

                if value is not None:
                    rowData[key] = value

            rows.append({
                "id": tomogramId,
                "cells": cells,
                "data": rowData,
                "cellContexts": cellContexts,
                "defaultAction": {
                    "id": "view-volume",
                    "label": "View",
                },
            })

        columns = [
            {
                "id": "tomogram",
                "label": "Tomogram",
                "width": "24%",
                "sortable": True,
            },
        ]

        if hasTiltSeries:
            columns.append({
                "id": "tiltSeries",
                "label": "Tilt series",
                "width": "17%",
            })

        if hasCtf:
            columns.append({
                "id": "ctf",
                "label": "CTF",
                "width": "17%",
            })

        if hasCoordinates:
            columns.append({
                "id": "coordinates",
                "label": "Coordinates",
                "width": "12%",
                "align": "right",
            })

        columns.extend([
            {
                "id": "dimensions",
                "label": "Dimensions",
                "width": "18%",
            },
            {
                "id": "voxelSize",
                "label": "Voxel size (Å/px)",
                "width": "12%",
                "align": "right",
            },
        ])

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
                "columns": columns,
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

    def _resolveCtftomoRoot(
            self,
            *,
            projectId: int,
            protocolId: int,
            outputName: str,
            pointerClass: str,
            mapper,
            listCtftomoSeriesCallback: Callable,
    ) -> Dict[str, Any]:
        seriesItems = (
                listCtftomoSeriesCallback(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    mapper=mapper,
                )
                or []
        )

        rows = []

        for index, item in enumerate(
                seriesItems
        ):
            if not isinstance(
                    item,
                    dict,
            ):
                continue

            seriesId = item.get(
                "ctfSeriesId"
            )

            if seriesId is None:
                seriesId = item.get(
                    "tiltSeriesId"
                )

            if seriesId is None:
                seriesId = item.get(
                    "tsId"
                )

            if seriesId is None:
                seriesId = item.get(
                    "id"
                )

            if seriesId is None:
                seriesId = index

            tiltSeriesId = item.get(
                "tiltSeriesId"
            )

            if tiltSeriesId is None:
                tiltSeriesId = item.get(
                    "tsId"
                )

            if tiltSeriesId is None:
                tiltSeriesId = seriesId

            label = (
                    item.get("label")
                    or item.get("name")
                    or str(seriesId)
            )

            nViews = item.get(
                "nViews"
            )

            if nViews is None:
                nViews = item.get(
                    "count"
                )

            if nViews is None:
                nViews = item.get(
                    "nTilts"
                )

            nViews = self._safeInt(
                nViews,
                0,
            )

            excluded = bool(
                item.get(
                    "excluded",
                    False,
                )
            )

            dimensions = (
                self._formatDimensions(
                    item.get("dims")
                    or item.get("shape")
                    or item.get("size")
                )
            )

            pixelSize = item.get(
                "pixelSize"
            )

            if pixelSize is None:
                pixelSize = item.get(
                    "samplingRate"
                )

            rows.append({
                "id": seriesId,

                "cells": {
                    "ctfSeries": str(
                        label
                    ),
                    "dimensions":
                        dimensions,
                    "pixelSize":
                        pixelSize,
                    "excluded":
                        excluded,
                    "ctfViews":
                        nViews,
                },

                "data": {
                    "kind": "ctfTomo",
                    "ctfSeriesId":
                        seriesId,
                    "tiltSeriesId":
                        tiltSeriesId,
                    "excluded":
                        excluded,
                    "label":
                        str(label),
                },

                "cellContexts": {
                    "ctfSeries": {
                        "target": {
                            "protocolId":
                                protocolId,
                            "outputName":
                                outputName,
                            "pointerClass":
                                pointerClass,
                        },
                        "data": {
                            "kind":
                                "ctfTomo",
                            "ctfSeriesId":
                                seriesId,
                            "tiltSeriesId":
                                tiltSeriesId,
                            "label":
                                str(label),
                        },
                        "defaultAction": {
                            "id":
                                "view-ctftomo",
                            "label":
                                "View",
                        },
                    },

                    "excluded": {
                        "edit": {
                            "type":
                                "boolean",
                            "field":
                                "excluded",

                            "cascadeToChildren": {
                                "childrenId":
                                    "ctfViews",
                                "columnId":
                                    "excluded",
                            },
                        },
                    },
                },

                "defaultAction": {
                    "id":
                        "view-ctftomo",
                    "label":
                        "View",
                },

                "children": {
                    "id":
                        "ctfViews",
                    "label":
                        "CTF views",
                    "count":
                        nViews,
                },
            })

        return {
            "handled": True,
            "viewer": "table",
            "title": outputName,

            "context": {
                "projectId":
                    projectId,
                "protocolId":
                    protocolId,
                "outputName":
                    outputName,
                "pointerClass":
                    pointerClass,
                "tableKey":
                    "ctfTomo",
            },

            "table": {
                "title":
                    "CTF tomography",

                "columns": [
                    {
                        "id":
                            "ctfSeries",
                        "label":
                            "CTF series",
                        "width":
                            "31%",
                        "sortable":
                            True,
                    },
                    {
                        "id":
                            "dimensions",
                        "label":
                            "Dimensions",
                        "width":
                            "24%",
                    },
                    {
                        "id":
                            "pixelSize",
                        "label":
                            "Pixel size (Å/px)",
                        "width":
                            "20%",
                        "align":
                            "right",
                    },
                    {
                        "id":
                            "excluded",
                        "label":
                            "Excl.",
                        "width":
                            "9%",
                        "align":
                            "center",
                    },
                    {
                        "id":
                            "ctfViews",
                        "label":
                            "CTF views",
                        "width":
                            "16%",
                        "align":
                            "right",
                    },
                ],

                "rows":
                    rows,

                "actions": [
                    {
                        "id":
                            "metadata",
                        "label":
                            "Metadata",
                    },
                ],

                "editActions": [
                    {
                        "id":
                            "create-filtered-output",
                        "label":
                            "Generate subsets",
                        "requiresChanges":
                            True,
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

            excluded = bool(
                item.get(
                    "excluded",
                    False,
                )
            )

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
                    "excluded": excluded,
                    "tiltImages": nViews,
                        },
                "data": {
                    "kind": "tiltSeries",
                    "tiltSeriesId": seriesId,
                    "label": str(label),
                },
                "cellContexts": {
                    "tiltSeries": {
                        "target": {
                            "protocolId": protocolId,
                            "outputName": outputName,
                            "pointerClass": pointerClass,
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
                    },
                    "excluded": {
                        "edit": {
                            "type": "boolean",
                            "field": "excluded",
                            "cascadeToChildren": {
                                "childrenId": "tiltImages",
                                "columnId": "excluded",
                            },
                        },
                    },
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
                        "width": "25%",
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
                        "width": "14%",
                        "align": "right",
                    },
                    {
                        "id": "excluded",
                        "label": "Excl.",
                        "width": "9%",
                        "align": "center",
                    },
                    {
                        "id": "tiltImages",
                        "label": "Tilt images",
                        "width": "12%",
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
                "editActions": [
                    {
                        "id": (
                            "create-filtered-output"
                        ),
                        "label": "Save",
                        "requiresChanges": True,
                    },
                    {
                        "id": (
                            "create-restacked-output"
                        ),
                        "label": "Re-stack",
                        "requiresChanges": True,
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
            descriptor: OutputViewerDescriptor,
            mapper,
            getTiltSeriesFramesCallback: Callable,
            getCtftomoSeriesViewsCallback: Callable,
    ) -> Dict[str, Any]:
        outputName = str(payload.get("outputName") or "").strip()
        childrenId = str(payload.get("childrenId") or "").strip()
        rowId = payload.get("rowId")

        rowData = payload.get("rowData")

        if not isinstance(rowData, dict):
            rowData = {}

        if (
                descriptor.hasCapability(
                    VIEWER_CAPABILITY_TILT_SERIES
                )
                and childrenId == "tiltImages"
        ):
            tiltSeriesId = rowData.get(
                "tiltSeriesId"
            )

            if tiltSeriesId is None:
                tiltSeriesId = rowId

            if tiltSeriesId is None:
                return {
                    "columns": [],
                    "rows": [],
                }

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
                    "cellContexts": {
                        "excluded": {
                            "edit": {
                                "type": "boolean",
                                "field": "excluded",
                            },
                        },
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
                        "width": "25%",
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

        if (
                descriptor.hasCapability(
                    VIEWER_CAPABILITY_CTF_TOMO
                )
                and childrenId
                == "ctfViews"
        ):
            ctfSeriesId = rowData.get(
                "ctfSeriesId"
            )

            if ctfSeriesId is None:
                ctfSeriesId = rowData.get(
                    "tiltSeriesId"
                )

            if ctfSeriesId is None:
                ctfSeriesId = rowId

            if ctfSeriesId is None:
                return {
                    "columns": [],
                    "rows": [],
                }

            raw = (
                    getCtftomoSeriesViewsCallback(
                        projectId=projectId,
                        protocolId=protocolId,
                        outputName=outputName,
                        tiltSeriesId=str(
                            ctfSeriesId
                        ),
                        mapper=mapper,
                    )
                    or {}
            )

            if isinstance(
                    raw,
                    list,
            ):
                frames = raw

            elif isinstance(
                    raw,
                    dict,
            ):
                frames = (
                        raw.get("frames")
                        or raw.get("views")
                        or raw.get("items")
                        or []
                )

            else:
                frames = []

            parentExcluded = bool(
                rowData.get(
                    "excluded",
                    False,
                )
            )

            rows = []

            for localIndex, frame in enumerate(
                    frames
            ):
                if not isinstance(
                        frame,
                        dict,
                ):
                    continue

                viewId = frame.get(
                    "viewId"
                )

                if viewId is None:
                    viewId = frame.get(
                        "id"
                    )

                if viewId is None:
                    viewId = localIndex

                ctfIndex = frame.get(
                    "index"
                )

                if ctfIndex is None:
                    ctfIndex = localIndex

                ccValue = frame.get(
                    "ccValue"
                )

                if ccValue is None:
                    ccValue = frame.get(
                        "cc"
                    )

                rows.append({
                    "id": (
                        f"{ctfSeriesId}:"
                        f"{viewId}"
                    ),

                    "cells": {
                        "index":
                            ctfIndex,
                        "order":
                            frame.get(
                                "order"
                            ),
                        "tiltAngle":
                            frame.get(
                                "tiltAngle"
                            ),
                        "excluded": (
                            True
                            if parentExcluded
                            else bool(
                                frame.get(
                                    "excluded",
                                    False,
                                )
                            )
                        ),
                        "defocusU":
                            frame.get(
                                "defocusU"
                            ),
                        "defocusV":
                            frame.get(
                                "defocusV"
                            ),
                        "astigmatism":
                            frame.get(
                                "astigmatism"
                            ),
                        "resolution":
                            frame.get(
                                "resolution"
                            ),
                        "ccValue":
                            ccValue,
                    },

                    "data": {
                        "kind":
                            "ctfTomoView",
                        "ctfSeriesId":
                            ctfSeriesId,
                        "tiltSeriesId":
                            rowData.get(
                                "tiltSeriesId"
                            ),
                        "viewId":
                            viewId,
                        "ctfIndex":
                            ctfIndex,
                    },

                    "cellContexts": {
                        "excluded": {
                            "edit": {
                                "type":
                                    "boolean",
                                "field":
                                    "excluded",
                            },
                        },
                    },

                    "defaultAction": {
                        "id":
                            "view-ctftomo",
                        "label":
                            "View",
                    },
                })

            return {
                "title":
                    "CTF views",

                "columns": [
                    {
                        "id": "index",
                        "label": "Index",
                        "width": "7%",
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
                        "width": "7%",
                        "align": "center",
                    },
                    {
                        "id": "defocusU",
                        "label": "Defocus U",
                        "width": "14%",
                        "align": "right",
                    },
                    {
                        "id": "defocusV",
                        "label": "Defocus V",
                        "width": "14%",
                        "align": "right",
                    },
                    {
                        "id": "astigmatism",
                        "label": "Astigmatism",
                        "width": "14%",
                        "align": "right",
                    },
                    {
                        "id": "resolution",
                        "label": "Resolution",
                        "width": "13%",
                        "align": "right",
                    },
                    {
                        "id": "ccValue",
                        "label": "CC",
                        "width": "12%",
                        "align": "right",
                    },
                ],

                "rows":
                    rows,
            }

        return {
            "columns": [],
            "rows": [],
        }

    @staticmethod
    def _normalizeTiltSeriesFrames(
            raw: Any,
    ) -> List[Dict[str, Any]]:
        if isinstance(
                raw,
                list,
        ):
            return [
                frame
                for frame in raw
                if isinstance(
                    frame,
                    dict,
                )
            ]

        if isinstance(
                raw,
                dict,
        ):
            frames = (
                    raw.get("frames")
                    or raw.get("views")
                    or raw.get("items")
                    or []
            )

            if isinstance(
                    frames,
                    list,
            ):
                return [
                    frame
                    for frame in frames
                    if isinstance(
                        frame,
                        dict,
                    )
                ]

        return []

    def _buildTiltSeriesExclusionsFromEdits(
            self,
            *,
            projectId: int,
            protocolId: int,
            outputName: str,
            edits: List[Dict[str, Any]],
            mapper,
            listTiltSeriesCallback: Callable,
            getTiltSeriesFramesCallback: Callable,
    ) -> Dict[str, Any]:
        seriesItems = (
                listTiltSeriesCallback(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    mapper=mapper,
                )
                or []
        )

        exclusions = {}

        allFrameIndexes = {}
        baselineFrameExclusions = {}

        for seriesIndex, item in enumerate(
                seriesItems
        ):
            if not isinstance(
                    item,
                    dict,
            ):
                continue

            seriesId = item.get(
                "tiltSeriesId"
            )

            if seriesId is None:
                seriesId = item.get(
                    "tsId"
                )

            if seriesId is None:
                seriesId = item.get(
                    "id"
                )

            if seriesId is None:
                seriesId = item.get(
                    "name"
                )

            if seriesId is None:
                seriesId = item.get(
                    "label"
                )

            if seriesId is None:
                seriesId = (
                    seriesIndex
                )

            seriesKey = str(
                seriesId
            )

            rawFrames = (
                getTiltSeriesFramesCallback(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    tiltSeriesId=seriesKey,
                    mapper=mapper,
                )
                or {}
            )

            frames = (
                self
                ._normalizeTiltSeriesFrames(
                    rawFrames
                )
            )

            indexes = []
            excludedIndexes = []

            for framePosition, frame in enumerate(
                    frames
            ):
                frameIndex = frame.get(
                    "index"
                )

                if frameIndex is None:
                    frameIndex = (
                        framePosition
                    )

                frameIndex = (
                    self._safeInt(
                        frameIndex,
                        framePosition,
                    )
                )

                indexes.append(
                    frameIndex
                )

                if bool(
                        frame.get(
                            "excluded",
                            False,
                        )
                ):
                    excludedIndexes.append(
                        frameIndex
                    )

            indexes = sorted(
                set(indexes)
            )

            excludedIndexes = sorted(
                set(
                    excludedIndexes
                )
            )

            allFrameIndexes[
                seriesKey
            ] = indexes

            baselineFrameExclusions[
                seriesKey
            ] = excludedIndexes

            seriesExcluded = bool(
                item.get(
                    "excluded",
                    False,
                )
            )

            exclusions[
                seriesKey
            ] = {
                "excluded":
                    seriesExcluded,

                "tiltimages": (
                    list(indexes)
                    if seriesExcluded
                    else list(
                        excludedIndexes
                    )
                ),
            }

        rootEdits = {}
        childEdits = {}

        for edit in edits:
            if not isinstance(
                    edit,
                    dict,
            ):
                continue

            if str(
                    edit.get("field")
                    or ""
            ) != "excluded":
                continue

            value = bool(
                edit.get(
                    "value"
                )
            )

            rowData = edit.get(
                "rowData"
            )

            if not isinstance(
                    rowData,
                    dict,
            ):
                rowData = {}

            childrenId = str(
                edit.get(
                    "childrenId"
                )
                or ""
            )

            parentRowId = (
                edit.get(
                    "parentRowId"
                )
            )

            isChildEdit = (
                    childrenId
                    == "tiltImages"
                    or parentRowId
                    not in (
                        None,
                        "",
                    )
            )

            if isChildEdit:
                seriesId = (
                        rowData.get(
                            "tiltSeriesId"
                        )
                        or parentRowId
                )

                frameIndex = (
                    rowData.get(
                        "frameIndex"
                    )
                )

                if (
                        seriesId
                        in (
                            None,
                            "",
                        )
                        or frameIndex
                        is None
                ):
                    continue

                seriesKey = str(
                    seriesId
                )

                if (
                        seriesKey
                        not in exclusions
                ):
                    continue

                frameIndex = (
                    self._safeInt(
                        frameIndex,
                        -1,
                    )
                )

                if frameIndex < 0:
                    continue

                childEdits.setdefault(
                    seriesKey,
                    {},
                )[
                    frameIndex
                ] = value

                continue

            seriesId = (
                    rowData.get(
                        "tiltSeriesId"
                    )
                    or edit.get(
                        "rowId"
                    )
            )

            if seriesId in (
                    None,
                    "",
            ):
                continue

            seriesKey = str(
                seriesId
            )

            if (
                    seriesKey
                    not in exclusions
            ):
                continue

            rootEdits[
                seriesKey
            ] = value

        for seriesKey, entry in (
                exclusions.items()
        ):
            parentExcluded = (
                rootEdits.get(
                    seriesKey,
                    bool(
                        entry.get(
                            "excluded",
                            False,
                        )
                    ),
                )
            )

            indexes = list(
                allFrameIndexes.get(
                    seriesKey,
                    [],
                )
            )

            if parentExcluded:
                entry[
                    "excluded"
                ] = True

                entry[
                    "tiltimages"
                ] = indexes

                continue

            selectedIndexes = set(
                baselineFrameExclusions.get(
                    seriesKey,
                    [],
                )
            )

            for (
                    frameIndex,
                    excluded,
            ) in childEdits.get(
                seriesKey,
                {},
            ).items():
                if excluded:
                    selectedIndexes.add(
                        frameIndex
                    )
                else:
                    selectedIndexes.discard(
                        frameIndex
                    )

            if (
                    indexes
                    and set(
                        indexes
                    ).issubset(
                        selectedIndexes
                    )
            ):
                entry[
                    "excluded"
                ] = True

                entry[
                    "tiltimages"
                ] = indexes

            else:
                entry[
                    "excluded"
                ] = False

                entry[
                    "tiltimages"
                ] = sorted(
                    selectedIndexes
                )

        return exclusions

    def _buildCtftomoExclusionsFromEdits(
            self,
            *,
            projectId: int,
            protocolId: int,
            outputName: str,
            edits: List[
                Dict[str, Any]
            ],
            mapper,
            listCtftomoSeriesCallback:
            Callable,
            getCtftomoSeriesViewsCallback:
            Callable,
    ) -> Dict[str, Any]:

        seriesItems = (
                listCtftomoSeriesCallback(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    mapper=mapper,
                )
                or []
        )

        exclusions = {}

        allFrameIndexes = {}
        baselineFrameExclusions = {}

        for seriesPosition, item in enumerate(
                seriesItems
        ):
            if not isinstance(
                    item,
                    dict,
            ):
                continue

            seriesId = item.get(
                "ctfSeriesId"
            )

            if seriesId is None:
                seriesId = item.get(
                    "tiltSeriesId"
                )

            if seriesId is None:
                seriesId = item.get(
                    "tsId"
                )

            if seriesId is None:
                seriesId = item.get(
                    "id"
                )

            if seriesId is None:
                seriesId = (
                    seriesPosition
                )

            seriesKey = str(
                seriesId
            )

            raw = (
                    getCtftomoSeriesViewsCallback(
                        projectId=projectId,
                        protocolId=protocolId,
                        outputName=outputName,
                        tiltSeriesId=seriesKey,
                        mapper=mapper,
                    )
                    or {}
            )

            if isinstance(
                    raw,
                    list,
            ):
                frames = raw

            elif isinstance(
                    raw,
                    dict,
            ):
                frames = (
                        raw.get("frames")
                        or raw.get("views")
                        or raw.get("items")
                        or []
                )

            else:
                frames = []

            indexes = []
            excludedIndexes = []

            for framePosition, frame in enumerate(
                    frames
            ):
                if not isinstance(
                        frame,
                        dict,
                ):
                    continue

                frameIndex = frame.get(
                    "index"
                )

                if frameIndex is None:
                    frameIndex = (
                        framePosition
                    )

                frameIndex = (
                    self._safeInt(
                        frameIndex,
                        framePosition,
                    )
                )

                indexes.append(
                    frameIndex
                )

                if bool(
                        frame.get(
                            "excluded",
                            False,
                        )
                ):
                    excludedIndexes.append(
                        frameIndex
                    )

            indexes = sorted(
                set(indexes)
            )

            excludedIndexes = sorted(
                set(
                    excludedIndexes
                )
            )

            allFrameIndexes[
                seriesKey
            ] = indexes

            baselineFrameExclusions[
                seriesKey
            ] = excludedIndexes

            seriesExcluded = bool(
                item.get(
                    "excluded",
                    False,
                )
            )

            exclusions[
                seriesKey
            ] = {
                "excluded":
                    seriesExcluded,

                "tiltimages": (
                    list(indexes)
                    if seriesExcluded
                    else list(
                        excludedIndexes
                    )
                ),
            }

        rootEdits = {}
        childEdits = {}

        for edit in edits:
            if not isinstance(
                    edit,
                    dict,
            ):
                continue

            if str(
                    edit.get(
                        "field"
                    )
                    or ""
            ) != "excluded":
                continue

            value = bool(
                edit.get(
                    "value"
                )
            )

            rowData = edit.get(
                "rowData"
            )

            if not isinstance(
                    rowData,
                    dict,
            ):
                rowData = {}

            childrenId = str(
                edit.get(
                    "childrenId"
                )
                or ""
            )

            parentRowId = (
                edit.get(
                    "parentRowId"
                )
            )

            isChildEdit = (
                    childrenId
                    == "ctfViews"
                    or parentRowId
                    not in (
                        None,
                        "",
                    )
            )

            if isChildEdit:
                seriesId = (
                    rowData.get(
                        "ctfSeriesId"
                    )
                )

                if seriesId is None:
                    seriesId = (
                        rowData.get(
                            "tiltSeriesId"
                        )
                    )

                if seriesId is None:
                    seriesId = (
                        parentRowId
                    )

                frameIndex = (
                    rowData.get(
                        "ctfIndex"
                    )
                )

                if frameIndex is None:
                    frameIndex = (
                        rowData.get(
                            "index"
                        )
                    )

                if (
                        seriesId
                        in (
                        None,
                        "",
                )
                        or frameIndex
                        is None
                ):
                    continue

                seriesKey = str(
                    seriesId
                )

                if (
                        seriesKey
                        not in exclusions
                ):
                    continue

                frameIndex = (
                    self._safeInt(
                        frameIndex,
                        -1,
                    )
                )

                if frameIndex < 0:
                    continue

                childEdits.setdefault(
                    seriesKey,
                    {},
                )[
                    frameIndex
                ] = value

                continue

            seriesId = rowData.get(
                "ctfSeriesId"
            )

            if seriesId is None:
                seriesId = (
                    rowData.get(
                        "tiltSeriesId"
                    )
                )

            if seriesId is None:
                seriesId = edit.get(
                    "rowId"
                )

            if seriesId in (
                    None,
                    "",
            ):
                continue

            seriesKey = str(
                seriesId
            )

            if (
                    seriesKey
                    not in exclusions
            ):
                continue

            rootEdits[
                seriesKey
            ] = value

        for seriesKey, entry in (
                exclusions.items()
        ):
            parentExcluded = (
                rootEdits.get(
                    seriesKey,
                    bool(
                        entry.get(
                            "excluded",
                            False,
                        )
                    ),
                )
            )

            indexes = list(
                allFrameIndexes.get(
                    seriesKey,
                    [],
                )
            )

            if parentExcluded:
                entry[
                    "excluded"
                ] = True

                entry[
                    "tiltimages"
                ] = indexes

                continue

            selectedIndexes = set(
                baselineFrameExclusions.get(
                    seriesKey,
                    [],
                )
            )

            for (
                    frameIndex,
                    excluded,
            ) in childEdits.get(
                seriesKey,
                {},
            ).items():

                if excluded:
                    selectedIndexes.add(
                        frameIndex
                    )
                else:
                    selectedIndexes.discard(
                        frameIndex
                    )

            if (
                    indexes
                    and set(
                indexes
            ).issubset(
                selectedIndexes
            )
            ):
                entry[
                    "excluded"
                ] = True

                entry[
                    "tiltimages"
                ] = indexes

            else:
                entry[
                    "excluded"
                ] = False

                entry[
                    "tiltimages"
                ] = sorted(
                    selectedIndexes
                )

        return exclusions

    def executeEditAction(
            self,
            *,
            projectId: int,
            protocolId: int,
            payload: Dict[str, Any],
            descriptor: OutputViewerDescriptor,
            mapper,
            listTiltSeriesCallback: Callable,
            getTiltSeriesFramesCallback: Callable,
            createTiltSeriesSetCallback: Callable,
            listCtftomoSeriesCallback: Callable,
            getCtftomoSeriesViewsCallback: Callable,
            createCtftomoSetCallback: Callable,
    ) -> Dict[str, Any]:
        outputName = str(
            payload.get(
                "outputName"
            )
            or ""
        ).strip()

        actionId = str(
            payload.get(
                "actionId"
            )
            or ""
        ).strip()

        edits = payload.get(
            "edits"
        )

        if not isinstance(
                edits,
                list,
        ):
            edits = []

        if (
                not outputName
                or not actionId
        ):
            return {
                "success": False,
                "message": (
                    "Missing output "
                    "or edit action."
                ),
            }

        if (
                descriptor.hasCapability(
                    VIEWER_CAPABILITY_TILT_SERIES
                )
                and actionId
                in (
                    "create-filtered-output",
                    "create-restacked-output",
                )
        ):
            if not edits:
                return {
                    "success": False,
                    "message": (
                        "There are no "
                        "pending changes."
                    ),
                }

            exclusions = (
                self
                ._buildTiltSeriesExclusionsFromEdits(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    edits=edits,
                    mapper=mapper,
                    listTiltSeriesCallback=(
                        listTiltSeriesCallback
                    ),
                    getTiltSeriesFramesCallback=(
                        getTiltSeriesFramesCallback
                    ),
                )
            )

            restack = (
                    actionId
                    == "create-restacked-output"
            )

            result = (
                createTiltSeriesSetCallback(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    exclusions=exclusions,
                    restack=restack,
                    mapper=mapper,
                )
            )

            message = None

            if isinstance(
                    result,
                    dict,
            ):
                rawMessage = (
                    result.get(
                        "message"
                    )
                )

                if rawMessage:
                    message = str(
                        rawMessage
                    )

            if not message:
                message = (
                    "New restacked "
                    "TiltSeries output created."
                    if restack
                    else
                    "New TiltSeries "
                    "output created."
                )

            return {
                "success": True,
                "message": message,
                "clearEdits": True,
                "data": result,
            }

        if (
                descriptor.hasCapability(
                    VIEWER_CAPABILITY_CTF_TOMO
                )
                and actionId
                == "create-filtered-output"
        ):
            if not edits:
                return {
                    "success": False,
                    "message": (
                        "There are no "
                        "pending changes."
                    ),
                }

            exclusions = (
                self
                ._buildCtftomoExclusionsFromEdits(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    edits=edits,
                    mapper=mapper,
                    listCtftomoSeriesCallback=(
                        listCtftomoSeriesCallback
                    ),
                    getCtftomoSeriesViewsCallback=(
                        getCtftomoSeriesViewsCallback
                    ),
                )
            )

            result = (
                createCtftomoSetCallback(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    exclusions=exclusions,
                    restack=False,
                    mapper=mapper,
                )
            )

            message = None

            if isinstance(
                    result,
                    dict,
            ):
                rawMessage = result.get(
                    "message"
                )

                if rawMessage:
                    message = str(
                        rawMessage
                    )

            if not message:
                message = (
                    "New CTF tomography "
                    "output created."
                )

            return {
                "success": True,
                "message": message,
                "clearEdits": True,
                "data": result,
            }

        return {
            "success": False,
            "message": (
                "No handler is registered "
                f"for edit action '{actionId}'."
            ),
        }

    def resolveAction(
            self,
            *,
            projectId: int,
            protocolId: int,
            payload: Dict[str, Any],
            descriptor: OutputViewerDescriptor,
            mapper=None,
    ) -> Dict[str, Any]:
        outputName = str(
            payload.get("outputName")
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

        cellContext = payload.get(
            "cellContext"
        )

        if not isinstance(
                cellContext,
                dict,
        ):
            cellContext = {}

        cellData = cellContext.get(
            "data"
        )

        if not isinstance(
                cellData,
                dict,
        ):
            cellData = {}

        actionData = dict(
            rowData
        )

        actionData.update(
            cellData
        )

        if not outputName or not actionId:
            return {
                "kind": "empty",
                "message": (
                    "Missing output or action."
                ),
            }

        if (
                descriptor.hasCapability(
                    VIEWER_CAPABILITY_COORDINATES3D
                )
                and actionId
                == "view-coordinates3d"
        ):
            tomogramId = actionData.get(
                "tomoId"
            )

            if tomogramId in (
                    None,
                    "",
            ):
                tomogramId = actionData.get(
                    "tomogramId"
                )

            if tomogramId in (
                    None,
                    "",
            ):
                tomogramId = actionData.get(
                    "tsId"
                )

            if tomogramId in (
                    None,
                    "",
            ):
                tomogramId = rowId

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
                descriptor.hasCapability(
                    VIEWER_CAPABILITY_TILT_SERIES
                )
                and actionId
                == "view-tiltseries"
        ):
            tiltSeriesId = actionData.get(
                "tiltSeriesId"
            )

            if tiltSeriesId in (
                    None,
                    "",
            ):
                tiltSeriesId = rowId

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

            frameIndex = actionData.get(
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

        if (
                descriptor.hasCapability(
                    VIEWER_CAPABILITY_CTF_TOMO
                )
                and actionId
                == "view-ctftomo"
        ):
            ctfSeriesId = actionData.get(
                "ctfSeriesId"
            )

            if ctfSeriesId in (
                    None,
                    "",
            ):
                ctfSeriesId = (
                    actionData.get(
                        "tiltSeriesId"
                    )
                )

            if ctfSeriesId in (
                    None,
                    "",
            ):
                ctfSeriesId = rowId

            if ctfSeriesId in (
                    None,
                    "",
            ):
                return {
                    "kind": "empty",
                    "message": (
                        "CTF series id "
                        "is missing."
                    ),
                }

            viewId = actionData.get(
                "viewId"
            )

            ctfIndex = actionData.get(
                "ctfIndex"
            )

            content = {
                "kind":
                    "ctfTomo",

                "title": (
                    f"CTF series · "
                    f"{ctfSeriesId}"
                ),

                "projectId":
                    projectId,

                "protocolId":
                    protocolId,

                "outputName":
                    outputName,

                "ctfSeriesId":
                    ctfSeriesId,
            }

            if viewId not in (
                    None,
                    "",
            ):
                content[
                    "viewId"
                ] = viewId

                displayIndex = (
                    ctfIndex
                    if ctfIndex is not None
                    else viewId
                )

                content[
                    "title"
                ] = (
                    f"CTF view · "
                    f"{ctfSeriesId} · "
                    f"{displayIndex}"
                )

            return content

        if (
                descriptor.hasCapability(
                    VIEWER_CAPABILITY_TOMOGRAMS
                )
                and actionId == "view-volume"
        ):
            volumeId = actionData.get(
                "volumeId"
            )

            if volumeId in (
                    None,
                    "",
            ):
                volumeId = actionData.get(
                    "objectId"
                )

            if volumeId in (
                    None,
                    "",
            ):
                volumeId = rowId

            if volumeId in (
                    None,
                    "",
            ):
                return {
                    "kind": "empty",
                    "message": (
                        "Tomogram volume id "
                        "is missing."
                    ),
                }

            label = (
                    actionData.get("label")
                    or actionData.get(
                "tomogramId"
            )
                    or rowId
                    or volumeId
            )

            return {
                "kind": "volume",
                "title": (
                    f"Tomogram · {label}"
                ),
                "projectId": projectId,
                "protocolId": protocolId,
                "outputName": outputName,
                "volumeId": volumeId,
            }

        return {
            "kind": "empty",
            "message": (
                "No viewer is registered "
                f"for action '{actionId}'."
            ),
        }