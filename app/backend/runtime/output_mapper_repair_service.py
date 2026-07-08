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
import os
from typing import Any, Callable, Dict, Optional

from app.backend.runtime.project_runtime_repository import ProjectRuntimeRepository

logger = logging.getLogger(__name__)


class RuntimeOutputMapperRepairService:
    """Repair PostgreSQL runtime output mapper metadata."""

    def __init__(self):
        self.projectRuntimeRepository = ProjectRuntimeRepository()

    def repairPostgresqlRuntimeSetMapperInfo(
            self,
            mapper,
            projectId: int,
            outputObj,
            outputInfo: Dict[str, Any],
            getCurrentProjectPathCallback: Optional[Callable] = None,
    ) -> bool:
        """
        Repair Scipion Set mapper metadata using PostgreSQL stored properties.

        Some outputs loaded from run.db can exist as Set objects but without
        mapper path/prefix initialized. Protocol execution then fails with:

            Set.load: mapper path and prefix not set.

        We do not replace the output object. We only restore the legacy sqlite
        mapper path from PostgreSQL properties so the Scipion Set can load normally.
        """
        if outputObj is None:
            return False

        properties = (outputInfo or {}).get("properties") or {}

        if not isinstance(properties, dict):
            return False

        mapperPath = (
                properties.get("_mapperPath")
                or properties.get("fileName")
                or properties.get("legacyMapperPath")
                or properties.get("legacyFileName")
        )

        if not mapperPath:
            return False

        mapperPath = str(mapperPath).split(",")[0].strip()

        if not mapperPath:
            return False

        if not os.path.isabs(mapperPath):
            projectPath = self._resolveProjectPath(
                mapper=mapper,
                projectId=projectId,
                getCurrentProjectPathCallback=getCurrentProjectPathCallback,
            )

            if projectPath:
                mapperPath = os.path.abspath(os.path.join(str(projectPath), mapperPath))

        if not mapperPath:
            return False

        currentFileName = None

        try:
            currentFileName = outputObj.getFileName()
        except Exception:
            currentFileName = None

        repaired = False

        if not currentFileName:
            try:
                setter = getattr(outputObj, "setFileName", None)
                if callable(setter):
                    setter(mapperPath)
                    repaired = True
            except Exception:
                logger.debug(
                    "Could not set filename on PostgreSQL runtime output object. object=%s mapperPath=%s",
                    outputObj,
                    mapperPath,
                    exc_info=True,
                )

        # Defensive repair for pyworkflow Set internals.
        for attrName, attrValue in (
                ("_mapperPath", mapperPath),
                ("_mapperPrefix", ""),
        ):
            try:
                attr = getattr(outputObj, attrName, None)

                if hasattr(attr, "set"):
                    currentValue = None

                    try:
                        currentValue = attr.get()
                    except Exception:
                        currentValue = None

                    if currentValue in (None, ""):
                        attr.set(attrValue)
                        repaired = True

                elif attr in (None, ""):
                    setattr(outputObj, attrName, attrValue)
                    repaired = True

            except Exception:
                logger.debug(
                    "Could not repair %s on PostgreSQL runtime output object. object=%s value=%s",
                    attrName,
                    outputObj,
                    attrValue,
                    exc_info=True,
                )

        logger.debug(
            "PostgreSQL runtime Set mapper repair. object=%s mapperPath=%s repaired=%s",
            outputObj,
            mapperPath,
            repaired,
        )

        return repaired

    def _resolveProjectPath(
            self,
            mapper,
            projectId: int,
            getCurrentProjectPathCallback: Optional[Callable] = None,
    ) -> Optional[str]:
        projectPath = None

        if getCurrentProjectPathCallback is not None:
            try:
                projectPath = getCurrentProjectPathCallback()
            except Exception:
                projectPath = None

        if not projectPath and mapper is not None:
            try:
                projectPath = self.projectRuntimeRepository.getProjectNameById(
                    mapper=mapper,
                    projectId=projectId,
                )
            except Exception:
                projectPath = None

        return projectPath