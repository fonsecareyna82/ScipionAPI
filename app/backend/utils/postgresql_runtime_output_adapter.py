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
from typing import Any, Dict, Iterator, List, Optional


class PostgresqlRuntimeItemProxy:
    """
    Lightweight item proxy backed by scipion_set_items.values.

    This is intentionally generic. It exposes common Scipion-style getters used
    by protocols without depending on the original output sqlite file.
    """

    def __init__(
            self,
            row: Dict[str, Any],
            itemClassName: Optional[str] = None,
            parent=None,
    ):
        self._row = dict(row or {})
        self._values = self._row.get("values") or {}
        self._itemClassName = itemClassName
        self._parent = parent

    def getObjId(self):
        return self._row.get("scipionItemId") or self._row.get("id")

    def getClassName(self):
        return self._itemClassName or self._firstValueBySuffix(
            ["className", "_className"]
        ) or self.__class__.__name__

    def getObjLabel(self):
        return (
            self._row.get("label")
            or self._firstValueBySuffix(["label", "objLabel", "name"])
            or str(self.getObjId())
        )

    def getObjComment(self):
        return self._row.get("comment")

    def getObjCreation(self):
        return self._row.get("creation")

    def isEnabled(self):
        value = self._row.get("enabled")
        if value is None:
            value = self._firstValueBySuffix(["enabled", "isEnabled"])
        return self._toBool(value, default=True)

    def getObjParent(self):
        return self._parent

    def getObjParentId(self):
        try:
            return self._parent.getObjId()
        except Exception:
            return None

    def getFileName(self):
        return self._firstValueBySuffix(
            ["fileName", "filename", "filePath", "path", "_filename"]
        )

    def getLocation(self):
        return self._firstValueBySuffix(["location", "_location"])

    def getTsId(self):
        return self._firstValueBySuffix(
            ["tsId", "_tsId", "tiltSeriesId", "seriesId"]
        )

    def getTSId(self):
        return self.getTsId()

    def getTomoId(self):
        return self._firstValueBySuffix(
            ["tomoId", "_tomoId", "tomogramId", "volumeId"]
        )

    def getTomogramId(self):
        return self.getTomoId()

    def getSamplingRate(self):
        return self._toFloat(
            self._firstValueBySuffix(["samplingRate", "_samplingRate", "pixelSize"])
        )

    def getDim(self):
        value = self._firstValueBySuffix(
            ["dim", "dims", "dimensions", "imageDim", "imageDims", "_dim"]
        )
        return self._parseNumericTuple(value)

    def getDimensions(self):
        return self.getDim()

    def getX(self):
        return self._toFloat(self._firstValueBySuffix(["x", "_x"]))

    def getY(self):
        return self._toFloat(self._firstValueBySuffix(["y", "_y"]))

    def getZ(self):
        return self._toFloat(self._firstValueBySuffix(["z", "_z"]))

    def getCoordinate3D(self):
        x = self.getX()
        y = self.getY()
        z = self.getZ()

        if x is None or y is None or z is None:
            return None

        return x, y, z

    def getValues(self) -> Dict[str, Any]:
        return dict(self._values)

    def _firstValueBySuffix(self, suffixes: List[str]):
        normalizedSuffixes = [
            str(suffix).replace("_", "").replace(".", "").lower()
            for suffix in suffixes
        ]

        for key, value in self._values.items():
            normalizedKey = str(key).replace("_", "").replace(".", "").lower()

            for suffix in normalizedSuffixes:
                if normalizedKey.endswith(suffix):
                    return value

        return None

    def _toFloat(self, value):
        if value in (None, ""):
            return None

        try:
            return float(value)
        except Exception:
            return None

    def _toBool(self, value, default=False):
        if value in (None, ""):
            return default

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return bool(value)

        text = str(value).strip().lower()

        if text in ("1", "true", "yes", "y", "on", "enabled"):
            return True

        if text in ("0", "false", "no", "n", "off", "disabled"):
            return False

        return default

    def _parseNumericTuple(self, value):
        if value in (None, ""):
            return None

        if isinstance(value, (list, tuple)):
            rawValues = value
        else:
            text = str(value).strip().strip("[]()")
            if not text:
                return None

            for sep in ("x", "X", ",", ";"):
                text = text.replace(sep, " ")

            rawValues = [part for part in text.split() if part]

        result = []

        for rawValue in rawValues:
            number = self._toFloat(rawValue)

            if number is None:
                return None

            if float(number).is_integer():
                number = int(number)

            result.append(number)

        return tuple(result)

    def __getattr__(self, name: str):
        """
        Generic Scipion-style getter fallback.

        Example:
          item.getTiltAngle() -> values key ending in tiltAngle
          item.getAcquisitionOrder() -> values key ending in acquisitionOrder
        """
        if not name.startswith("get") or len(name) <= 3:
            raise AttributeError(name)

        suffix = name[3:]
        if not suffix:
            raise AttributeError(name)

        def getter(*_args, **_kwargs):
            return self._firstValueBySuffix([suffix])

        return getter

    def __repr__(self):
        return (
            "<PostgresqlRuntimeItemProxy class=%s objId=%s label=%s>"
            % (self.getClassName(), self.getObjId(), self.getObjLabel())
        )


