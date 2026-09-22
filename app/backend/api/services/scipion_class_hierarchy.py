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
import logging
from typing import Dict, List

from pyworkflow.object import OBJECTS_DICT


logger = logging.getLogger(__name__)


class ScipionClassHierarchyResolver:

    @staticmethod
    def getClassHierarchyNames(
            objectClass,
    ) -> List[str]:
        if not isinstance(
                objectClass,
                type,
        ):
            return []

        hierarchy = []

        for baseClass in getattr(
                objectClass,
                "__mro__",
                (),
        ):
            className = str(
                getattr(
                    baseClass,
                    "__name__",
                    "",
                )
                or ""
            ).strip()

            if (
                    not className
                    or className == "object"
                    or className in hierarchy
            ):
                continue

            hierarchy.append(
                className
            )

        return hierarchy

    @classmethod
    def getRuntimeObjectClassHierarchy(
            cls,
            runtimeObject,
    ) -> List[str]:
        if runtimeObject is None:
            return []

        objectClass = None

        getClass = getattr(
            runtimeObject,
            "getClass",
            None,
        )

        if callable(getClass):
            try:
                candidateClass = getClass()

                if isinstance(
                        candidateClass,
                        type,
                ):
                    objectClass = candidateClass

            except Exception:
                objectClass = None

        if objectClass is None:
            objectClass = (
                runtimeObject.__class__
            )

        return (
            cls
            .getClassHierarchyNames(
                objectClass
            )
        )

    @staticmethod
    def loadScipionObjectClasses(
    ) -> Dict[str, type]:
        classes = dict(
            OBJECTS_DICT
            or {}
        )

        try:
            from pwem import Domain

            classes.update(
                Domain.getObjects()
                or {}
            )

        except Exception:
            logger.debug(
                "Could not load Scipion Domain objects "
                "while resolving output class hierarchy.",
                exc_info=True,
            )

        return classes

    @classmethod
    def getPersistedClassHierarchy(
            cls,
            className,
            classRegistry=None,
    ) -> List[str]:
        normalizedClassName = str(
            className
            or ""
        ).strip()

        if not normalizedClassName:
            return []

        if classRegistry is None:
            classRegistry = (
                cls
                .loadScipionObjectClasses()
            )

        objectClass = (
            classRegistry.get(
                normalizedClassName
            )
        )

        if isinstance(
                objectClass,
                type,
        ):
            return (
                cls
                .getClassHierarchyNames(
                    objectClass
                )
            )

        return [
            normalizedClassName
        ]