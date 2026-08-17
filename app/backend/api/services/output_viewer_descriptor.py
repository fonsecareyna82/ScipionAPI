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
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional

from pyworkflow.object import Set as ScipionSet
from tomo.objects import (
    Coordinate3D,
    SetOfCoordinates3D,
    SetOfTiltSeries,
    TiltSeries,
)


VIEWER_CAPABILITY_SET = "set"
VIEWER_CAPABILITY_COORDINATES3D = "coordinates3d"
VIEWER_CAPABILITY_TILT_SERIES = "tiltSeries"


@dataclass(frozen=True)
class OutputViewerDescriptor:
    outputName: str
    className: str
    itemClassName: str
    kind: str
    mapperKind: Optional[str]
    runtimeClassName: str
    runtimeAvailable: bool
    capabilities: FrozenSet[str]

    def hasCapability(
            self,
            capability: str,
    ) -> bool:
        return capability in self.capabilities


class OutputViewerDescriptorBuilder:

    @staticmethod
    def _getRuntimeClassName(
            output: Any,
    ) -> str:
        if output is None:
            return ""

        getClassName = getattr(
            output,
            "getClassName",
            None,
        )

        if callable(getClassName):
            try:
                value = getClassName()

                if value:
                    return str(value).strip()
            except Exception:
                pass

        try:
            return str(
                output.__class__.__name__
            ).strip()
        except Exception:
            return ""

    @staticmethod
    def _getRuntimeItemType(
            output: Any,
    ):
        if output is None:
            return None

        itemType = getattr(
            output,
            "ITEM_TYPE",
            None,
        )

        return (
            itemType
            if isinstance(itemType, type)
            else None
        )

    @staticmethod
    def _getTypeName(
            value: Any,
    ) -> str:
        if not isinstance(value, type):
            return ""

        return str(
            getattr(value, "__name__", "")
            or ""
        ).strip()

    @staticmethod
    def _isSubclass(
            value: Any,
            parentClass: type,
    ) -> bool:
        if not isinstance(value, type):
            return False

        try:
            return issubclass(
                value,
                parentClass,
            )
        except Exception:
            return False

    @classmethod
    def build(
            cls,
            *,
            outputName: str,
            output: Any = None,
            outputInfo: Optional[
                Dict[str, Any]
            ] = None,
            fallbackClassName: str = "",
    ) -> OutputViewerDescriptor:
        info = (
            outputInfo
            if isinstance(
                outputInfo,
                dict,
            )
            else {}
        )

        runtimeClassName = (
            cls._getRuntimeClassName(
                output
            )
        )

        itemType = (
            cls._getRuntimeItemType(
                output
            )
        )

        className = str(
            info.get("className")
            or runtimeClassName
            or fallbackClassName
            or ""
        ).strip()

        itemClassName = str(
            info.get("itemClassName")
            or cls._getTypeName(
                itemType
            )
            or ""
        ).strip()

        kind = str(
            info.get("kind")
            or ""
        ).strip().lower()

        isSet = (
            kind == "set"
            or isinstance(
                output,
                ScipionSet,
            )
        )

        if not kind:
            if isSet:
                kind = "set"
            elif output is not None:
                kind = "object"

        mapperKind = str(
            info.get("mapperKind")
            or ""
        ).strip()

        if not mapperKind:
            if kind == "set":
                mapperKind = "flat_set"
            elif kind == "object":
                mapperKind = "tree"
            else:
                mapperKind = None

        capabilities = set()

        if isSet:
            capabilities.add(
                VIEWER_CAPABILITY_SET
            )

        if output is not None:
            if (
                    isinstance(
                        output,
                        SetOfCoordinates3D,
                    )
                    or cls._isSubclass(
                        itemType,
                        Coordinate3D,
                    )
            ):
                capabilities.add(
                    VIEWER_CAPABILITY_COORDINATES3D
                )

            if (
                    isinstance(
                        output,
                        SetOfTiltSeries,
                    )
                    or cls._isSubclass(
                        itemType,
                        TiltSeries,
                    )
            ):
                capabilities.add(
                    VIEWER_CAPABILITY_TILT_SERIES
                )

        return OutputViewerDescriptor(
            outputName=str(
                outputName or ""
            ).strip(),
            className=className,
            itemClassName=itemClassName,
            kind=kind,
            mapperKind=mapperKind,
            runtimeClassName=runtimeClassName,
            runtimeAvailable=(
                output is not None
            ),
            capabilities=frozenset(
                capabilities
            ),
        )