class PostgresqlRuntimeOutputProxy:
    """
    Lightweight PostgreSQL-backed output proxy.

    It is used as parentProtocol.<outputName> so Pointer(...).get() can return
    an object backed by PostgreSQL instead of the original sqlite-backed output.
    """

    def __init__(
            self,
            db,
            parent,
            outputName: str,
            outputInfo: Dict[str, Any],
    ):
        self._db = db
        self._parent = parent
        self._outputName = outputName
        self._info = dict(outputInfo or {})
        self._properties = self._info.get("properties") or {}
        self._itemsCache = None
        self._relatedOutputs = {}

    def getObjId(self):
        value = self._info.get("objectId")

        try:
            return int(value)
        except Exception:
            return value

    def getClassName(self):
        return self._info.get("className") or self.__class__.__name__

    def getItemClassName(self):
        return self._info.get("itemClassName")

    def getObjParent(self):
        return self._parent

    def getObjParentId(self):
        try:
            return self._parent.getObjId()
        except Exception:
            return None

    def getName(self):
        return self._outputName

    def getObjLabel(self):
        return self._outputName

    def getSize(self):
        value = self._info.get("itemsCount")

        if value in (None, ""):
            value = self._properties.get("itemsCount") or self._properties.get("_size")

        try:
            return int(value)
        except Exception:
            return 0

    def isEmpty(self):
        return self.getSize() == 0

    def getFileName(self):
        """
        Do not return the original legacy sqlite here.

        If a protocol fails because it requires getFileName(), that is exactly
        the next runtime dependency we need to solve with real materialization
        or a richer PostgreSQL-backed adapter.
        """
        return None

    def getLegacyFileName(self):
        return self._properties.get("fileName")

    def getLegacyMapperPath(self):
        return self._properties.get("_mapperPath")

    def getSamplingRate(self):
        value = (
            self._properties.get("samplingRate")
            or self._properties.get("_samplingRate")
        )

        try:
            return float(value)
        except Exception:
            return None

    def getDim(self):
        return self._parseNumericTuple(
            self._properties.get("_firstDim")
            or self._properties.get("firstDim")
            or self._properties.get("dimensions")
            or self._properties.get("dim")
        )

    def getDimensions(self):
        return self.getDim()

    def getStreamState(self):
        value = (
            self._properties.get("streamState")
            or self._properties.get("_streamState")
        )

        try:
            return int(value)
        except Exception:
            return value

    def isStreamClosed(self):
        streamState = self.getStreamState()

        try:
            return int(streamState) == 2
        except Exception:
            return True

    def isStreamOpen(self):
        return not self.isStreamClosed()

    def getTSIds(self):
        result = []

        for item in self.iterItems():
            tsId = None

            try:
                tsId = item.getTsId()
            except Exception:
                tsId = None

            if tsId not in (None, ""):
                result.append(tsId)

        return result

    def iterItems(self, *args, **kwargs) -> Iterator[PostgresqlRuntimeItemProxy]:
        for row in self._loadItems():
            yield PostgresqlRuntimeItemProxy(
                row=row,
                itemClassName=self.getItemClassName(),
                parent=self,
            )

    def __iter__(self):
        return self.iterItems()

    def _loadItems(self):
        if self._itemsCache is not None:
            return self._itemsCache

        setId = self._info.get("setId")

        if setId is None:
            self._itemsCache = []
            return self._itemsCache

        rows = self._db.fetchAll(
            """
            SELECT id,
                   "setId",
                   "scipionItemId",
                   enabled,
                   label,
                   comment,
                   creation,
                   "values",
                   "createdAt",
                   "updatedAt"
              FROM scipion_set_items
             WHERE "setId" = %s
             ORDER BY "scipionItemId" ASC
            """,
            (int(setId),),
        )

        self._itemsCache = [dict(row) for row in rows or []]

        return self._itemsCache

    def getPostgresqlRuntimeInfo(self):
        return dict(self._info)

    def isPostgresqlRuntimeOutput(self):
        return True

    def _parseNumericTuple(self, value):
        if value in (None, ""):
            return None

        if isinstance(value, (list, tuple)):
            rawValues = value
        else:
            text = str(value).strip().strip("[]()")
            if not text:
                return None

            for sep in ("x", "X", ",", ";"):
                text = text.replace(sep, " ")

            rawValues = [part for part in text.split() if part]

        result = []

        for rawValue in rawValues:
            try:
                number = float(rawValue)
            except Exception:
                return None

            if number.is_integer():
                number = int(number)

            result.append(number)

        return tuple(result)

    def __getattr__(self, name: str):
        if name.startswith("set") and len(name) > 3:
            relationName = name[3:4].lower() + name[4:]

            def setter(value):
                self._relatedOutputs[relationName] = value

            return setter

        if name.startswith("get") and len(name) > 3:
            relationName = name[3:4].lower() + name[4:]

            def getter(*_args, **_kwargs):
                return self._relatedOutputs.get(relationName)

            return getter

        raise AttributeError(name)

    def __bool__(self):
        return True

    def __repr__(self):
        return (
            "<PostgresqlRuntimeOutputProxy name=%s class=%s objectId=%s items=%s>"
            % (
                self._outputName,
                self.getClassName(),
                self.getObjId(),
                self.getSize(),
            )
        )