"""Pure helpers for generic metadata-table preview (.sqlite / .star / etc.):
table introspection, cell rendering, selection-id handling, and constructing
the PostgreSQL generic DAO when available.
"""
import io
from typing import Any, List, Optional, Union

import numpy as np
from fastapi import HTTPException, Response, status


def isPropertiesMetadataTable(table) -> bool:
    try:
        tableName = str(table.getName() or "").strip()
    except Exception:
        tableName = ""

    try:
        tableAlias = str(table.getAlias() or "").strip()
    except Exception:
        tableAlias = ""

    return tableName == "Properties" or tableAlias == "Properties"


def getMetadataTableActionNames(table) -> List[str]:
    if isPropertiesMetadataTable(table):
        return []

    try:
        tableActions = table.getActions() or []
    except Exception:
        return []

    actionNames: List[str] = []
    seen = set()

    for action in tableActions:
        try:
            actionName = str(action.getName() or "").strip()
        except Exception:
            actionName = ""

        if not actionName or actionName in seen:
            continue

        seen.add(actionName)
        actionNames.append(actionName)

    return actionNames


def rendererTypeFromInstance(renderer) -> str:
    """Map renderer class name to a simple type label for the API."""
    name = renderer.__class__.__name__
    mapping = {
        "IntRenderer": "int",
        "FloatRenderer": "float",
        "BoolRenderer": "bool",
        "MatrixRender": "matrix",
        "ImageRenderer": "image",
        "StrRenderer": "str",
    }
    return mapping.get(name, "str")


def convertCellForPage(renderer, rawValue, rowValues):
    """
    Convert a raw cell value + renderer into something JSON friendly for page API.
    - image  -> { kind: "image", path: "..." }
    - matrix -> { kind: "matrix", value: [[...], ...] }
    - others -> primitive (int/float/bool/str) when possible
    """
    clsName = renderer.__class__.__name__

    if clsName == "ImageRenderer":
        return {
            "kind": "image",
            "path": "" if rawValue is None else str(rawValue),
        }

    if clsName == "MatrixRender":
        try:
            rendered = renderer.render(rawValue, rowValues)
        except Exception:
            rendered = rawValue
        if isinstance(rendered, np.ndarray):
            renderedVal = rendered.tolist()
        else:
            renderedVal = rendered
        return {
            "kind": "matrix",
            "value": renderedVal,
        }

    try:
        rendered = renderer.render(rawValue, rowValues)
    except Exception:
        rendered = rawValue

    if isinstance(rendered, np.ndarray):
        rendered = rendered.tolist()
    if isinstance(rendered, np.generic):
        rendered = rendered.item()

    return rendered


def normalizeMetadataSelectionIds(ids: List[int]) -> List[int]:
    normalizedIds: List[int] = []

    for rowId in ids or []:
        try:
            normalizedIds.append(int(rowId))
        except Exception:
            continue

    if not normalizedIds:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing ids",
        )

    return normalizedIds


def buildMetadataSelectionArgument(selectionPath: str, tableName: str, objectTable: str) -> str:
    selectionArg = selectionPath + ","

    if tableName != objectTable:
        selectionArg += tableName.split("_Objects")[0]

    return selectionArg


def getMetadataActionAliasForTable(dao, table) -> str:
    getActionAliasFn = getattr(dao, "_getActionAliasForTableName", None)
    if callable(getActionAliasFn):
        try:
            actionAlias = str(getActionAliasFn(table.getName()) or "").strip()
            if actionAlias:
                return actionAlias
        except Exception:
            pass

    try:
        return str(table.getAlias() or "").strip()
    except Exception:
        return ""


def resolveMetadataActionOutputClassName(dao, table, action: str) -> str:
    actionName = str(action or "").strip()
    if not actionName:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing action",
        )

    validActions = getMetadataTableActionNames(table)
    if actionName not in validActions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported action '{actionName}' for table '{table.getName()}'",
        )

    actionAlias = getMetadataActionAliasForTable(dao, table)

    if actionAlias == "Class2D" and actionName == "Averages":
        return "SetOfAverages"

    if actionAlias == "Class3D" and actionName == "Volumes":
        return "SetOfVolumes"

    objectsType = getattr(dao, "_objectsType", {}) or {}

    if actionAlias == "Class2D":
        objectsType.setdefault("Averages", "SetOfAverages")

    if actionAlias == "Class3D":
        objectsType.setdefault("Volumes", "SetOfVolumes")

    outputClassName = objectsType.get(actionName)

    if outputClassName:
        return str(outputClassName)

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Could not resolve output class for action '{actionName}'",
    )


def renderMetadataPlaceholderImage(
        size: int,
        inline: bool,
        fmt: str,
        tableName: str,
        columnName: str,
        rowId: Optional[Union[int, str]],
        rowIndex: Optional[int],
) -> Response:
    """Return a small neutral placeholder image for broken metadata cells."""
    from PIL import Image as PILImage

    try:
        sizeInt = int(size)
    except Exception:
        sizeInt = 64
    sizeInt = max(8, sizeInt)

    img = PILImage.new("L", (sizeInt, sizeInt), 0)
    buf = io.BytesIO()

    fmtLower = (fmt or "png").lower()
    if fmtLower in ("jpg", "jpeg"):
        pilFormat = "JPEG"
        mediaType = "image/jpeg"
    elif fmtLower == "webp":
        pilFormat = "WEBP"
        mediaType = "image/webp"
    else:
        pilFormat = "PNG"
        mediaType = "image/png"

    img.save(buf, format=pilFormat)

    disp = "inline" if inline else "attachment"
    ident = rowId if rowId is not None else (rowIndex if rowIndex is not None else "placeholder")

    headers = {
        "Content-Disposition": f'{disp}; filename="{tableName}_{columnName}_{ident}.{fmtLower}"',
        "Access-Control-Expose-Headers": "Content-Disposition",
        "X-Image-Placeholder": "1",
    }
    return Response(content=buf.getvalue(), media_type=mediaType, headers=headers)


def buildPostgresqlDAO(mapper, projectId: int, protocolId, outputName: str):
    """protocolId here is expected to already be resolved for reader use
    (see ProjectService._resolvePostgresqlReaderProtocolId)."""
    from app.backend.viewers.postgresql_dao import PostgresqlDAO

    dao = PostgresqlDAO(
        db=mapper.db,
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    if dao.hasOutput():
        return dao

    return None
