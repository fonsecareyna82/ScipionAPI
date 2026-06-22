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
from typing import Any, Dict, List, Optional, Union

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class PostgresqlTomogramTiltSeriesReader:
    """Expose tilt series linked from a SetOfTomograms as tilt-series-like items."""

    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = projectId
        self.protocolId = protocolId
        self.outputName = outputName
        self.setMapper = ScipionSetPostgresqlMapper(db)
        self._storedSet = None
        self._linkedTiltSeries = None
        self.lastSkipReason = None

    def hasOutput(self) -> bool:
        return bool(self._getLinkedTiltSeriesItems())

    def listTiltSeries(self) -> List[Dict[str, Any]]:
        items = self._getLinkedTiltSeriesItems()
        return [
            self._buildTiltSeriesSummary(item, index)
            for index, item in enumerate(items)
        ]

    def getTiltSeriesFrames(self, tiltSeriesId: Any) -> Optional[Dict[str, Any]]:
        item = self._findTiltSeriesItem(tiltSeriesId)
        if item is None:
            self.lastSkipReason = "tilt_series_not_found tiltSeriesId=%s" % str(tiltSeriesId)
            return None

        summary = self._buildTiltSeriesSummary(item, 0)
        frames = item.get("frames") or []

        payload = dict(summary)
        payload["frames"] = frames
        payload["nViews"] = len(frames)

        return payload

    def getTiltImageFrame(self, tiltSeriesId: Any, index: Any) -> Optional[Dict[str, Any]]:
        payload = self.getTiltSeriesFrames(tiltSeriesId)
        if not payload:
            return None

        frames = payload.get("frames") or []
        targetIndex = self._toOptionalInt(index)

        if targetIndex is not None:
            for frame in frames:
                frameIndex = self._toOptionalInt(frame.get("index"))
                if frameIndex == targetIndex:
                    return frame

            if 0 <= targetIndex < len(frames):
                return frames[targetIndex]

        return None

    def _getStoredSet(self) -> Optional[Dict[str, Any]]:
        if self._storedSet is None:
            try:
                self._storedSet = self.setMapper.getStoredSet(
                    projectId=self.projectId,
                    protocolDbId=self.protocolId,
                    outputName=self.outputName,
                    limit=None,
                    offset=0,
                )
            except Exception:
                self._storedSet = None

        return self._storedSet

    def _getLinkedTiltSeries(self) -> Optional[Dict[str, Any]]:
        if self._linkedTiltSeries is not None:
            return self._linkedTiltSeries

        storedSet = self._getStoredSet()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        properties = storedSet.get("properties") or {}
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except Exception:
                properties = {}

        linkedTiltSeries = properties.get("linkedTiltSeries") if isinstance(properties, dict) else None
        if isinstance(linkedTiltSeries, dict):
            self._linkedTiltSeries = linkedTiltSeries
            return self._linkedTiltSeries

        for item in storedSet.get("setProperties") or []:
            if str(item.get("key")) != "linkedTiltSeries":
                continue

            value = item.get("value")
            if isinstance(value, dict):
                self._linkedTiltSeries = value
                return self._linkedTiltSeries

            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except Exception:
                    parsed = None

                if isinstance(parsed, dict):
                    self._linkedTiltSeries = parsed
                    return self._linkedTiltSeries

        self.lastSkipReason = "linked_tilt_series_not_found"
        return None

    def _getLinkedTiltSeriesItems(self) -> List[Dict[str, Any]]:
        linkedTiltSeries = self._getLinkedTiltSeries()
        if not linkedTiltSeries:
            return []

        items = linkedTiltSeries.get("items") or []
        return [
            item
            for item in items
            if isinstance(item, dict)
        ]

    def _buildTiltSeriesSummary(self, item: Dict[str, Any], index: int) -> Dict[str, Any]:
        tiltSeriesId = (
                item.get("tiltSeriesId")
                or item.get("tsId")
                or item.get("id")
                or index
        )

        label = item.get("label") or "TiltSeries %s" % str(tiltSeriesId)
        frames = item.get("frames") or []

        summary: Dict[str, Any] = {
            "tiltSeriesId": str(tiltSeriesId),
            "label": str(label),
            "source": "tomogram",
        }

        if item.get("dims") is not None:
            summary["dims"] = item.get("dims")

        if item.get("pixelSize") is not None:
            summary["pixelSize"] = item.get("pixelSize")

        if item.get("tiltAxisAngle") is not None:
            summary["tiltAxisAngle"] = item.get("tiltAxisAngle")

        if frames:
            summary["nViews"] = len(frames)
        elif item.get("nViews") is not None:
            summary["nViews"] = item.get("nViews")

        return summary

    def _findTiltSeriesItem(self, tiltSeriesId: Any) -> Optional[Dict[str, Any]]:
        target = str(tiltSeriesId)

        for index, item in enumerate(self._getLinkedTiltSeriesItems()):
            candidates = [
                item.get("tiltSeriesId"),
                item.get("tsId"),
                item.get("id"),
                item.get("label"),
                index,
            ]

            if any(str(value) == target for value in candidates if value is not None):
                return item

        return None

    def _toOptionalInt(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None

        try:
            return int(value)
        except Exception:
            try:
                return int(float(value))
            except Exception:
                return None