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
import os
import re
import shutil
from typing import Any, Callable, Dict, List, Optional, Set, Union

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from pyworkflow.object import (
    Object as ScipionObject,
    Pointer,
    Set as ScipionSet,
)

from app.backend.runtime.protocol_identity import ProtocolIdentityResolver

logger = logging.getLogger(__name__)


class RuntimeProtocolOutputPersistenceService:
    """Persist and cleanup PostgreSQL runtime protocol outputs."""

    @staticmethod
    def safeCall(obj: Any, methodName: str, default: Any = None) -> Any:
        try:
            method = getattr(obj, methodName, None)
            if method is None:
                return default
            return method()
        except Exception:
            return default

    def getScipionObjectId(self, obj: Any) -> Optional[Any]:
        return self.safeCall(obj, "getObjId", None)

    def getScipionClassName(self, obj: Any) -> Optional[str]:
        if obj is None:
            return None

        className = self.safeCall(obj, "getClassName", None)
        if className:
            return str(className)

        return obj.__class__.__name__

    def isPersistableNonSetOutput(self, outputObj: Any) -> bool:
        if outputObj is None:
            return False

        if self.isScipionSetLikeOutput(outputObj):
            return False

        try:
            if isinstance(outputObj, Pointer):
                return False
        except Exception:
            pass

        try:
            if isinstance(outputObj, ScipionObject):
                return True
        except Exception:
            pass

        return False

    def isScipionSetLikeOutput(self, outputObj: Any) -> bool:
        if outputObj is None:
            return False

        try:
            if isinstance(outputObj, ScipionSet):
                return True
        except Exception:
            pass

        className = self.getScipionClassName(outputObj) or outputObj.__class__.__name__
        classNameText = str(className or "")

        if classNameText.startswith("SetOf") or "SetOf" in classNameText:
            return True

        return (
                callable(getattr(outputObj, "iterItems", None))
                and callable(getattr(outputObj, "getSize", None))
                and callable(getattr(outputObj, "getFileName", None))
        )

    def shouldRegisterProtocolOutputs(self, protocol: Any) -> bool:
        """
        Return True when the protocol already exposes at least one persistable output.

        Do not depend on protocol status here:
          - streaming protocols can expose outputs while running
          - finished protocols should also register outputs
          - new/launched protocols without outputs will naturally return False
        """
        try:
            outputs = list(protocol.iterOutputAttributes())
        except Exception:
            return False

        if not outputs:
            return False

        for outputItem in outputs:
            if isinstance(outputItem, (tuple, list)) and len(outputItem) >= 2:
                outputObj = outputItem[1]
            else:
                outputObj = outputItem

            if outputObj is None:
                continue

            try:
                if self.isScipionSetLikeOutput(outputObj):
                    return True
            except Exception:
                pass

            try:
                if self.isPersistableNonSetOutput(outputObj):
                    return True
            except Exception:
                pass

        return False

    def shouldReconcileMissingProtocolOutputs(
            self,
            protocol: Any,
    ) -> bool:
        """
        Return True when the protocol output list can be treated as its final
        snapshot.

        Running and streaming protocols may expose only a partial list of
        outputs, so missing outputs must never be removed while they are active.
        """
        for methodName in (
                "isFinished",
                "isFailed",
                "isAborted",
        ):
            method = getattr(
                protocol,
                methodName,
                None,
            )

            if not callable(method):
                continue

            try:
                if bool(method()):
                    return True
            except Exception:
                pass

        statusValue = self.safeCall(
            protocol,
            "getStatus",
            None,
        )

        statusText = str(
            statusValue or ""
        ).strip().lower()

        return statusText in {
            "finished",
            "failed",
            "aborted",
            "interactive",
        }

    def shouldSyncProtocolOutputs(
            self,
            protocol: Any,
    ) -> bool:
        """
        Return True when outputs must either be persisted or reconciled.
        """
        return (
            self.shouldRegisterProtocolOutputs(
                protocol
            )
            or self.shouldReconcileMissingProtocolOutputs(
                protocol
            )
        )

    def countRuntimeOutputKinds(self, outputs: List[Dict[str, Any]]) -> Dict[str, int]:
        result: Dict[str, int] = {}

        for item in outputs or []:
            mapperKind = str(item.get("mapperKind") or "unknown")
            result[mapperKind] = result.get(mapperKind, 0) + 1

        return result

    def buildMissingOutputSyncItems(
            self,
            protocolId,
            declaredOutputs: List[Dict[str, Any]],
            persistedOutputs: List[Dict[str, Any]],
            skippedOutputs: List[Dict[str, Any]],
            outputErrors: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        persistedOutputNames = {
            item.get("outputName")
            for item in persistedOutputs or []
            if item.get("outputName")
        }

        result = []

        for skippedOutput in skippedOutputs or []:
            result.append({
                "protocolId": str(protocolId),
                "outputName": skippedOutput.get("outputName"),
                "outputClassName": skippedOutput.get("outputClassName"),
                "reason": skippedOutput.get("reason") or "skipped",
            })

        for outputError in outputErrors or []:
            item = {
                "protocolId": str(protocolId),
                "outputName": outputError.get("outputName"),
                "outputClassName": outputError.get("outputClassName"),
                "reason": "persistence_error",
            }

            if outputError.get("error") is not None:
                item["error"] = outputError.get("error")

            result.append(item)

        knownMissingNames = {
            item.get("outputName")
            for item in result
            if item.get("outputName")
        }

        for declaredOutput in declaredOutputs or []:
            outputName = declaredOutput.get("outputName")

            if not outputName:
                continue

            if outputName in persistedOutputNames:
                continue

            if outputName in knownMissingNames:
                continue

            result.append({
                "protocolId": str(protocolId),
                "outputName": outputName,
                "outputClassName": declaredOutput.get("outputClassName"),
                "reason": "not_persisted",
            })

        return result

    def _firstPersistedValue(
            self,
            sources: List[Optional[Dict[str, Any]]],
            keys: List[str],
    ) -> Any:
        for source in sources:
            if not isinstance(source, dict):
                continue

            for key in keys:
                if key in source:
                    value = source.get(key)
                    if value not in (None, "", []):
                        return value

            lowerSource = {
                str(k).lower(): v
                for k, v in source.items()
            }

            for key in keys:
                value = lowerSource.get(str(key).lower())
                if value not in (None, "", []):
                    return value

        return None

    def _toPersistedOutputInt(self, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None

        try:
            return int(value)
        except Exception:
            pass

        try:
            return int(float(str(value).strip()))
        except Exception:
            return None

    def _toPersistedOutputFloat(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None

        if isinstance(value, (list, tuple)) and value:
            value = value[0]

        try:
            return float(value)
        except Exception:
            pass

        text = str(value).strip()
        if not text:
            return None

        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None

        try:
            return float(match.group(0))
        except Exception:
            return None

    def _normalizePersistedOutputDims(self, value: Any) -> List[int]:
        if value in (None, ""):
            return []

        rawValues: List[Any] = []

        if isinstance(value, dict):
            for key in ("dims", "dim", "dimensions", "value"):
                candidate = value.get(key)
                if candidate not in (None, "", []):
                    return self._normalizePersistedOutputDims(candidate)

            for keys in (
                    ("x", "y", "z"),
                    ("width", "height", "depth"),
                    ("xDim", "yDim", "zDim"),
                    ("_xDim", "_yDim", "_zDim"),
            ):
                rawValues = [value.get(k) for k in keys if value.get(k) not in (None, "")]
                if rawValues:
                    break

        elif isinstance(value, (list, tuple)):
            rawValues = list(value)

        else:
            text = str(value).strip()
            if not text:
                return []

            # Handles "140x140", "140,140", "140 140", "[140, 140]".
            text = text.strip("[]()")
            rawValues = [
                part
                for part in re.split(r"[xX,;:\s]+", text)
                if part
            ]

        dims: List[int] = []
        for raw in rawValues[:3]:
            dim = self._toPersistedOutputInt(raw)
            if dim is not None and dim > 0:
                dims.append(dim)

        return dims

    def _normalizePersistedOutputClassText(
            self,
            *values: Any,
    ) -> str:
        return (
            " ".join(str(value or "") for value in values)
            .replace("_", "")
            .replace("-", "")
            .replace(".", "")
            .replace(" ", "")
            .lower()
        )

    def _resolvePersistedOutputDims(
            self,
            persistedOutput: Dict[str, Any],
            properties: Optional[Dict[str, Any]] = None,
    ) -> List[int]:
        properties = properties or {}
        sources = [properties, persistedOutput]

        classText = self._normalizePersistedOutputClassText(
            persistedOutput.get("className"),
            persistedOutput.get("itemClassName"),
            properties.get("className"),
            properties.get("baseClassName"),
        )

        firstDim = self._normalizePersistedOutputDims(
            self._firstPersistedValue(
                sources,
                [
                    "_firstDim",
                    "firstDim",
                    "first_dim",
                ],
            )
        )

        anglesCount = self._toPersistedOutputInt(
            self._firstPersistedValue(
                sources,
                [
                    "_anglesCount",
                    "anglesCount",
                    "angles_count",
                    "tiltAngles",
                    "tiltAnglesCount",
                    "tilt_angles_count",
                ],
            )
        )

        # Scipion displays SetOfTiltSeries as:
        #   nAngles x xDim x yDim
        # not as xDim x yDim x zDim.
        if "setoftiltseries" in classText and firstDim:
            if anglesCount is None:
                anglesCount = self._toPersistedOutputInt(
                    self._firstPersistedValue(
                        sources,
                        [
                            "itemsCount",
                            "itemsTableCount",
                            "rootTableItemsCount",
                            "size",
                            "count",
                            "_size",
                        ],
                    )
                )

            if anglesCount is not None and anglesCount > 0 and len(firstDim) >= 2:
                return [anglesCount, firstDim[0], firstDim[1]]

            return firstDim[:3]

        dimValue = self._firstPersistedValue(
            sources,
            [
                "dimensions",
                "dimension",
                "dims",
                "dim",
                "_dim",
                "_firstDim",
                "firstDim",
                "first_dim",
                "boxSize",
                "box_size",
                "_boxSize",
                "imageSize",
                "image_size",
                "xDim",
                "yDim",
                "zDim",
                "_xDim",
                "_yDim",
                "_zDim",
                "width",
                "height",
                "depth",
            ],
        )

        dims = self._normalizePersistedOutputDims(dimValue)
        if dims:
            return dims

        xDim = self._toPersistedOutputInt(
            self._firstPersistedValue(
                sources,
                ["xDim", "_xDim", "xdim", "_xdim", "width", "_width"],
            )
        )
        yDim = self._toPersistedOutputInt(
            self._firstPersistedValue(
                sources,
                ["yDim", "_yDim", "ydim", "_ydim", "height", "_height"],
            )
        )
        zDim = self._toPersistedOutputInt(
            self._firstPersistedValue(
                sources,
                ["zDim", "_zDim", "zdim", "_zdim", "depth", "_depth"],
            )
        )

        dims = [d for d in (xDim, yDim, zDim) if d is not None and d > 0]
        if dims:
            return dims

        # Useful for Coordinate3D-like outputs where tomograms are stored as linked metadata.
        linkedTomograms = self._firstPersistedValue(
            sources,
            ["linkedTomograms", "linked_tomograms", "tomograms"],
        )

        if isinstance(linkedTomograms, list):
            for item in linkedTomograms:
                if not isinstance(item, dict):
                    continue

                dims = self._normalizePersistedOutputDims(
                    self._firstPersistedValue(
                        [item],
                        [
                            "dimensions",
                            "dims",
                            "dim",
                            "_firstDim",
                            "firstDim",
                            "xDim",
                            "yDim",
                            "zDim",
                            "width",
                            "height",
                            "depth",
                        ],
                    )
                )

                if dims:
                    return dims

        return []

    def _formatPersistedOutputDims(self, dims: List[int]) -> str:
        if not dims:
            return ""

        if len(dims) == 1:
            return f"{dims[0]}x{dims[0]}"

        if len(dims) >= 3 and dims[2] > 1:
            return f"{dims[0]}x{dims[1]}x{dims[2]}"

        return f"{dims[0]}x{dims[1]}"

    def _toPersistedOutputBool(self, value: Any) -> Optional[bool]:
        if value is None or value == "":
            return None

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return bool(value)

        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "y"):
            return True
        if text in ("false", "0", "no", "n"):
            return False

        return None

    def _buildPersistedTomoDisplayFlags(
            self,
            persistedOutput: Dict[str, Any],
            properties: Dict[str, Any],
    ) -> List[str]:
        sources = [properties or {}, persistedOutput or {}]

        classText = self._normalizePersistedOutputClassText(
            persistedOutput.get("className"),
            persistedOutput.get("itemClassName"),
            properties.get("className"),
            properties.get("baseClassName"),
        )

        isTomoLike = (
                "tiltseries" in classText
                or "tomogram" in classText
                or "ctftomo" in classText
        )

        if not isTomoLike:
            return []

        def firstBool(*names):
            value = self._firstPersistedValue(sources, list(names))
            return self._toPersistedOutputBool(value)

        flags: List[str] = []

        isHeterogeneousSet = firstBool(
            "isHeterogeneousSet",
            "heterogeneous",
            "_isHeterogeneousSet",
        )
        if isHeterogeneousSet:
            flags.append("+het")

        hasAlignment = firstBool(
            "hasAlignment",
            "_hasAlignment",
            "alignment",
            "aligned",
        )
        if hasAlignment:
            flags.append("+ali")

        interpolated = firstBool(
            "interpolated",
            "_interpolated",
            "isInterpolated",
        )
        if interpolated:
            flags.append("! interp")

        ctfCorrected = firstBool(
            "ctfCorrected",
            "_ctfCorrected",
            "ctf",
            "ctfCorrectedFlag",
        )
        if ctfCorrected:
            flags.append("+ctf")

        hasOddEven = firstBool(
            "hasOddEven",
            "_hasOddEven",
            "oddEven",
            "hasOddEvenAssociated",
        )
        if hasOddEven:
            flags.append("+oe")

        return flags

    def _formatPersistedOutputClassName(
            self,
            className: Any,
            itemClassName: Any = None,
            outputName: Any = None,
    ) -> str:
        classText = str(className or "").strip()
        itemClassText = str(itemClassName or "").strip()
        outputText = str(outputName or "").strip()

        if classText:
            # Keep this one as Scipion normally shows it this way.
            if classText.startswith("SetOfClasses"):
                return classText

            # SetOfParticles -> Particles, SetOfMovies -> Movies, etc.
            if classText.startswith("SetOf") and len(classText) > len("SetOf"):
                return classText[len("SetOf"):]

            return classText

        if itemClassText:
            return itemClassText

        return outputText or "Output"

    def _buildPersistedOutputInfo(
            self,
            outputName: str,
            persistedOutput: Dict[str, Any],
            properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        properties = properties or {}

        displayClass = self._formatPersistedOutputClassName(
            persistedOutput.get("className") or properties.get("className"),
            persistedOutput.get("itemClassName"),
            outputName,
        )

        itemsCount = self._toPersistedOutputInt(
            self._firstPersistedValue(
                [persistedOutput, properties],
                [
                    "itemsCount",
                    "itemsTableCount",
                    "rootTableItemsCount",
                    "size",
                    "count",
                    "_size",
                ],
            )
        )

        dims = self._resolvePersistedOutputDims(
            persistedOutput=persistedOutput,
            properties=properties,
        )

        samplingRate = self._toPersistedOutputFloat(
            self._firstPersistedValue(
                [properties, persistedOutput],
                [
                    "samplingRate",
                    "_samplingRate",
                    "sampling_rate",
                    "sampling",
                    "_sampling",
                    "pixelSize",
                    "pixel_size",
                    "voxelSize",
                    "voxel_size",
                ],
            )
        )

        details: List[str] = []

        if itemsCount is not None:
            details.append(f"{itemsCount} {'item' if itemsCount == 1 else 'items'}")

        dimsText = self._formatPersistedOutputDims(dims)
        if dimsText:
            details.append(dimsText)

        details.extend(
            self._buildPersistedTomoDisplayFlags(
                persistedOutput=persistedOutput,
                properties=properties,
            )
        )

        if samplingRate is not None and samplingRate > 0:
            details.append(f"{samplingRate:.2f} Å/px")

        if details:
            return f"{displayClass} ({', '.join(details)})"

        return displayClass

    def loadPersistedOutputsByProtocolId(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        def toOptionalInt(value: Any) -> Optional[int]:
            if value is None or value == "":
                return None
            try:
                return int(value)
            except Exception:
                return None

        result: Dict[str, Dict[str, Dict[str, Any]]] = {}

        setRows = mapper.db.fetchAll(
            """
            SELECT
                p.id AS "protocolDbId",
                p."protocolId",
                s.id,
                s."objectId",
                s."outputName",
                s."setClassName",
                s."itemClassName",
                s.properties,
                root_object.id AS "rootObjectDbId",
                root_object."projectId" AS "rootObjectProjectId",
                root_object."protocolDbId" AS "rootObjectProtocolDbId",
                root_object."parentObjectId" AS "rootObjectParentObjectId",
                root_object.name AS "rootObjectName",
                root_object.path AS "rootObjectPath",
                root_object."className" AS "rootObjectClassName",
                COALESCE(items_stats."itemsTableCount", 0) AS "itemsTableCount",
                items_stats."maxItemIdFromItems" AS "maxItemIdFromItems",
                items_stats."itemsIdSignature" AS "itemsIdSignature",
                items_stats."itemsValueSignature" AS "itemsValueSignature",
                COALESCE(columns_stats."setColumnsCount", 0) AS "setColumnsCount",
                columns_stats."setColumnsSignature" AS "setColumnsSignature",
                COALESCE(root_table_stats."rootTablesCount", 0) AS "rootTablesCount",
                root_table_stats."rootTableId" AS "rootTableId",
                COALESCE(root_table_stats."rootTableItemsCount", 0) AS "rootTableItemsCount",
                root_table_stats."rootTableMaxItemId" AS "rootTableMaxItemId",
                root_table_stats."rootTableItemsIdSignature" AS "rootTableItemsIdSignature",
                root_table_stats."rootTableItemsValueSignature" AS "rootTableItemsValueSignature",
                COALESCE(root_table_columns_stats."rootTableColumnsCount", 0) AS "rootTableColumnsCount",
                root_table_columns_stats."rootTableColumnsSignature" AS "rootTableColumnsSignature",
                COALESCE(properties_payload_stats."propertiesPayloadCount", 0) AS "propertiesPayloadCount",
                properties_payload_stats."propertiesPayloadSignature" AS "propertiesPayloadSignature",
                COALESCE(set_properties_stats."setPropertiesCount", 0) AS "setPropertiesCount",
                set_properties_stats."setPropertiesSignature" AS "setPropertiesSignature",
                s."createdAt",
                s."updatedAt"
              FROM scipion_sets s
              JOIN protocols p
                ON p.id = s."protocolDbId"
              LEFT JOIN scipion_objects root_object
                ON root_object.id = s."objectId"
              LEFT JOIN (
                  SELECT
                      "setId",
                      COUNT(*)::int AS "itemsTableCount",
                      MAX("scipionItemId")::int AS "maxItemIdFromItems",
                      md5(
                          string_agg(
                              "scipionItemId"::text,
                              ','
                              ORDER BY "scipionItemId"
                          )
                      ) AS "itemsIdSignature",
                      md5(
                          string_agg(
                              jsonb_build_object(
                                  'scipionItemId', "scipionItemId",
                                  'enabled', enabled,
                                  'label', label,
                                  'comment', comment,
                                  'creation', creation,
                                  'values', "values"
                              )::text,
                              ','
                              ORDER BY "scipionItemId"
                          )
                      ) AS "itemsValueSignature"
                    FROM scipion_set_items
                   GROUP BY "setId"
              ) items_stats
                ON items_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      "setId",
                      COUNT(*)::int AS "setColumnsCount",
                      jsonb_agg(
                          jsonb_build_object(
                              'labelProperty', "labelProperty",
                              'columnName', "columnName",
                              'className', "className",
                              'valueType', "valueType",
                              'position', position,
                              'indexed', indexed
                          )
                          ORDER BY position ASC, "labelProperty" ASC
                      ) AS "setColumnsSignature"
                    FROM scipion_set_columns
                   GROUP BY "setId"
              ) columns_stats
                ON columns_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      t."setId",
                      COUNT(DISTINCT t.id)::int AS "rootTablesCount",
                      MIN(t.id)::int AS "rootTableId",
                      COUNT(ti.id)::int AS "rootTableItemsCount",
                      MAX(ti."scipionItemId")::int AS "rootTableMaxItemId",
                      md5(
                          string_agg(
                              ti."scipionItemId"::text,
                              ','
                              ORDER BY ti."scipionItemId"
                          ) FILTER (WHERE ti.id IS NOT NULL)
                      ) AS "rootTableItemsIdSignature",
                      md5(
                          string_agg(
                              jsonb_build_object(
                                  'scipionItemId', ti."scipionItemId",
                                  'enabled', ti.enabled,
                                  'label', ti.label,
                                  'comment', ti.comment,
                                  'creation', ti.creation,
                                  'values', ti."values"
                              )::text,
                              ','
                              ORDER BY ti."scipionItemId"
                          ) FILTER (WHERE ti.id IS NOT NULL)
                      ) AS "rootTableItemsValueSignature"
                    FROM scipion_set_tables t
                    LEFT JOIN scipion_set_table_items ti
                      ON ti."tableId" = t.id
                   WHERE t."tableKind" = 'root'
                   GROUP BY t."setId"
              ) root_table_stats
                ON root_table_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      t."setId",
                      COUNT(tc.id)::int AS "rootTableColumnsCount",
                      jsonb_agg(
                          jsonb_build_object(
                              'labelProperty', tc."labelProperty",
                              'columnName', tc."columnName",
                              'className', tc."className",
                              'valueType', tc."valueType",
                              'position', tc.position,
                              'indexed', tc.indexed
                          )
                          ORDER BY tc.position ASC, tc."labelProperty" ASC
                      ) FILTER (WHERE tc.id IS NOT NULL) AS "rootTableColumnsSignature"
                    FROM scipion_set_tables t
                    LEFT JOIN scipion_set_table_columns tc
                      ON tc."tableId" = t.id
                   WHERE t."tableKind" = 'root'
                   GROUP BY t."setId"
              ) root_table_columns_stats
                ON root_table_columns_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      s2.id AS "setId",
                      COUNT(*)::int AS "propertiesPayloadCount",
                      jsonb_agg(
                          jsonb_build_object(
                              'key', stable_keys.key,
                              'value', s2.properties ->> stable_keys.key
                          )
                          ORDER BY stable_keys.key ASC
                      ) AS "propertiesPayloadSignature"
                    FROM scipion_sets s2
                    CROSS JOIN (
                        VALUES
                            ('columnsCount'),
                            ('itemsCount'),
                            ('nestedTablesVersion')
                    ) AS stable_keys(key)
                   WHERE s2.properties ? stable_keys.key
                   GROUP BY s2.id
              ) properties_payload_stats
                ON properties_payload_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      "setId",
                      COUNT(*)::int AS "setPropertiesCount",
                      jsonb_agg(
                          jsonb_build_object(
                              'key', key,
                              'value', value
                          )
                          ORDER BY key ASC
                      ) AS "setPropertiesSignature"
                    FROM scipion_set_properties
                   WHERE key IN (
                       'columnsCount',
                       'itemsCount',
                       'nestedTablesVersion'
                   )
                   GROUP BY "setId"
              ) set_properties_stats
                ON set_properties_stats."setId" = s.id
             WHERE s."projectId" = %s
             ORDER BY p."protocolId", s."outputName"
            """,
            (projectId,),
        )

        for row in setRows:
            protocolId = str(row.get("protocolId"))
            outputName = str(row.get("outputName") or "")
            if not protocolId or not outputName:
                continue

            properties = row.get("properties") or {}

            persistedOutputInfo = self._buildPersistedOutputInfo(
                outputName=outputName,
                persistedOutput={
                    "className": row.get("setClassName"),
                    "itemClassName": row.get("itemClassName"),
                    "itemsCount": toOptionalInt(properties.get("itemsCount")) if isinstance(properties, dict) else None,
                    "itemsTableCount": toOptionalInt(row.get("itemsTableCount")),
                    "rootTableItemsCount": toOptionalInt(row.get("rootTableItemsCount")),
                },
                properties=properties if isinstance(properties, dict) else {},
            )

            result.setdefault(protocolId, {})[outputName] = {
                "mapperKind": "flat_set",
                "setId": row.get("id"),
                "protocolDbId": toOptionalInt(row.get("protocolDbId")),
                "rootObjectId": row.get("objectId"),
                "rootObjectDbId": toOptionalInt(row.get("rootObjectDbId")),
                "rootObjectProjectId": toOptionalInt(row.get("rootObjectProjectId")),
                "rootObjectProtocolDbId": toOptionalInt(row.get("rootObjectProtocolDbId")),
                "rootObjectParentObjectId": toOptionalInt(row.get("rootObjectParentObjectId")),
                "rootObjectName": row.get("rootObjectName"),
                "rootObjectPath": row.get("rootObjectPath"),
                "rootObjectClassName": row.get("rootObjectClassName"),
                "className": row.get("setClassName"),
                "itemClassName": row.get("itemClassName"),
                "info": persistedOutputInfo,
                "itemsCount": toOptionalInt(properties.get("itemsCount")) if isinstance(properties, dict) else None,
                "itemsTableCount": toOptionalInt(row.get("itemsTableCount")),
                "maxItemIdFromItems": toOptionalInt(row.get("maxItemIdFromItems")),
                "itemsIdSignature": row.get("itemsIdSignature"),
                "itemsValueSignature": row.get("itemsValueSignature"),
                "maxItemId": toOptionalInt(properties.get("maxItemId")) if isinstance(properties, dict) else None,
                "columnsCount": toOptionalInt(properties.get("columnsCount")) if isinstance(properties, dict) else None,
                "setColumnsCount": toOptionalInt(row.get("setColumnsCount")),
                "setColumnsSignature": row.get("setColumnsSignature") or [],
                "rootTablesCount": toOptionalInt(row.get("rootTablesCount")),
                "rootTableId": toOptionalInt(row.get("rootTableId")),
                "rootTableItemsCount": toOptionalInt(row.get("rootTableItemsCount")),
                "rootTableMaxItemId": toOptionalInt(row.get("rootTableMaxItemId")),
                "rootTableItemsIdSignature": row.get("rootTableItemsIdSignature"),
                "rootTableItemsValueSignature": row.get("rootTableItemsValueSignature"),
                "rootTableColumnsCount": toOptionalInt(row.get("rootTableColumnsCount")),
                "rootTableColumnsSignature": row.get("rootTableColumnsSignature") or [],
                "propertiesPayloadCount": toOptionalInt(row.get("propertiesPayloadCount")),
                "propertiesPayloadSignature": row.get("propertiesPayloadSignature") or [],
                "setPropertiesCount": toOptionalInt(row.get("setPropertiesCount")),
                "setPropertiesSignature": row.get("setPropertiesSignature") or [],
                "lastSyncAt": properties.get("lastSyncAt") if isinstance(properties, dict) else None,
                "lastCheckedAt": properties.get("lastCheckedAt") if isinstance(properties, dict) else None,
                "skippedLastSync": properties.get("skippedLastSync") if isinstance(properties, dict) else None,
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
            }

        treeRows = mapper.db.fetchAll(
            """
            SELECT
                p."protocolId",
                o.id,
                o."scipionObjId",
                o.name,
                o.path,
                o."className",
                o.value,
                o.label,
                o.comment,
                o.metadata,
                o."createdAt",
                o."updatedAt"
              FROM scipion_objects o
              JOIN protocols p
                ON p.id = o."protocolDbId"
             WHERE o."projectId" = %s
               AND o."parentObjectId" IS NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM scipion_sets s
                     WHERE s."objectId" = o.id
               )
             ORDER BY p."protocolId", o.path
            """,
            (projectId,),
        )

        for row in treeRows:
            protocolId = str(row.get("protocolId"))
            outputName = str(row.get("path") or row.get("name") or "")
            if not protocolId or not outputName:
                continue

            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}

            if not isinstance(metadata, dict):
                metadata = {}

            className = row.get("className")
            displayText = (
                    metadata.get("displayText")
                    or row.get("value")
                    or row.get("label")
                    or className
                    or outputName
            )

            result.setdefault(protocolId, {})[outputName] = {
                "mapperKind": metadata.get("mapperKind") or "tree",
                "rootObjectId": row.get("id"),
                "rootObjectDbId": toOptionalInt(row.get("id")),
                "scipionObjId": row.get("scipionObjId"),
                "rootObjectName": row.get("name"),
                "rootObjectPath": row.get("path"),
                "rootObjectClassName": className,
                "className": className,
                "info": str(displayText or ""),
                "value": row.get("value"),
                "label": row.get("label"),
                "comment": row.get("comment"),
                "metadata": metadata,
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
            }

        return result

    def loadPersistedOutputSummariesByProtocolId(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        def toOptionalInt(value: Any) -> Optional[int]:
            if value is None or value == "":
                return None
            try:
                return int(value)
            except Exception:
                return None

        result: Dict[str, Dict[str, Dict[str, Any]]] = {}

        setRows = mapper.db.fetchAll(
            """
            SELECT
                p."protocolId",
                s.id,
                s."objectId",
                s."outputName",
                s."setClassName",
                s."itemClassName",
                s.properties,
                s."createdAt",
                s."updatedAt"
              FROM scipion_sets s
              JOIN protocols p
                ON p.id = s."protocolDbId"
             WHERE s."projectId" = %s
             ORDER BY p."protocolId", s."outputName"
            """,
            (projectId,),
        )

        for row in setRows:
            protocolId = str(row.get("protocolId"))
            outputName = str(row.get("outputName") or "")
            if not protocolId or not outputName:
                continue

            properties = row.get("properties") or {}

            result.setdefault(protocolId, {})[outputName] = {
                "mapperKind": "flat_set",
                "setId": row.get("id"),
                "rootObjectId": row.get("objectId"),
                "className": row.get("setClassName"),
                "itemClassName": row.get("itemClassName"),
                "itemsCount": toOptionalInt(properties.get("itemsCount")) if isinstance(properties, dict) else None,
                "maxItemId": toOptionalInt(properties.get("maxItemId")) if isinstance(properties, dict) else None,
                "columnsCount": toOptionalInt(properties.get("columnsCount")) if isinstance(properties, dict) else None,
                "lastSyncAt": properties.get("lastSyncAt") if isinstance(properties, dict) else None,
                "lastCheckedAt": properties.get("lastCheckedAt") if isinstance(properties, dict) else None,
                "skippedLastSync": properties.get("skippedLastSync") if isinstance(properties, dict) else None,
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
            }

        treeRows = mapper.db.fetchAll(
            """
            SELECT
                p."protocolId",
                o.id,
                o."scipionObjId",
                o.name,
                o.path,
                o."className",
                o.value,
                o.label,
                o.comment,
                o.metadata,
                o."createdAt",
                o."updatedAt"
              FROM scipion_objects o
              JOIN protocols p
                ON p.id = o."protocolDbId"
             WHERE o."projectId" = %s
               AND o."parentObjectId" IS NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM scipion_sets s
                     WHERE s."objectId" = o.id
               )
             ORDER BY p."protocolId", o.path
            """,
            (projectId,),
        )

        for row in treeRows:
            protocolId = str(row.get("protocolId"))
            outputName = str(row.get("path") or row.get("name") or "")
            if not protocolId or not outputName:
                continue

            result.setdefault(protocolId, {})[outputName] = {
                "mapperKind": "tree",
                "rootObjectId": row.get("id"),
                "scipionObjId": row.get("scipionObjId"),
                "className": row.get("className"),
                "value": row.get("value"),
                "label": row.get("label"),
                "comment": row.get("comment"),
                "metadata": row.get("metadata") or {},
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
            }

        return result

    def resolveProtocolDbIdForOutputPersistence(
            self,
            mapper,
            projectId: int,
            protocol,
    ) -> Optional[int]:
        protocolId = self.getScipionObjectId(protocol)

        if protocolId in (None, ""):
            return None

        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        return protocolIdentityResolver.resolvePostgresqlProtocolDbId(protocolId)

    def loadPersistedProtocolOutputNames(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> Set[str]:
        """
        Load the names of all flat-set and tree outputs currently persisted
        for one protocol.

        Set root objects are excluded from the tree query because they are
        represented through scipion_sets.
        """
        outputNames: Set[str] = set()

        setRows = mapper.db.fetchAll(
            """
            SELECT "outputName"
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
            """,
            (
                projectId,
                protocolDbId,
            ),
        )

        for row in setRows or []:
            outputName = (
                row.get("outputName")
                if isinstance(row, dict)
                else row[0]
            )

            outputNameText = str(
                outputName or ""
            ).strip()

            if outputNameText:
                outputNames.add(
                    outputNameText
                )

        treeRows = mapper.db.fetchAll(
            """
            SELECT COALESCE(
                       NULLIF(o.path, ''),
                       o.name
                   ) AS "outputName"
              FROM scipion_objects o
             WHERE o."projectId" = %s
               AND o."protocolDbId" = %s
               AND o."parentObjectId" IS NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM scipion_sets s
                     WHERE s."objectId" = o.id
               )
            """,
            (
                projectId,
                protocolDbId,
            ),
        )

        for row in treeRows or []:
            outputName = (
                row.get("outputName")
                if isinstance(row, dict)
                else row[0]
            )

            outputNameText = str(
                outputName or ""
            ).strip()

            if outputNameText:
                outputNames.add(
                    outputNameText
                )

        return outputNames

    def deletePersistedProtocolOutputSnapshots(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            outputNames: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Delete PostgreSQL metadata for outputs that are no longer exposed by
        a terminal protocol.

        Files are intentionally not removed from the filesystem. Their lifecycle
        remains under the native Scipion protocol operations.
        """
        normalizedOutputNames = sorted({
            str(outputName).strip()
            for outputName in outputNames or []
            if str(outputName or "").strip()
        })

        if not normalizedOutputNames:
            return []

        removedOutputs: List[
            Dict[str, Any]
        ] = []

        with mapper.db.transaction():
            for outputName in normalizedOutputNames:
                setCursor = mapper.db.execute(
                    """
                    DELETE FROM scipion_sets
                     WHERE "projectId" = %s
                       AND "protocolDbId" = %s
                       AND "outputName" = %s
                    """,
                    (
                        projectId,
                        protocolDbId,
                        outputName,
                    ),
                    commit=False,
                )

                objectCursor = mapper.db.execute(
                    """
                    DELETE FROM scipion_objects
                     WHERE "projectId" = %s
                       AND "protocolDbId" = %s
                       AND (
                            path = %s
                            OR LEFT(
                                path,
                                CHAR_LENGTH(%s) + 1
                            ) = %s || '.'
                       )
                    """,
                    (
                        projectId,
                        protocolDbId,
                        outputName,
                        outputName,
                        outputName,
                    ),
                    commit=False,
                )

                removedOutputs.append({
                    "outputName": outputName,
                    "setsDeleted": int(
                        setCursor.rowcount or 0
                    ),
                    "objectsDeleted": int(
                        objectCursor.rowcount or 0
                    ),
                })

        return removedOutputs

    def storeGeneratedSetInPostgresql(
            self,
            mapper,
            projectId: Optional[int],
            protocolId: Union[int, str],
            outputName: str,
            scipionSet,
            contextLabel: str,
    ) -> Dict[str, Any]:
        postgresqlSync = None
        postgresqlError = None

        if mapper is None:
            return {
                "postgresqlSync": postgresqlSync,
                "postgresqlError": postgresqlError,
            }

        try:
            from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper

            protocolIdentityResolver = ProtocolIdentityResolver(
                mapper=mapper,
                projectId=projectId,
            )

            protocolDbId = (
                    protocolIdentityResolver.resolvePostgresqlProtocolDbId(protocolId)
                    or protocolId
            )

            setMapper = ScipionSetPostgresqlMapper(mapper.db)
            postgresqlSync = setMapper.storeSet(
                projectId=projectId,
                protocolDbId=protocolDbId,
                outputName=outputName,
                scipionSet=scipionSet,
            )

        except Exception as e:
            postgresqlError = str(e)
            logger.exception(
                "Failed to persist generated %s output to PostgreSQL. projectId=%s protocolId=%s outputName=%s",
                contextLabel,
                projectId,
                protocolId,
                outputName,
            )

        return {
            "postgresqlSync": postgresqlSync,
            "postgresqlError": postgresqlError,
        }

    def registerOutput(
            self,
            projectId: int,
            protocol: Any,
            mapper,
            returnReport: bool = False,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        from app.backend.mapper import (
            ScipionObjectPostgresqlMapper,
            ScipionSetPostgresqlMapper,
        )

        declaredOutputs: List[Dict[str, Any]] = []
        persistedOutputs: List[Dict[str, Any]] = []
        skippedOutputs: List[Dict[str, Any]] = []
        outputErrors: List[Dict[str, Any]] = []
        removedOutputs: List[
            Dict[str, Any]
        ] = []

        currentOutputNames: Set[str] = set()

        protocolId = self.getScipionObjectId(protocol)
        protocolDbId = self.resolveProtocolDbIdForOutputPersistence(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
        )

        if protocolDbId is None:
            raise ValueError(f"Protocol not found in PostgreSQL: {protocolId}")

        reconcileMissingOutputs = (
            self
            .shouldReconcileMissingProtocolOutputs(
                protocol
            )
        )

        persistedOutputNames: Set[str] = set()

        if reconcileMissingOutputs:
            try:
                persistedOutputNames = (
                    self
                    .loadPersistedProtocolOutputNames(
                        mapper=mapper,
                        projectId=projectId,
                        protocolDbId=int(
                            protocolDbId
                        ),
                    )
                )

            except Exception as exc:
                reconcileMissingOutputs = False

                logger.exception(
                    "Could not load persisted protocol output names. "
                    "projectId=%s protocolId=%s",
                    projectId,
                    protocolId,
                )

                outputErrors.append({
                    "outputName": None,
                    "outputClassName": None,
                    "operation": (
                        "load_persisted_output_names"
                    ),
                    "error": str(exc),
                })

        try:
            outputAttributes = list(protocol.iterOutputAttributes())
        except Exception as exc:
            logger.exception(
                "Could not iterate protocol outputs. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )
            outputErrors.append({
                "outputName": None,
                "outputClassName": None,
                "error": str(exc),
            })

            report = {
                "declared": declaredOutputs,
                "persisted": persistedOutputs,
                "skipped": skippedOutputs,
                "errors": outputErrors,
                "removed": removedOutputs,
            }
            return report if returnReport else persistedOutputs

        setMapper = ScipionSetPostgresqlMapper(mapper.db)
        objectMapper = ScipionObjectPostgresqlMapper(mapper.db)

        for outputItem in outputAttributes:
            outputName = None
            outputObj = None

            if isinstance(outputItem, (tuple, list)) and len(outputItem) >= 2:
                outputName = outputItem[0]
                outputObj = outputItem[1]
            else:
                outputName = self.safeCall(outputItem, "getName", None)
                outputObj = outputItem

            outputName = str(outputName or "").strip()
            outputClassName = self.getScipionClassName(outputObj) or ""

            if not outputName:
                skippedOutputs.append({
                    "outputName": outputName,
                    "outputClassName": outputClassName,
                    "reason": "empty_output_name",
                })
                continue

            currentOutputNames.add(
                outputName
            )

            declaredOutputs.append({
                "outputName": outputName,
                "outputClassName": outputClassName,
            })

            if outputObj is None:
                skippedOutputs.append({
                    "outputName": outputName,
                    "outputClassName": "",
                    "reason": "empty_output",
                })
                continue

            try:
                if self.isScipionSetLikeOutput(outputObj):
                    syncInfo = setMapper.storeSet(
                        projectId=projectId,
                        protocolDbId=int(protocolDbId),
                        outputName=outputName,
                        scipionSet=outputObj,
                    )

                    persistedOutputs.append({
                        "outputName": outputName,
                        "outputClassName": outputClassName,
                        "mapperKind": "flat_set",
                        **(syncInfo or {}),
                    })

                elif self.isPersistableNonSetOutput(outputObj):
                    try:
                        syncInfo = objectMapper.storeObjectTree(
                            projectId=projectId,
                            protocolDbId=int(protocolDbId),
                            outputName=outputName,
                            scipionObj=outputObj,
                            registerType=True,
                            includeNestedProperties=True,
                        )
                    except TypeError:
                        syncInfo = objectMapper.storeObjectTree(
                            projectId=projectId,
                            protocolDbId=int(protocolDbId),
                            outputName=outputName,
                            scipionObj=outputObj,
                            includeNestedProperties=True,
                        )

                    persistedOutputs.append({
                        "outputName": outputName,
                        "outputClassName": outputClassName,
                        "mapperKind": "tree",
                        **(syncInfo or {}),
                    })

                else:
                    skippedOutputs.append({
                        "outputName": outputName,
                        "outputClassName": outputClassName,
                        "reason": "unsupported_output_type",
                    })

            except Exception as exc:
                logger.exception(
                    "Failed to persist protocol output. projectId=%s protocolId=%s outputName=%s outputClassName=%s",
                    projectId,
                    protocolId,
                    outputName,
                    outputClassName,
                )
                outputErrors.append({
                    "outputName": outputName,
                    "outputClassName": outputClassName,
                    "error": str(exc),
                })

        if reconcileMissingOutputs:
            staleOutputNames = sorted(
                persistedOutputNames
                - currentOutputNames
            )

            if staleOutputNames:
                try:
                    removedOutputs = (
                        self
                        .deletePersistedProtocolOutputSnapshots(
                            mapper=mapper,
                            projectId=projectId,
                            protocolDbId=int(
                                protocolDbId
                            ),
                            outputNames=staleOutputNames,
                        )
                    )

                except Exception as exc:
                    logger.exception(
                        "Failed to remove stale persisted protocol outputs. "
                        "projectId=%s protocolId=%s outputNames=%s",
                        projectId,
                        protocolId,
                        staleOutputNames,
                    )

                    outputErrors.append({
                        "outputName": None,
                        "outputClassName": None,
                        "operation": (
                            "remove_stale_outputs"
                        ),
                        "staleOutputNames": (
                            staleOutputNames
                        ),
                        "error": str(exc),
                    })

        report = {
            "declared": declaredOutputs,
            "persisted": persistedOutputs,
            "skipped": skippedOutputs,
            "removed": removedOutputs,
            "errors": outputErrors,
        }

        return report if returnReport else persistedOutputs

    def deletePersistedProtocolOutputs(
            self,
            mapper,
            projectId: int,
            protocolId: Union[int, str],
            protocol: Any = None,
            getCurrentProjectPathCallback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        protocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(protocolId)

        if protocolDbId is None:
            return {
                "protocolDbId": None,
                "setsDeleted": 0,
                "objectsDeleted": 0,
                "filesDeleted": 0,
                "filesSkipped": [],
                "fileErrors": [],
                "skipped": True,
                "reason": "protocol_not_found",
            }

        outputFiles = self.collectPersistedProtocolOutputFiles(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
        )

        fileCleanup = self.deletePersistedProtocolOutputFilesFromFilesystem(
            protocol=protocol,
            rawFileNames=outputFiles,
            getCurrentProjectPathCallback=getCurrentProjectPathCallback,
        )

        setRows = mapper.db.fetchAll(
            """
            SELECT id
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
            """,
            (projectId, protocolDbId),
        )

        setIds = [
            int(row.get("id") if isinstance(row, dict) else row[0])
            for row in (setRows or [])
            if (row.get("id") if isinstance(row, dict) else row[0]) is not None
        ]

        setsDeleted = 0
        objectsDeleted = 0

        with mapper.db.transaction():
            if setIds:
                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_table_items
                     WHERE "tableId" IN (
                           SELECT id
                             FROM scipion_set_tables
                            WHERE "setId" = ANY(%s)
                     )
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_table_columns
                     WHERE "tableId" IN (
                           SELECT id
                             FROM scipion_set_tables
                            WHERE "setId" = ANY(%s)
                     )
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_tables
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_items
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_columns
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_properties
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                cur = mapper.db.execute(
                    """
                    DELETE FROM scipion_sets
                     WHERE id = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )
                setsDeleted = int(cur.rowcount or 0)

            cur = mapper.db.execute(
                """
                WITH RECURSIVE object_tree AS (
                    SELECT id
                      FROM scipion_objects
                     WHERE "projectId" = %s
                       AND "protocolDbId" = %s

                    UNION ALL

                    SELECT child.id
                      FROM scipion_objects child
                      JOIN object_tree parent
                        ON child."parentObjectId" = parent.id
                )
                DELETE FROM scipion_objects
                 WHERE id IN (SELECT id FROM object_tree)
                """,
                (projectId, protocolDbId),
                commit=False,
            )
            objectsDeleted = int(cur.rowcount or 0)

        return {
            "protocolDbId": protocolDbId,
            "setsDeleted": setsDeleted,
            "objectsDeleted": objectsDeleted,
            "filesDeleted": fileCleanup.get("filesDeleted", 0),
            "filesSkipped": fileCleanup.get("filesSkipped", []),
            "fileErrors": fileCleanup.get("fileErrors", []),
            "skipped": False,
        }

    def deletePersistedProtocolOutputsForRuntimeProtocols(
            self,
            mapper,
            projectId: int,
            protocols: List[Any],
            getCurrentProjectPathCallback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        cleanupItems = []
        totalSetsDeleted = 0
        totalObjectsDeleted = 0
        totalFilesDeleted = 0
        totalFileErrors = []

        for protocol in protocols or []:
            protocolId = None

            try:
                protocolId = protocol.getObjId()
            except Exception:
                protocolId = protocol

            if protocolId is None:
                continue

            cleanupInfo = self.deletePersistedProtocolOutputs(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                protocol=protocol,
                getCurrentProjectPathCallback=getCurrentProjectPathCallback,
            )

            cleanupItems.append({
                "protocolId": str(protocolId),
                **cleanupInfo,
            })

            totalSetsDeleted += int(cleanupInfo.get("setsDeleted") or 0)
            totalObjectsDeleted += int(cleanupInfo.get("objectsDeleted") or 0)
            totalFilesDeleted += int(cleanupInfo.get("filesDeleted") or 0)
            totalFileErrors.extend(cleanupInfo.get("fileErrors") or [])

        return {
            "protocolsCount": len(cleanupItems),
            "setsDeleted": totalSetsDeleted,
            "objectsDeleted": totalObjectsDeleted,
            "filesDeleted": totalFilesDeleted,
            "fileErrors": totalFileErrors,
            "items": cleanupItems,
        }

    def collectPersistedProtocolOutputFiles(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> List[str]:
        rows = mapper.db.fetchAll(
            """
            SELECT DISTINCT file_name
              FROM (
                    SELECT root.metadata ->> 'fileName' AS file_name
                      FROM scipion_sets s
                      LEFT JOIN scipion_objects root
                        ON root.id = s."objectId"
                     WHERE s."projectId" = %s
                       AND s."protocolDbId" = %s

                    UNION

                    SELECT o.metadata ->> 'fileName' AS file_name
                      FROM scipion_objects o
                     WHERE o."projectId" = %s
                       AND o."protocolDbId" = %s
                       AND o."parentObjectId" IS NULL
              ) files
             WHERE file_name IS NOT NULL
               AND file_name <> ''
            """,
            (
                projectId,
                protocolDbId,
                projectId,
                protocolDbId,
            ),
        )

        result = []
        seen = set()

        for row in rows or []:
            value = row.get("file_name") if isinstance(row, dict) else row[0]
            value = str(value or "").strip()

            if not value or value in seen:
                continue

            seen.add(value)
            result.append(value)

        return result

    def deletePersistedProtocolOutputFilesFromFilesystem(
            self,
            protocol: Any,
            rawFileNames: List[str],
            getCurrentProjectPathCallback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        projectPath = None

        if callable(getCurrentProjectPathCallback):
            try:
                projectPath = getCurrentProjectPathCallback()
            except Exception:
                projectPath = None

        if not projectPath:
            return {
                "filesDeleted": 0,
                "filesSkipped": [
                    {
                        "fileName": fileName,
                        "reason": "missing_project_path",
                    }
                    for fileName in (rawFileNames or [])
                ],
                "fileErrors": [],
            }

        projectPath = os.path.abspath(str(projectPath))

        workingDirPath = None
        if protocol is not None:
            try:
                workingDirPath = protocol.getWorkingDir()
            except Exception:
                workingDirPath = None

        if workingDirPath:
            workingDirPath = str(workingDirPath)
            if not os.path.isabs(workingDirPath):
                workingDirPath = os.path.join(projectPath, workingDirPath)
            workingDirPath = os.path.abspath(workingDirPath)

        allowedRoot = workingDirPath or projectPath

        filesDeleted = 0
        filesSkipped = []
        fileErrors = []

        for rawFileName in rawFileNames or []:
            resolvedPath = self.resolvePersistedOutputFileForDeletion(
                rawFileName=rawFileName,
                projectPath=projectPath,
                allowedRoot=allowedRoot,
            )

            if resolvedPath is None:
                filesSkipped.append({
                    "fileName": str(rawFileName),
                    "reason": "outside_allowed_root",
                })
                continue

            candidatePaths = [
                resolvedPath,
                resolvedPath + "-wal",
                resolvedPath + "-shm",
                resolvedPath + "-journal",
            ]

            for candidatePath in candidatePaths:
                if not os.path.exists(candidatePath):
                    continue

                try:
                    if os.path.isdir(candidatePath) and not os.path.islink(candidatePath):
                        shutil.rmtree(candidatePath)
                    else:
                        os.remove(candidatePath)

                    filesDeleted += 1

                except Exception as e:
                    logger.exception(
                        "Could not delete persisted protocol output file. path=%s",
                        candidatePath,
                    )
                    fileErrors.append({
                        "fileName": str(rawFileName),
                        "path": candidatePath,
                        "error": str(e),
                    })

        return {
            "filesDeleted": filesDeleted,
            "filesSkipped": filesSkipped,
            "fileErrors": fileErrors,
        }

    def resolvePersistedOutputFileForDeletion(
            self,
            rawFileName: str,
            projectPath: str,
            allowedRoot: str,
    ) -> Optional[str]:
        rawFileName = str(rawFileName or "").strip()

        if not rawFileName:
            return None

        if os.path.isabs(rawFileName):
            candidatePath = os.path.abspath(rawFileName)
        else:
            candidatePath = os.path.abspath(os.path.join(projectPath, rawFileName))

        allowedRoot = os.path.abspath(allowedRoot)

        try:
            commonPath = os.path.commonpath([allowedRoot, candidatePath])
        except Exception:
            return None

        if commonPath != allowedRoot:
            return None

        return candidatePath