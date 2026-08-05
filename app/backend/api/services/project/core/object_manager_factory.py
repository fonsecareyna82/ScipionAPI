"""Building ObjectManager instances for preview operations, and reading
Scipion sqlite object databases through them. Always returns a fresh
ObjectManager per call to avoid sharing SQLite connections across
concurrent HTTP requests/threads.
"""
import logging
from typing import Any, Dict, Optional

from metadataviewer.dao.numpy_dao import NumpyDao
from metadataviewer.model import ObjectManager
from pwem.viewers.mdviewer.readers import ScipionImageReader
from pwem.viewers.mdviewer.sqlite_dao import ScipionSetsDAO
from pwem.viewers.mdviewer.star_dao import StarFile

from app.backend.api.services.project.core.scipion_object_helpers import safeScipionValue

logger = logging.getLogger(__name__)


def createObjectManager() -> ObjectManager:
    """Create and configure a fresh ObjectManager instance."""
    objMgr = ObjectManager()
    objMgr.registerDAO(ScipionSetsDAO)
    objMgr.registerDAO(StarFile)
    objMgr.registerReader(ScipionImageReader)
    NumpyDao.addCompatibleFileType('cs')
    return objMgr


def tryReadScipionSetWithObjectManager(filePath) -> Optional[Any]:
    """
    Try several ObjectManager entry points because different metadata
    viewer versions expose slightly different method names.
    """
    objMgr = createObjectManager()
    fileName = str(filePath)

    candidateCalls = [
        ("read", (fileName,)),
        ("load", (fileName,)),
        ("open", (fileName,)),
        ("getObject", (fileName,)),
        ("getDataObject", (fileName,)),
        ("getDataObjects", (fileName,)),
    ]

    lastError = None

    for methodName, args in candidateCalls:
        method = getattr(objMgr, methodName, None)
        if method is None:
            continue

        try:
            result = method(*args)
            if result is not None:
                if isinstance(result, (list, tuple)) and result:
                    return result[0]
                return result
        except Exception as exc:
            lastError = exc

    if lastError is not None:
        logger.debug(
            "Could not read Scipion sqlite with ObjectManager. file=%s error=%s",
            fileName,
            lastError,
        )

    return None


def buildScipionItemPreviewRow(item: Any) -> Dict[str, Any]:
    """Build a compact preview row for one Scipion object item."""
    row: Dict[str, Any] = {}

    candidates = [
        ("id", "getObjId"),
        ("class", "getClassName"),
        ("fileName", "getFileName"),
        ("index", "getIndex"),
        ("enabled", "isEnabled"),
        ("samplingRate", "getSamplingRate"),
        ("dimensions", "getDimensions"),
    ]

    for key, methodName in candidates:
        try:
            method = getattr(item, methodName, None)
            if method is None:
                continue
            value = method()
            row[key] = safeScipionValue(value)
        except Exception:
            pass

    if not row:
        try:
            row["value"] = safeScipionValue(item)
        except Exception:
            pass

    return row


def extractScipionSetPreviewInfo(obj: Any) -> Dict[str, Any]:
    """Build a compact preview payload from a Scipion set-like object."""
    objectClass = obj.__class__.__name__ if obj is not None else None

    objectCount = None
    for methodName in ("getSize", "__len__"):
        try:
            if methodName == "__len__":
                objectCount = len(obj)
            else:
                method = getattr(obj, methodName, None)
                if method is not None:
                    objectCount = int(method())
            if objectCount is not None:
                break
        except Exception:
            pass

    summary: list = []

    if objectClass:
        summary.append({"key": "Object class", "value": objectClass})
    if objectCount is not None:
        summary.append({"key": "Items", "value": objectCount})

    scalarMethods = [
        ("Sampling rate", "getSamplingRate"),
        ("Dimensions", "getDimensions"),
        ("First item", "getFirstItem"),
        ("File name", "getFileName"),
    ]

    for label, methodName in scalarMethods:
        try:
            method = getattr(obj, methodName, None)
            if method is None:
                continue
            value = method()
            safeValue = safeScipionValue(value)
            if safeValue not in (None, ""):
                summary.append({"key": label, "value": safeValue})
        except Exception:
            pass

    sampleRows = []
    sampleColumns: list = []

    try:
        iterator = iter(obj)
        for index, item in enumerate(iterator):
            if index >= 10:
                break

            row = buildScipionItemPreviewRow(item)
            if row:
                for key in row.keys():
                    if key not in sampleColumns:
                        sampleColumns.append(key)
                sampleRows.append(row)
    except Exception:
        pass

    return {
        "objectClass": objectClass,
        "objectCount": objectCount,
        "summary": summary,
        "sample": {
            "columns": sampleColumns,
            "rows": sampleRows,
        },
    }


def inspectScipionSqliteDatabase(filePath) -> Optional[Dict[str, Any]]:
    """
    Inspect a Scipion SQLite object database using the metadata viewer
    ObjectManager when possible.
    """
    obj = tryReadScipionSetWithObjectManager(filePath)
    if obj is None:
        return None

    info = extractScipionSetPreviewInfo(obj)
    info["reader"] = "ObjectManager"
    return info
