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
from typing import Any, Dict, Optional, Type

from app.backend.mapper.postgresql_scipion_item_hydrator import (
    PostgresqlScipionItemHydrator,
)
from app.backend.mapper.postgresql_set_runtime_mapper import (
    PostgresqlSetRuntimeMapper,
)
from app.backend.mapper.scipion_set_mapper import (
    ScipionSetPostgresqlMapper,
)


class PostgresqlRuntimeSetMixin:
    """
    Runtime behavior added to native Scipion SetOf... classes.

    The original Scipion API is preserved, but load() reconstructs the
    PostgreSQL mapper instead of opening the legacy SQLite file.
    """

    def load(self):
        mapperFactory = getattr(
            self,
            "_postgresqlMapperFactory",
            None,
        )

        if not callable(mapperFactory):
            raise RuntimeError(
                "PostgreSQL runtime set does not have a mapper factory."
            )

        self._mapper = mapperFactory()
        self._size.set(self._mapper.count())
        self._idCount = self._mapper.maxId()

        return self

    def close(self):
        mapper = getattr(
            self,
            "_mapper",
            None,
        )

        if mapper is not None:
            mapper.close()

        self._mapper = None

    def getFileName(self):
        """
        A PostgreSQL runtime set must not expose the original SQLite as its
        active persistence source.
        """
        return None

    def getLegacyFileName(self):
        return self._postgresqlRuntimeProperties.get(
            "fileName"
        )

    def getLegacyMapperPath(self):
        return self._postgresqlRuntimeProperties.get(
            "_mapperPath"
        )

    def getPostgresqlRuntimeInfo(self):
        return dict(
            self._postgresqlRuntimeInfo
        )

    def isPostgresqlRuntimeOutput(self):
        return True

    def write(self, properties=True):
        raise RuntimeError(
            "PostgreSQL runtime input sets are read-only."
        )


class PostgresqlRuntimeSetFactory:
    """
    Build native Scipion SetOf... instances backed by PostgreSQL.
    """

    SKIPPED_PROPERTY_PATHS = {
        "_mapperPath",
        "_size",
    }

    _runtimeClassCache: Dict[Type, Type] = {}

    def build(
            self,
            db,
            parent,
            outputName: str,
            outputInfo: Dict[str, Any],
            classes: Optional[Dict[str, Type]] = None,
    ):
        if db is None:
            raise ValueError("db is required")

        info = dict(
            outputInfo or {}
        )

        setId = info.get("setId")
        setClassName = (
            info.get("className")
            or info.get("setClassName")
        )
        itemClassName = info.get(
            "itemClassName"
        )

        if setId is None:
            raise ValueError(
                "PostgreSQL runtime set requires setId"
            )

        if not setClassName:
            raise ValueError(
                "PostgreSQL runtime set requires className"
            )

        if not itemClassName:
            raise ValueError(
                "PostgreSQL runtime set requires itemClassName"
            )

        classRegistry = self._loadClasses(
            classes
        )

        nativeSetClass = classRegistry.get(
            str(setClassName)
        )

        if nativeSetClass is None:
            raise ValueError(
                "Scipion set class '%s' was not found in Domain.getObjects()"
                % setClassName
            )

        runtimeSetClass = self._getRuntimeSetClass(
            nativeSetClass
        )

        runtimeSet = runtimeSetClass()

        properties = self._normalizeProperties(
            info.get("properties")
        )

        runtimeSet._postgresqlRuntimeInfo = info
        runtimeSet._postgresqlRuntimeProperties = properties

        self._applyBasicMetadata(
            runtimeSet=runtimeSet,
            parent=parent,
            outputName=outputName,
            outputInfo=info,
        )

        self._hydrateSetProperties(
            runtimeSet=runtimeSet,
            properties=properties,
        )

        setMapper = ScipionSetPostgresqlMapper(
            db=db
        )

        columns = setMapper.getStoredSetColumns(
            int(setId)
        )

        itemHydrator = PostgresqlScipionItemHydrator(
            itemClassName=str(itemClassName),
            columns=columns,
            parent=runtimeSet,
            classes=classRegistry,
        )

        def mapperFactory():
            return PostgresqlSetRuntimeMapper(
                db=db,
                setId=int(setId),
                itemBuilder=itemHydrator,
            )

        runtimeSet._postgresqlMapperFactory = (
            mapperFactory
        )

        runtimeSet.load()

        return runtimeSet

    def _getRuntimeSetClass(
            self,
            nativeSetClass: Type,
    ) -> Type:
        runtimeClass = self._runtimeClassCache.get(
            nativeSetClass
        )

        if runtimeClass is not None:
            return runtimeClass

        runtimeClass = type(
            nativeSetClass.__name__,
            (
                PostgresqlRuntimeSetMixin,
                nativeSetClass,
            ),
            {
                "__module__": nativeSetClass.__module__,
            },
        )

        self._runtimeClassCache[
            nativeSetClass
        ] = runtimeClass

        return runtimeClass

    def _loadClasses(
            self,
            extraClasses: Optional[Dict[str, Type]],
    ) -> Dict[str, Type]:
        classes: Dict[str, Type] = {}

        try:
            from pwem import Domain

            classes.update(
                Domain.getObjects() or {}
            )
        except Exception:
            pass

        if extraClasses:
            classes.update(
                extraClasses
            )

        return classes

    def _applyBasicMetadata(
            self,
            runtimeSet,
            parent,
            outputName: str,
            outputInfo: Dict[str, Any],
    ) -> None:
        if "runtimeObjectId" in outputInfo:
            runtimeObjectId = outputInfo.get(
                "runtimeObjectId"
            )
        else:
            runtimeObjectId = outputInfo.get(
                "objectId"
            )

        if runtimeObjectId is not None:
            runtimeSet.setObjId(
                self._toOptionalInt(
                    runtimeObjectId
                )
            )

        runtimeSet.setName(
            str(outputName)
        )

        runtimeSet.setObjLabel(
            str(outputName)
        )

        runtimeSet._objParent = parent

        parentIdGetter = getattr(
            parent,
            "getObjId",
            None,
        )

        if callable(parentIdGetter):
            try:
                runtimeSet._objParentId = (
                    parentIdGetter()
                )
            except Exception:
                runtimeSet._objParentId = None

    def _hydrateSetProperties(
            self,
            runtimeSet,
            properties: Dict[str, Any],
    ) -> None:
        for path, value in properties.items():
            path = str(path)

            if not path.startswith("_"):
                continue

            if path in self.SKIPPED_PROPERTY_PATHS:
                continue

            self._setExistingAttributeValue(
                runtimeSet,
                path,
                value,
            )

    def _setExistingAttributeValue(
            self,
            runtimeSet,
            path: str,
            value: Any,
    ) -> bool:
        parts = [
            part
            for part in path.split(".")
            if part
        ]

        if not parts:
            return False

        current = runtimeSet

        for part in parts:
            current = getattr(
                current,
                part,
                None,
            )

            if current is None:
                return False

        setter = getattr(
            current,
            "set",
            None,
        )

        if not callable(setter):
            return False

        setter(value)

        return True

    def _normalizeProperties(
            self,
            properties,
    ) -> Dict[str, Any]:
        if isinstance(properties, dict):
            return dict(properties)

        if isinstance(properties, str):
            try:
                parsed = json.loads(
                    properties
                )
            except Exception:
                return {}

            if isinstance(parsed, dict):
                return dict(parsed)

        return {}

    def _toOptionalInt(
            self,
            value,
    ):
        if value in (None, ""):
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return value