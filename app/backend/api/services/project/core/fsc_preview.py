"""Building FSC curve rows (used by the FSC preview endpoint) from either a
PostgreSQL-backed reader or a live Scipion runtime SetOfFSCs-like output.
"""
import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_FSC_THRESHOLD = 0.143


def buildPostgresqlFscReader(mapper, projectId: int, protocolId, outputName: str):
    """protocolId here is expected to already be resolved for reader use
    (see ProjectService._resolvePostgresqlReaderProtocolId)."""
    from app.backend.viewers.postgresql_fsc_reader import PostgresqlFscReader

    reader = PostgresqlFscReader(
        db=mapper.db,
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    if reader.hasOutput():
        return reader

    return None


def iterFscObjects(output):
    # iterateWithoutReusingSameMutableObject
    iterItemsFn = getattr(output, "iterItems", None)
    if callable(iterItemsFn):
        try:
            for item in iterItemsFn(iterate=False):
                yield item
            return
        except TypeError:
            pass
        except Exception:
            pass

        try:
            for item in iterItemsFn():
                clone = getattr(item, "clone", lambda: item)()
                yield clone
            return
        except Exception:
            pass

    # singleFscObjectFallback
    if hasattr(output, "getData") and callable(getattr(output, "getData", None)):
        yield output
        return

    # genericIterableFallback
    try:
        for item in output:
            clone = getattr(item, "clone", lambda: item)()
            yield clone
        return
    except Exception:
        pass

    from fastapi import HTTPException

    raise HTTPException(
        status_code=500,
        detail="Output does not expose iterable FSC objects",
    )


def getFscXY(fsc):
    # getXYExactlyLikeThumbnailPreview
    data = fsc.getData()

    if isinstance(data, (list, tuple)) and len(data) == 2:
        x, y = data
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
    else:
        arr = np.asarray(data, dtype=float)

        if arr.ndim != 2:
            raise ValueError("Invalid FSC data shape")

        if arr.shape[1] >= 2:
            x, y = arr[:, 0], arr[:, 1]
        elif arr.shape[0] >= 2:
            x, y = arr[0, :], arr[1, :]
        else:
            raise ValueError("Invalid FSC data shape")

    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]

    return x, y


def buildFscRows(output, threshold: float = DEFAULT_FSC_THRESHOLD) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []

    for i, fsc in enumerate(iterFscObjects(output)):
        if fsc is None:
            continue

        clone = getattr(fsc, "clone", lambda: fsc)()

        label = getattr(clone, "getObjLabel", lambda: None)() or f"FSC {i + 1}"

        try:
            x, y = getFscXY(clone)
        except Exception as e:
            logger.warning("Skipping FSC '%s' because data could not be parsed: %s", label, e)
            continue

        if x.size == 0:
            continue

        resolution = None
        if hasattr(clone, "calculateResolution"):
            try:
                res = clone.calculateResolution(threshold)
                if res is not None:
                    res = float(res)
                    if np.isfinite(res) and res > 0:
                        resolution = res
            except Exception:
                resolution = None

        rows.append(
            {
                "label": str(label),
                "resolution": resolution,
                "x": x.astype(float).tolist(),
                "y": y.astype(float).tolist(),
            }
        )

    return {
        "threshold": threshold,
        "rows": rows,
    }
