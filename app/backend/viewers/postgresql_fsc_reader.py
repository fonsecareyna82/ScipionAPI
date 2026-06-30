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
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class PostgresqlFscReader:
    """Read SetOfFSCs-like outputs from PostgreSQL flat_set metadata."""

    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = int(projectId)
        self.protocolId = int(protocolId)
        self.outputName = str(outputName)
        self.setMapper = ScipionSetPostgresqlMapper(db)
        self._storedSet = None
        self.lastSkipReason = None

    def hasOutput(self) -> bool:
        return self._getStoredSet() is not None

    def getFscRows(self, threshold: float = 0.143) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        storedSet = self._getStoredSet()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        rows: List[Dict[str, Any]] = []

        for index, item in enumerate(storedSet.get("items") or []):
            values = self._normalizeJsonObject(item.get("values"))

            label = (
                item.get("label")
                or self._firstValueByNormalizedName(
                    values,
                    [
                        "_objLabel",
                        "objLabel",
                        "label",
                        "name",
                        "_label",
                    ],
                )
                or f"FSC {index + 1}"
            )

            xy = self._extractXY(values)
            if xy is None:
                continue

            x, y = xy
            if x.size == 0 or y.size == 0:
                continue

            resolution = self._extractResolution(values)
            if resolution is None:
                resolution = self._estimateResolutionFromThreshold(x, y, threshold)

            rows.append(
                {
                    "label": str(label),
                    "resolution": resolution,
                    "x": x.astype(float).tolist(),
                    "y": y.astype(float).tolist(),
                }
            )

        if not rows:
            self.lastSkipReason = "fsc_rows_not_found"
            return None

        return {
            "threshold": float(threshold),
            "rows": rows,
        }

    def _getStoredSet(self) -> Optional[Dict[str, Any]]:
        if self._storedSet is None:
            self._storedSet = self.setMapper.getStoredSet(
                projectId=self.projectId,
                protocolDbId=self.protocolId,
                outputName=self.outputName,
            )
        return self._storedSet

    def _extractXY(self, values: Dict[str, Any]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        xRaw = self._firstValueByNormalizedName(
            values,
            [
                "x",
                "_x",
                "freq",
                "frequency",
                "frequencies",
                "spatialFrequency",
                "resolutionInv",
            ],
        )
        yRaw = self._firstValueByNormalizedName(
            values,
            [
                "y",
                "_y",
                "fsc",
                "_fsc",
                "correlation",
                "corr",
                "value",
                "values",
            ],
        )

        if xRaw is not None and yRaw is not None:
            parsed = self._buildXYFromArrays(xRaw, yRaw)
            if parsed is not None:
                return parsed

        dataRaw = self._firstValueByNormalizedName(
            values,
            [
                "data",
                "_data",
                "fscData",
                "curve",
                "points",
                "plot",
            ],
        )

        parsed = self._parseDataPayload(dataRaw)
        if parsed is not None:
            return parsed

        # Last-resort recursive search: sometimes values may wrap data under
        # nested dictionaries.
        for value in values.values():
            parsed = self._parseDataPayload(value)
            if parsed is not None:
                return parsed

        return None

    def _parseDataPayload(self, raw: Any) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        parsed = self._parseJsonValue(raw)

        if parsed is None:
            return None

        if isinstance(parsed, dict):
            xRaw = self._firstValueByNormalizedName(
                parsed,
                [
                    "x",
                    "_x",
                    "freq",
                    "frequency",
                    "frequencies",
                    "spatialFrequency",
                    "resolutionInv",
                ],
            )
            yRaw = self._firstValueByNormalizedName(
                parsed,
                [
                    "y",
                    "_y",
                    "fsc",
                    "_fsc",
                    "correlation",
                    "corr",
                    "value",
                    "values",
                ],
            )

            if xRaw is not None and yRaw is not None:
                return self._buildXYFromArrays(xRaw, yRaw)

            for value in parsed.values():
                nested = self._parseDataPayload(value)
                if nested is not None:
                    return nested

            return None

        if isinstance(parsed, (list, tuple)):
            if len(parsed) == 2:
                maybeXY = self._buildXYFromArrays(parsed[0], parsed[1])
                if maybeXY is not None:
                    return maybeXY

            # Nx2 shape: [[x, y], [x, y], ...]
            try:
                arr = np.asarray(parsed, dtype=float)
                if arr.ndim == 2:
                    if arr.shape[1] >= 2:
                        return self._cleanXY(arr[:, 0], arr[:, 1])
                    if arr.shape[0] >= 2:
                        return self._cleanXY(arr[0, :], arr[1, :])
            except Exception:
                pass

            # List of dicts: [{"x": ..., "y": ...}, ...]
            xs: List[float] = []
            ys: List[float] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue

                xRaw = self._firstValueByNormalizedName(
                    item,
                    ["x", "_x", "freq", "frequency", "spatialFrequency"],
                )
                yRaw = self._firstValueByNormalizedName(
                    item,
                    ["y", "_y", "fsc", "_fsc", "correlation", "corr", "value"],
                )

                try:
                    xValue = float(xRaw)
                    yValue = float(yRaw)
                except Exception:
                    continue

                if np.isfinite(xValue) and np.isfinite(yValue):
                    xs.append(xValue)
                    ys.append(yValue)

            if xs:
                return self._cleanXY(xs, ys)

        return None

    def _buildXYFromArrays(self, xRaw: Any, yRaw: Any) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        try:
            x = np.asarray(self._parseJsonValue(xRaw), dtype=float)
            y = np.asarray(self._parseJsonValue(yRaw), dtype=float)
        except Exception:
            return None

        if x.ndim != 1:
            x = x.ravel()
        if y.ndim != 1:
            y = y.ravel()

        return self._cleanXY(x, y)

    def _cleanXY(self, xRaw: Any, yRaw: Any) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        try:
            x = np.asarray(xRaw, dtype=float).ravel()
            y = np.asarray(yRaw, dtype=float).ravel()
        except Exception:
            return None

        n = min(x.size, y.size)
        if n <= 0:
            return None

        x = x[:n]
        y = y[:n]

        mask = np.isfinite(x) & np.isfinite(y)
        x = x[mask]
        y = y[mask]

        if x.size == 0:
            return None

        return x, y

    def _extractResolution(self, values: Dict[str, Any]) -> Optional[float]:
        raw = self._firstValueByNormalizedName(
            values,
            [
                "resolution",
                "_resolution",
                "resolution0143",
                "resolutionAt0143",
                "fscResolution",
            ],
        )

        value = self._toOptionalFloat(raw)
        if value is not None and np.isfinite(value) and value > 0:
            return float(value)

        return None

    def _estimateResolutionFromThreshold(
            self,
            x: np.ndarray,
            y: np.ndarray,
            threshold: float,
    ) -> Optional[float]:
        try:
            order = np.argsort(x)
            xSorted = x[order]
            ySorted = y[order]

            for index in range(1, len(xSorted)):
                prevX = float(xSorted[index - 1])
                currX = float(xSorted[index])
                prevY = float(ySorted[index - 1])
                currY = float(ySorted[index])

                prevDelta = prevY - threshold
                currDelta = currY - threshold

                if prevDelta == 0.0:
                    freq = prevX
                elif currDelta == 0.0:
                    freq = currX
                elif (prevDelta > 0 > currDelta) or (prevDelta < 0 < currDelta):
                    denom = currY - prevY
                    if denom == 0.0:
                        freq = currX
                    else:
                        t = (threshold - prevY) / denom
                        freq = prevX + t * (currX - prevX)
                else:
                    continue

                if np.isfinite(freq) and freq > 0:
                    return float(1.0 / freq)

        except Exception:
            return None

        return None

    @staticmethod
    def _normalizeJsonObject(raw: Any) -> Dict[str, Any]:
        parsed = PostgresqlFscReader._parseJsonValue(raw)
        if isinstance(parsed, dict):
            return parsed
        return {}

    @staticmethod
    def _parseJsonValue(raw: Any) -> Any:
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return raw

            if text.startswith("{") or text.startswith("["):
                try:
                    return json.loads(text)
                except Exception:
                    return raw

        return raw

    @staticmethod
    def _normalizeKey(value: Any) -> str:
        return (
            str(value or "")
            .replace("_", "")
            .replace("-", "")
            .replace(".", "")
            .lower()
        )

    def _firstValueByNormalizedName(
            self,
            values: Dict[str, Any],
            names: List[str],
    ) -> Any:
        if not isinstance(values, dict):
            return None

        targets = {self._normalizeKey(name) for name in names}

        for key, value in values.items():
            if self._normalizeKey(key) in targets:
                return value

        for key, value in values.items():
            normalizedKey = self._normalizeKey(key)
            if any(normalizedKey.endswith(target) for target in targets):
                return value

        return None

    @staticmethod
    def _toOptionalFloat(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None

        parsed = PostgresqlFscReader._parseJsonValue(value)

        if isinstance(parsed, dict):
            for key in ("value", "_value", "resolution"):
                if key in parsed:
                    return PostgresqlFscReader._toOptionalFloat(parsed.get(key))
            return None

        try:
            return float(parsed)
        except Exception:
            return None