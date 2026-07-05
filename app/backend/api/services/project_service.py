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
import base64
import collections
import io
import logging
import re
from functools import lru_cache
from urllib.request import urlopen
from uuid import uuid4
import copy
import json
import sys
import threading
import textwrap
import shutil

import numpy as np

from metadataviewer.dao.numpy_dao import NumpyDao
from metadataviewer.model import ObjectManager
from starlette.responses import JSONResponse
from tomo.constants import BOTTOM_LEFT_CORNER
from tomo.objects import SetOfTiltSeries, TiltSeries, Coordinate3D

from app.backend.utils.constants import SQLITE_OBJECT_TABLE, maxThumbSize
from app.backend.utils.outputs_preview import OutputsPreview
from app.backend.utils.volume_surface_mesh import buildVolumeSurfaceMesh
from app.backend.utils.volume_utils import readVolumeArray3d, readVolumeSlice2d
from app.backend.api.services.protocol_wizard_service import (
    ProtocolWizardService,
    findProtocolWizardsWeb,
)
from pwem.emlib.image.image_readers import ImageReadersRegistry, ImageStack
from pwem.objects import SetOfVolumes
from pwem.protocols import ProtUserSubSet
from pwem.viewers.mdviewer.readers import ScipionImageReader
from pwem.viewers.mdviewer.sqlite_dao import ScipionSetsDAO, OBJECT_TABLE
from pwem.viewers.mdviewer.star_dao import StarFile
from pyworkflow.object import (
    Object as ScipionObject,
    PointerList,
    Pointer,
    CsvList,
    Set as ScipionSet,
)
from pyworkflow.protocol import (
    MODE_RESUME,
    MODE_RESTART,
    STATUS_FINISHED,
    STATUS_LAUNCHED,
    STATUS_NEW,
    STATUS_RUNNING,
    STATUS_SCHEDULED,
)
from pyworkflow.template import TemplateList
from pyworkflow.protocol.protocol import getProtocolFromDb

try:
    from pyworkflow.viewer import DESKTOP_TKINTER
except Exception:
    DESKTOP_TKINTER = None
    findViewers=None

logger = logging.getLogger(__name__)

import os
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Any, Union, Tuple, Dict, Set as TypingSet, Sequence
from fastapi import HTTPException, status, Response
from pathlib import Path as FsPath
import mimetypes
import pyworkflow
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from pyworkflow.config import Config
from pyworkflow.project import Manager, Project as ScipionProject
from app.backend.project import PostgresqlProject
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper
from pyworkflow.protocol.params import (IntParam, FloatParam, BooleanParam, StringParam, EnumParam, PointerParam,
                                        MultiPointerParam, RelationParam)
import pyworkflow.utils as pwutils
from app.backend.api.schemas.project_schema import ProjectCreate, ProjectUpdate
from app.backend.utils.file_handlers import FileHandlers

from app.utils.scipion_helper import serializeToJson

from app.backend.api.services.plugins_revision import getPluginsRevision
from app.backend.utils.thumbnail_service import ThumbnailService
from app.backend.api.services.settings_service import SettingsService

# protocolsTreeCacheByRevision
_protocolsTreeLock = threading.Lock()
_protocolsTreeCache: Dict[int, Dict[str, Any]] = {}
_lastProtocolsTreeRevision = -1

_VOLUME_SLICE_CACHE_LOCK = threading.Lock()
_VOLUME_SLICE_CACHE = collections.OrderedDict()
_VOLUME_SLICE_CACHE_MAX_ITEMS = 128

# newProtocolContextCacheRevisionDriven
_newProtocolLock = threading.Lock()
_newProtocolCache: Dict[str, Dict[str, Any]] = {}
_lastNewProtocolRevision = -1

# Global lock for metadata / DAO operations (not thread-safe)
_metadataLock = threading.Lock()

# Global lock for Scipion project thumbnail operations.
# Loading several Scipion projects concurrently can mix project state in Pyworkflow internals.
_thumbnailProjectLock = threading.Lock()

# In-memory cache for rendered tilt-series previews.
# The key includes file path, mtime and render options, so changed stacks invalidate naturally.
_tiltSeriesPreviewCacheLock = threading.Lock()
_tiltSeriesPreviewCache = collections.OrderedDict()
_TILT_SERIES_PREVIEW_CACHE_LIMIT = 160

def _invalidateProtocolsTreeCacheIfNeeded() -> int:
    # invalidateProtocolsTreeCacheIfNeeded
    global _lastProtocolsTreeRevision
    rev = int(getPluginsRevision() or 0)

    with _protocolsTreeLock:
        if rev != _lastProtocolsTreeRevision:
            _protocolsTreeCache.clear()
            _lastProtocolsTreeRevision = rev

    return rev


def _invalidateNewProtocolCacheIfNeeded() -> int:
    # invalidateNewProtocolCacheIfNeeded
    global _lastNewProtocolRevision
    rev = int(getPluginsRevision() or 0)

    with _newProtocolLock:
        if rev != _lastNewProtocolRevision:
            _newProtocolCache.clear()
            _lastNewProtocolRevision = rev

    return rev


class ProjectService:
    def __init__(self):
        self.manager = Manager()
        # Keep objectManager attribute for backward compatibility,
        # but new HTTP endpoints use a fresh ObjectManager per request.
        self.objectManager = None

        # Real per-instance state
        self.currentProject: Optional[ScipionProject] = None
        self.tomoList: Dict[Any, Any] = {}

    # ------------------------------------------------------------------
    # Per-request project / tomogram context
    # ------------------------------------------------------------------
    def clearCurrentProject(self):
        """Clear per-request project and tomogram cache."""
        self.currentProject = None
        self.tomoList = {}

    def _currentProjectUsesPostgresqlRuntimeMapper(self) -> bool:
        project = getattr(self, "currentProject", None)
        if project is None:
            return False

        checker = getattr(project, "usingPostgresqlRuntimeMapper", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False

        return isinstance(getattr(project, "mapper", None), PostgresqlRuntimeMapper)

    def _shouldUsePostgresqlRuntimeProject(self, explicit: bool = False) -> bool:
        if explicit:
            return True

        value = os.environ.get("SCIPIONWEB_USE_POSTGRESQL_RUNTIME_PROJECT", "")
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _replaceCurrentProjectWithPostgresqlProject(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            enableReadFallback: bool = True,
            enableWriteFallback: bool = False,
    ) -> None:
        """
        Replace the currently loaded Scipion Project with a PostgreSQL-aware
        Project wrapper.

        This keeps Scipion paths/settings/hosts but makes Project.mapper and
        Protocol.mapper delegate writes to PostgreSQL.
        """
        currentProject = getattr(self, "currentProject", None)
        if currentProject is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No current project loaded",
            )

        if self._currentProjectUsesPostgresqlRuntimeMapper():
            return

        projectPath = getattr(currentProject, "path", None)
        if not projectPath:
            try:
                projectPath = currentProject.getPath()
            except Exception:
                projectPath = None

        if not projectPath:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Cannot enable PostgreSQL runtime project: missing project path",
            )

        domain = currentProject.getDomain()

        try:
            currentProject.closeMapper()
        except Exception:
            logger.debug(
                "Could not close legacy project mapper before PostgreSQL runtime replacement.",
                exc_info=True,
            )

        pgProject = PostgresqlProject(
            domain=domain,
            path=projectPath,
            projectId=projectId,
            flatMapper=mapper,
            enableReadFallback=enableReadFallback,
            enableWriteFallback=enableWriteFallback,
        )

        pgProject.load(chdir=True)

        self.currentProject = pgProject

        logger.info(
            "Loaded project %s with PostgreSQL runtime mapper. readFallback=%s writeFallback=%s",
            projectId,
            enableReadFallback,
            enableWriteFallback,
        )

    def _createObjectManager(self) -> ObjectManager:
        """Create and configure a fresh ObjectManager instance.

        A new instance is returned on each call to avoid sharing
        SQLite connections across threads.
        """
        objMgr = ObjectManager()
        objMgr.registerDAO(ScipionSetsDAO)
        objMgr.registerDAO(StarFile)
        objMgr.registerReader(ScipionImageReader)
        NumpyDao.addCompatibleFileType('cs')
        return objMgr

    def initializeOrderManager(self):
        """Kept for backward compatibility with older code paths.

        New HTTP endpoints should call _createObjectManager() instead
        of relying on a shared instance.
        """
        if self.objectManager is None:
            self.objectManager = self._createObjectManager()
        return self.objectManager

    def _getPreviewObjectManager(self) -> ObjectManager:
        """
        Return an ObjectManager for preview operations.

        Prefer a fresh instance to avoid sharing SQLite connections across
        concurrent HTTP requests.
        """
        return self._createObjectManager()

    def _safeScipionValue(self, value: Any) -> Any:
        """
        Convert Scipion/Python values into JSON-safe preview values.
        """
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            if isinstance(value, str) and len(value) > 240:
                return value[:240] + "..."
            return value

        if isinstance(value, (list, tuple)):
            return [self._safeScipionValue(v) for v in value[:20]]

        if isinstance(value, dict):
            return {
                str(k): self._safeScipionValue(v)
                for k, v in list(value.items())[:30]
            }

        try:
            text = str(value)
            return text[:240] + "..." if len(text) > 240 else text
        except Exception:
            return repr(value)

    def _tryReadScipionSetWithObjectManager(self, filePath: FsPath) -> Optional[Any]:
        """
        Try several ObjectManager entry points because different metadata
        viewer versions expose slightly different method names.
        """
        objMgr = self._getPreviewObjectManager()
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

    def _extractScipionSetPreviewInfo(self, obj: Any) -> Dict[str, Any]:
        """
        Build a compact preview payload from a Scipion set-like object.
        """
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

        summary: list[Dict[str, Any]] = []

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
                safeValue = self._safeScipionValue(value)
                if safeValue not in (None, ""):
                    summary.append({"key": label, "value": safeValue})
            except Exception:
                pass

        sampleRows = []
        sampleColumns: list[str] = []

        try:
            iterator = iter(obj)
            for index, item in enumerate(iterator):
                if index >= 10:
                    break

                row = self._buildScipionItemPreviewRow(item)
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

    def _buildScipionItemPreviewRow(self, item: Any) -> Dict[str, Any]:
        """
        Build a compact preview row for one Scipion object item.
        """
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
                row[key] = self._safeScipionValue(value)
            except Exception:
                pass

        if not row:
            try:
                row["value"] = self._safeScipionValue(item)
            except Exception:
                pass

        return row

    def _inspectScipionSqliteDatabase(self, filePath: FsPath) -> Optional[Dict[str, Any]]:
        """
        Inspect a Scipion SQLite object database using the metadata viewer
        ObjectManager when possible.
        """
        obj = self._tryReadScipionSetWithObjectManager(filePath)
        if obj is None:
            return None

        info = self._extractScipionSetPreviewInfo(obj)
        info["reader"] = "ObjectManager"
        return info

    @staticmethod
    def sanitizeProjectName(rawName: str) -> str:
        """
        Return a filesystem-safe project name.

        Rules:
          - Replace any char not in [A-Za-z0-9_-] with '_'
          - Collapse consecutive underscores
          - Strip leading/trailing underscores and dots
          - Ensure non-empty (fallback to 'project')
        """
        if rawName is None:
            rawName = ""

        # Trim whitespace
        name = rawName.strip()

        # Replace invalid chars with underscore
        name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)

        # Collapse multiple underscores
        name = re.sub(r"_+", "_", name)

        # Strip leading/trailing underscores and dots
        name = name.strip("._")

        # Fallback if empty
        if not name:
            name = "project"

        return name

    def createProject(
            self,
            mapper: PostgresqlFlatMapper,
            projectData: ProjectCreate,
            currentUser,
    ) -> dict:
        # Sanitize incoming name for filesystem usage
        originalName = projectData.name
        sanitizedName = self.sanitizeProjectName(originalName)

        projectData.name = sanitizedName

        existingProjects = mapper.listProjects(ownerId=currentUser["id"])
        if any(p["name"] == sanitizedName for p in existingProjects):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                        "A project with this name already exists for the current user "
                        "(sanitized name: '%s')" % sanitizedName
                ),
            )

        scipionPath = self.manager.getProjectPath(sanitizedName)
        if os.path.exists(scipionPath):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                        "A project with this name already exists in the file system "
                        "(sanitized name: '%s')" % sanitizedName
                ),
            )

        proj = self.manager.createProject(sanitizedName)
        proj.setComment(projectData.description or "")

        dbProjectId = mapper.insertProject(
            ownerId=currentUser["id"],
            name=scipionPath,
            description=projectData.description,
            status=projectData.status,
        )

        return {
            "id": dbProjectId,
            "name": sanitizedName,
            "description": projectData.description,
            "createdAt": datetime.utcnow(),
            "status": projectData.status,
            "protocolsCount": 0,
            "diskUsage": f"{0.0} GB",
            "isOwner": True,
            "isShared": False,
            "permission": "full",
            "projectOwnerId": currentUser["id"],
            "thumbnailUrl": self.buildProjectThumbnailUrl(dbProjectId),
            "thumbnailRebuildUrl": self.buildProjectThumbnailRebuildUrl(dbProjectId),
            "thumbnailItemsUrl": self.buildProjectThumbnailItemsUrl(dbProjectId),
        }

    def _normalizeProjectPath(self, projectPath: str) -> str:
        """
        Normalize a stored project path to an absolute filesystem path.

        Important:
        - Do NOT resolve symlinks here.
        - We want the project entry path, not the real target path.
        """
        if not projectPath:
            return ""

        normalized = os.path.expanduser(str(projectPath).strip())

        if not os.path.isabs(normalized):
            normalized = self.manager.getProjectPath(normalized)

        return os.path.abspath(normalized)

    def _isManagedProjectPath(self, projectPath: str) -> bool:
        """
        Return True when the project entry iºtself lives under the managed projects root.

        Important:
        - This checks the lexical path of the entry.
        - It must not resolve symlinks, otherwise linked external projects would
          look "outside" even if their symlink entry is inside the workspace.
        """
        try:
            managedRoot = self._normalizeProjectPath(self.manager.PROJECTS)
            normalizedPath = self._normalizeProjectPath(projectPath)

            common = os.path.commonpath([managedRoot, normalizedPath])
            return common == managedRoot
        except Exception:
            return False

    def _isLinkedProjectPath(self, projectPath: str) -> bool:
        """
        Return True if the stored project entry is a symbolic link.
        """
        normalizedPath = self._normalizeProjectPath(projectPath)
        return os.path.islink(normalizedPath)

    def _validateImportableScipionProject(self, sourcePath: Path) -> Dict[str, Any]:
        """
        Validate that a folder is a real Scipion project by trying to load it.

        Returns a small metadata dict that can be reused by importProject.
        """
        if sourcePath is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid source project path",
            )

        if not sourcePath.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source project path does not exist",
            )

        if not sourcePath.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source project path must be a directory",
            )

        try:
            importedProject = ScipionProject(
                pyworkflow.Config.getDomain(),
                str(sourcePath),
            )
            importedProject.load(dbPath=importedProject.getDbPath())
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source path is not a valid Scipion project: {e}",
            )

        try:
            description = importedProject.getComment() or ""
        except Exception:
            description = ""

        try:
            statusValue = str(importedProject.getStatus()) if importedProject.getStatus() else "active"
        except Exception:
            statusValue = "active"

        return {
            "description": description,
            "status": statusValue or "active",
        }

    def _shouldRegisterProtocolOutputs(self, protocol: Any) -> bool:
        try:
            outputs = list(protocol.iterOutputAttributes())
        except Exception:
            return False

        if not outputs:
            return False

        status = protocol.getStatus()

        return status == STATUS_FINISHED

    def _safeCall(self, obj: Any, methodName: str, default: Any = None) -> Any:
        try:
            method = getattr(obj, methodName, None)
            if method is None:
                return default
            return method()
        except Exception:
            return default

    def _getScipionClassName(self, obj: Any) -> Optional[str]:
        if obj is None:
            return None

        className = self._safeCall(obj, "getClassName", None)
        if className:
            return str(className)

        return obj.__class__.__name__

    def _getScipionObjectId(self, obj: Any) -> Optional[Any]:
        return self._safeCall(obj, "getObjId", None)

    def _isPersistableNonSetOutput(self, outputObj: Any) -> bool:
        if outputObj is None:
            return False

        if self._isScipionSetLikeOutput(outputObj):
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

    def _isScipionSetLikeOutput(self, outputObj: Any) -> bool:
        if outputObj is None:
            return False

        try:
            if isinstance(outputObj, ScipionSet):
                return True
        except Exception:
            pass

        className = self._getScipionClassName(outputObj) or outputObj.__class__.__name__
        classNameText = str(className or "")

        if classNameText.startswith("SetOf") or "SetOf" in classNameText:
            return True

        return (
                callable(getattr(outputObj, "iterItems", None))
                and callable(getattr(outputObj, "getSize", None))
                and callable(getattr(outputObj, "getFileName", None))
        )

    def _iterProtocolInputPointers(self, pointer: Any) -> List[Any]:
        if pointer is None:
            return []

        if isinstance(pointer, (list, tuple, set)):
            return list(pointer)

        try:
            if not isinstance(pointer, (str, bytes, dict)):
                items = list(pointer)
                if items:
                    return items
        except Exception:
            pass

        return [pointer]

    def _getPointerTargetObject(self, pointer: Any) -> Any:
        if pointer is None:
            return None

        target = self._safeCall(pointer, "get", None)
        if target is not None:
            return target

        return pointer

    def _getPointerParentProtocolId(self, pointer: Any, targetObj: Any) -> Optional[Any]:
        pointerObj = self._safeCall(pointer, "getObjValue", None)
        parentProtocolId = self._safeCall(pointerObj, "getObjId", None)
        if parentProtocolId is not None:
            return parentProtocolId

        parentObj = self._safeCall(targetObj, "getObjParent", None)
        parentProtocolId = self._safeCall(parentObj, "getObjId", None)
        if parentProtocolId is not None:
            return parentProtocolId

        return None

    # ------------------------------------------------------------------
    # Scipion runtime protocol resolution
    # ------------------------------------------------------------------
    def _resolveScipionProtocolId(
            self,
            mapper,
            projectId: Optional[int],
            protocolId: Union[int, str],
    ) -> int:
        rawProtocolId = str(protocolId).strip()

        if not rawProtocolId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing protocol id",
            )

        if mapper is None or projectId is None:
            try:
                return int(rawProtocolId)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid Scipion protocol id: {protocolId}",
                )

        protocolDbIdCandidate = None
        try:
            protocolDbIdCandidate = int(rawProtocolId)
        except Exception:
            protocolDbIdCandidate = None

        try:
            if protocolDbIdCandidate is not None:
                row = mapper.db.fetchOne(
                    """
                    SELECT "protocolId"
                      FROM protocols
                     WHERE "projectId" = %s
                       AND (id = %s OR "protocolId" = %s)
                     LIMIT 1
                    """,
                    (projectId, protocolDbIdCandidate, rawProtocolId),
                )
            else:
                row = mapper.db.fetchOne(
                    """
                    SELECT "protocolId"
                      FROM protocols
                     WHERE "projectId" = %s
                       AND "protocolId" = %s
                     LIMIT 1
                    """,
                    (projectId, rawProtocolId),
                )

            if row:
                value = row.get("protocolId") if isinstance(row, dict) else row[0]
                if value is not None:
                    return int(value)

        except HTTPException:
            raise
        except Exception:
            logger.exception(
                "Failed to resolve Scipion protocol id from PostgreSQL. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )

        try:
            return int(rawProtocolId)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol not found in PostgreSQL: {protocolId}",
            )


    def _getScipionProtocolByRuntimeId(
            self,
            protocolId: Union[int, str],
    ):
        if self.currentProject is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No current Scipion project loaded",
            )

        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(
                "Failed to load protocol from currentProject. "
                "protocolId=%s currentProject=%s mapper=%s",
                protocolId,
                type(self.currentProject),
                type(getattr(self.currentProject, "mapper", None)),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol not found in Scipion runtime: {protocolId}. {e}",
            )

        if protocol is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol not found in Scipion runtime: {protocolId}",
            )

        return protocol

    def _tryGetScipionProtocolByRuntimeId(
            self,
            protocolId: Union[int, str],
    ):
        try:
            return self._getScipionProtocolByRuntimeId(protocolId)
        except Exception:
            return None

    def _getScipionProtocolForRuntime(
            self,
            mapper,
            projectId: Optional[int],
            protocolId: Union[int, str],
    ):
        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        return self._getScipionProtocolByRuntimeId(scipionProtocolId)

    def _tryGetScipionProtocolForRuntime(
            self,
            mapper,
            projectId: Optional[int],
            protocolId: Union[int, str],
    ):
        try:
            return self._getScipionProtocolForRuntime(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
        except Exception:
            return None

    def _resolvePostgresqlProtocolDbId(
            self,
            mapper,
            projectId: Optional[int],
            protocolId: Union[int, str],
    ) -> Optional[int]:
        if mapper is None or projectId is None or protocolId is None:
            return None

        rawProtocolId = str(protocolId).strip()
        if not rawProtocolId:
            return None

        protocolDbIdCandidate = None
        try:
            protocolDbIdCandidate = int(rawProtocolId)
        except Exception:
            protocolDbIdCandidate = None

        try:
            if protocolDbIdCandidate is not None:
                row = mapper.db.fetchOne(
                    """
                    SELECT id
                      FROM protocols
                     WHERE "projectId" = %s
                       AND (id = %s OR "protocolId" = %s)
                     LIMIT 1
                    """,
                    (projectId, protocolDbIdCandidate, rawProtocolId),
                )
            else:
                row = mapper.db.fetchOne(
                    """
                    SELECT id
                      FROM protocols
                     WHERE "projectId" = %s
                       AND "protocolId" = %s
                     LIMIT 1
                    """,
                    (projectId, rawProtocolId),
                )

            if row:
                value = row.get("id") if isinstance(row, dict) else row[0]
                if value is not None:
                    return int(value)

        except Exception:
            logger.exception(
                "Failed to resolve PostgreSQL protocol id. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )

        return None

    def _resolveProtocolDbIdForOutputPersistence(
            self,
            db,
            projectId: int,
            protocol: Any,
    ) -> Optional[int]:
        protocolId = self._getScipionObjectId(protocol)
        if protocolId is None:
            return None

        try:
            row = db.fetchOne(
                """
                SELECT id
                  FROM protocols
                 WHERE "projectId" = %s
                   AND "protocolId" = %s
                 LIMIT 1
                """,
                (projectId, str(protocolId)),
            )
        except Exception:
            logger.exception(
                "Failed to resolve protocol db id for output persistence. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )
            return None

        if not row:
            return None

        value = row.get("id") if isinstance(row, dict) else row[0]
        if value is None:
            return None

        try:
            return int(value)
        except Exception:
            return None

    def _raisePostgresqlViewerUnavailable(
            self,
            viewerName: str,
            projectId: int,
            protocolId: Union[int, str],
            outputName: str,
            reason: Optional[str] = None,
            **extra,
    ) -> None:
        extraText = " ".join(
            "%s=%s" % (key, value)
            for key, value in extra.items()
            if value is not None
        )

        logger.warning(
            "%s output is not available in PostgreSQL metadata. projectId=%s protocolId=%s outputName=%s reason=%s %s",
            viewerName,
            projectId,
            protocolId,
            outputName,
            reason,
            extraText,
        )

        detail = "%s output is not available in PostgreSQL metadata" % viewerName
        if reason:
            detail = "%s: %s" % (detail, reason)

        raise HTTPException(
            status_code=404,
            detail=detail,
        )

    def _resolvePostgresqlReaderProtocolId(
            self,
            mapper,
            projectId: Optional[int],
            protocolId: Union[int, str],
    ) -> Union[int, str]:
        if mapper is None:
            return protocolId

        return self._resolvePostgresqlProtocolDbId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        ) or protocolId

    def _storeGeneratedSetInPostgresql(
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

            protocolDbId = self._resolvePostgresqlProtocolDbId(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            ) or protocolId

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
            mapper: PostgresqlFlatMapper,
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

        protocolId = self._getScipionObjectId(protocol)
        protocolDbId = self._resolveProtocolDbIdForOutputPersistence(
            mapper.db,
            projectId,
            protocol,
        )

        if protocolDbId is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol not found in PostgreSQL: {protocolId}",
            )

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
                outputName = self._safeCall(outputItem, "getName", None)
                outputObj = outputItem

            outputName = str(outputName or "").strip()
            outputClassName = self._getScipionClassName(outputObj) or ""

            if not outputName:
                skippedOutputs.append({
                    "outputName": outputName,
                    "outputClassName": outputClassName,
                    "reason": "empty_output_name",
                })
                continue

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
                if self._isScipionSetLikeOutput(outputObj):
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

                elif self._isPersistableNonSetOutput(outputObj):
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

        report = {
            "declared": declaredOutputs,
            "persisted": persistedOutputs,
            "skipped": skippedOutputs,
            "errors": outputErrors,
        }

        return report if returnReport else persistedOutputs

    def _deletePersistedProtocolOutputsFromPostgresql(
            self,
            mapper,
            projectId: int,
            protocolId: Union[int, str],
            protocol: Any = None,
    ) -> Dict[str, Any]:
        protocolDbId = self._resolvePostgresqlProtocolDbId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

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

        outputFiles = self._collectPersistedProtocolOutputFilesFromPostgresql(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
        )

        fileCleanup = self._deletePersistedProtocolOutputFilesFromFilesystem(
            protocol=protocol,
            rawFileNames=outputFiles,
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

    def _collectPersistedProtocolOutputFilesFromPostgresql(
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

    def _deletePersistedProtocolOutputFilesFromFilesystem(
            self,
            protocol: Any,
            rawFileNames: List[str],
    ) -> Dict[str, Any]:
        projectPath = self._getCurrentProjectPath()

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
            resolvedPath = self._resolvePersistedOutputFileForDeletion(
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

    def _resolvePersistedOutputFileForDeletion(
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

    def _deletePersistedProtocolOutputsForRuntimeProtocolsFromPostgresql(
            self,
            mapper,
            projectId: int,
            protocols: List[Any],
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

            cleanupInfo = self._deletePersistedProtocolOutputsFromPostgresql(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                protocol=protocol,
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

    def _getPointerOutputName(self, pointer: Any) -> Optional[str]:
        outputName = self._safeCall(pointer, "getExtended", None)
        if outputName is None:
            return None

        outputNameText = str(outputName).strip()
        return outputNameText or None

    def _buildProtocolInputRefsForPostgresql(
            self,
            projectId: int,
            protocol: Any,
            protocolDbIdByScipionId: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        protocolId = self._getScipionObjectId(protocol)
        if protocolId is None:
            return []

        protocolIdText = str(protocolId)
        protocolDbId = protocolDbIdByScipionId.get(protocolIdText)
        if protocolDbId is None:
            return []

        try:
            inputAttributes = list(protocol.iterInputAttributes())
        except Exception:
            return []

        refs: List[Dict[str, Any]] = []

        for inputName, pointer in inputAttributes:
            pointerItems = self._iterProtocolInputPointers(pointer)

            for itemIndex, pointerItem in enumerate(pointerItems):
                targetObj = self._getPointerTargetObject(pointerItem)
                if targetObj is None:
                    continue

                parentProtocolId = self._getPointerParentProtocolId(pointerItem, targetObj)
                parentProtocolIdText = str(parentProtocolId) if parentProtocolId is not None else None
                parentProtocolDbId = (
                    protocolDbIdByScipionId.get(parentProtocolIdText)
                    if parentProtocolIdText is not None
                    else None
                )

                refs.append({
                    "projectId": int(projectId),
                    "protocolDbId": int(protocolDbId),
                    "protocolId": protocolIdText,
                    "inputName": str(inputName),
                    "itemIndex": int(itemIndex),
                    "parentProtocolDbId": parentProtocolDbId,
                    "parentProtocolId": parentProtocolIdText,
                    "parentOutputName": self._getPointerOutputName(pointerItem),
                    "objectClassName": self._getScipionClassName(targetObj),
                    "objectId": str(self._getScipionObjectId(targetObj))
                    if self._getScipionObjectId(targetObj) is not None else None,
                })

        return refs

    def _safeProtocolStepValue(self, value: Any, default=None):
        try:
            if value is None:
                return default

            if hasattr(value, "hasValue") and not value.hasValue():
                return default

            if hasattr(value, "get"):
                try:
                    return value.get(default)
                except TypeError:
                    return value.get()

            return value
        except Exception:
            return default

    def _safeProtocolStepCall(self, step: Any, methodName: str, default=None):
        try:
            method = getattr(step, methodName, None)
            if not callable(method):
                return default
            value = method()
            return value if value is not None else default
        except Exception:
            return default

    def _safeProtocolStepJsonValue(self, value: Any):
        if value in (None, ""):
            return None

        if isinstance(value, (dict, list, tuple)):
            return value

        try:
            return json.loads(str(value))
        except Exception:
            return str(value)

    def _loadProtocolStepsForPostgresql(self, protocol: Any) -> List[Any]:
        for methodName in ("loadSteps", "getSteps"):
            try:
                method = getattr(protocol, methodName, None)
                if not callable(method):
                    continue

                steps = method() or []
                steps = list(steps)
                if steps:
                    return steps
            except Exception:
                logger.debug(
                    "Could not load protocol steps using %s.",
                    methodName,
                    exc_info=True,
                )

        for attrName in ("_steps", "steps"):
            try:
                steps = getattr(protocol, attrName, None)
                if not steps:
                    continue

                if isinstance(steps, dict):
                    steps = list(steps.values())
                else:
                    steps = list(steps)

                if steps:
                    return steps
            except Exception:
                logger.debug(
                    "Could not load protocol steps from attribute %s.",
                    attrName,
                    exc_info=True,
                )

        return []

    def _buildProtocolStepsForPostgresql(self, protocol: Any) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []

        steps = self._loadProtocolStepsForPostgresql(protocol)
        if not steps:
            return result

        for step in steps:
            try:
                stepIndex = self._safeProtocolStepCall(step, "getIndex", None)
                if stepIndex is None:
                    continue

                elapsedSeconds = None
                elapsed = self._safeProtocolStepCall(step, "getElapsedTime", None)
                try:
                    if elapsed is not None:
                        elapsedSeconds = elapsed.total_seconds()
                except Exception:
                    elapsedSeconds = None

                stepName = self._safeProtocolStepValue(
                    getattr(step, "funcName", None),
                    None,
                )

                if not stepName:
                    stepName = self._safeProtocolStepCall(step, "getClassName", "")

                prerequisites = []
                rawPrerequisites = self._safeProtocolStepCall(
                    step,
                    "getPrerequisites",
                    [],
                )

                try:
                    prerequisites = [
                        int(prerequisite)
                        for prerequisite in (rawPrerequisites or [])
                    ]
                except Exception:
                    prerequisites = []

                rawArgs = self._safeProtocolStepValue(
                    getattr(step, "argsStr", None),
                    None,
                )

                needsGpu = self._safeProtocolStepCall(step, "needsGPU", None)
                if needsGpu is None:
                    needsGpu = True

                result.append({
                    "index": int(stepIndex),
                    "name": str(stepName or ""),
                    "status": self._safeProtocolStepCall(step, "getStatus", ""),
                    "prerequisites": prerequisites,
                    "args": self._safeProtocolStepJsonValue(rawArgs),
                    "initTime": self._safeProtocolStepValue(
                        getattr(step, "initTime", None),
                        None,
                    ),
                    "endTime": self._safeProtocolStepValue(
                        getattr(step, "endTime", None),
                        None,
                    ),
                    "elapsedSeconds": elapsedSeconds,
                    "error": self._safeProtocolStepCall(step, "getErrorMessage", None),
                    "interactive": bool(
                        self._safeProtocolStepCall(step, "isInteractive", False)
                    ),
                    "needsGpu": bool(needsGpu),
                    "event": "snapshot",
                })
            except Exception:
                logger.debug(
                    "Could not serialize protocol step for PostgreSQL.",
                    exc_info=True,
                )

        return result

    def _shouldPreservePostgresqlOnlyProtocols(self) -> bool:
        value = os.environ.get("SCIPIONWEB_PRESERVE_POSTGRESQL_ONLY_PROTOCOLS", "1")
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _mergeRuntimeProtocolStatus(self, storedStatus, runtimeStatus):
        storedText = str(storedStatus or "").strip().lower()
        runtimeText = str(runtimeStatus or "").strip().lower()

        if not runtimeText:
            return storedStatus or STATUS_NEW

        # Do not downgrade a protocol that was already launched/running/scheduled
        # just because an early runtime read still reports "new".
        if runtimeText == "new" and storedText in {
            "launched",
            "running",
            "scheduled",
        }:
            return storedStatus

        # Do not overwrite terminal states with non-terminal stale reads.
        if storedText in {"finished", "failed", "aborted", "interactive"}:
            if runtimeText not in {"finished", "failed", "aborted", "interactive"}:
                return storedStatus

        return runtimeStatus

    def syncPostgresqlRuntimeProtocolStatus(
            self,
            mapper,
            projectId: int,
            protocolId,
    ):
        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = self._getScipionProtocolByRuntimeId(scipionProtocolId)

        statusValue = self._safeCall(protocol, "getStatus", None)

        if str(statusValue or "").strip().lower() in ("", "new"):
            existing = mapper.getProjectProtocolByProtocolId(
                projectId=projectId,
                protocolId=scipionProtocolId,
            )
            existingStatus = existing.get("status") if existing else None

            if str(existingStatus or "").strip().lower() in ("launched", "running", "scheduled"):
                statusValue = existingStatus

        mapper.saveProtocol(
            self._buildProtocolContext(projectId, protocol)
        )

        return {
            "protocolId": str(scipionProtocolId),
            "status": statusValue,
        }

    def syncPostgresqlRuntimeProtocolStatusFromRunDb(
            self,
            mapper,
            projectId: int,
            protocolId,
    ) -> dict:
        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = self._getScipionProtocolByRuntimeId(scipionProtocolId)

        projectPath = self.currentProject.getPath()
        runDbPath = protocol.getDbPath()

        if not os.path.isabs(str(runDbPath)):
            workingDir = protocol.getWorkingDir()

            if not os.path.isabs(str(workingDir)):
                workingDir = os.path.join(projectPath, str(workingDir))

            runDbPath = os.path.join(str(workingDir), "logs", "run.db")

        runDbPath = os.path.abspath(str(runDbPath))

        runtimeProtocol = getProtocolFromDb(
            projectPath,
            runDbPath,
            int(scipionProtocolId),
            chdir=False,
        )

        runtimeStatus = runtimeProtocol.getStatus()

        row = mapper.getProjectProtocolByProtocolId(
            projectId=projectId,
            protocolId=scipionProtocolId,
        )

        if not row:
            raise RuntimeError(
                f"PostgreSQL protocol row not found. projectId={projectId} protocolId={scipionProtocolId}"
            )

        mapper.updateProtocol({
            "id": row["id"],
            "status": runtimeStatus,
        })

        return {
            "projectId": projectId,
            "protocolId": str(scipionProtocolId),
            "runDbPath": runDbPath,
            "status": runtimeStatus,
        }

    def syncPostgresqlRuntimeProtocol(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            protocolId,
            registerOutputs: bool = True,
    ) -> Dict[str, Any]:
        """
        Sync one PostgreSQL-runtime protocol from its Scipion runtime database.

        The process launched by Scipion updates logs/run.db and steps.sqlite.
        PostgreSQL must be refreshed from that runtime state, not from the
        legacy project graph.
        """
        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = self._loadProtocolFromRuntimeDb(
            protocolId=scipionProtocolId,
        )

        if protocol is None:
            protocol = self._getScipionProtocolByRuntimeId(scipionProtocolId)

        protocolContext = self._buildProtocolContext(projectId, protocol)

        storedRow = mapper.getProjectProtocolByProtocolId(
            projectId=projectId,
            protocolId=scipionProtocolId,
        )

        storedStatus = storedRow.get("status") if storedRow else None
        runtimeStatus = protocolContext.get("info", {}).get("status")

        protocolContext["info"]["status"] = self._mergeRuntimeProtocolStatus(
            storedStatus=storedStatus,
            runtimeStatus=runtimeStatus,
        )
        protocolDbId = mapper.saveProtocol(protocolContext)

        steps = []
        try:
            steps = self._buildProtocolStepsForPostgresql(protocol)
        except Exception:
            logger.exception(
                "Failed to build PostgreSQL runtime protocol steps. projectId=%s protocolId=%s",
                projectId,
                scipionProtocolId,
            )

        if steps:
            mapper.replaceProtocolSteps(
                projectId=projectId,
                protocolDbId=int(protocolDbId),
                protocolId=int(scipionProtocolId),
                steps=steps,
            )

        outputReport = {
            "declared": [],
            "persisted": [],
            "skipped": [],
            "errors": [],
        }

        shouldRegisterOutputs = (
                registerOutputs
                and self._isRuntimeProtocolTerminal(protocol)
                and self._shouldRegisterProtocolOutputs(protocol)
        )

        if shouldRegisterOutputs:
            try:
                outputReport = self.registerOutput(
                    projectId=projectId,
                    protocol=protocol,
                    mapper=mapper,
                    returnReport=True,
                )
            except Exception:
                logger.exception(
                    "Failed to register PostgreSQL runtime protocol outputs. projectId=%s protocolId=%s",
                    projectId,
                    scipionProtocolId,
                )
                outputReport = {
                    "declared": [],
                    "persisted": [],
                    "skipped": [],
                    "errors": [{
                        "protocolId": str(scipionProtocolId),
                        "error": "Failed to register outputs",
                    }],
                }

        artifactReport = None

        if logger.isEnabledFor(logging.DEBUG):
            try:
                artifactReport = self._buildPostgresqlRuntimeArtifactReport(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=scipionProtocolId,
                    protocol=protocol,
                )

                logger.debug(
                    "PostgreSQL runtime artifact report. projectId=%s protocolId=%s report=%s",
                    projectId,
                    scipionProtocolId,
                    artifactReport,
                )
            except Exception:
                logger.debug(
                    "Could not build PostgreSQL runtime artifact report. projectId=%s protocolId=%s",
                    projectId,
                    scipionProtocolId,
                    exc_info=True,
                )

        return {
            "protocols": 1,
            "dependencies": 0,
            "inputRefs": 0,
            "steps": len(steps or []),
            "stepsProtocols": 1 if steps else 0,
            "stepErrors": [],
            "outputsDeclared": len(outputReport.get("declared") or []),
            "outputs": len(outputReport.get("persisted") or []),
            "outputsMissing": 0,
            "outputsByKind": self._countRuntimeOutputKinds(outputReport.get("persisted") or []),
            "outputMissing": [],
            "outputErrors": outputReport.get("errors") or [],
            "postgresqlRuntimeSync": True,
            "protocolId": str(scipionProtocolId),
            "protocolStatus": self._safeCall(protocol, "getStatus", None),
            "outputsRegistered": bool(outputReport.get("persisted")),
        }

    def _buildPostgresqlRuntimeArtifactReport(
            self,
            mapper,
            projectId: int,
            protocolId,
            protocol=None,
    ) -> Dict[str, Any]:
        """
        Report legacy runtime artifacts still present for one PostgreSQL-runtime protocol.

        This method does not delete anything.

        It classifies:
          - run.db: Scipion runtime protocol database.
          - logs/steps.sqlite: Scipion runtime steps database.
          - output sqlite files: legacy Set mapper files already persisted to PostgreSQL.
          - unknown sqlite files: anything else under the protocol working directory.

        The goal is to understand which files are still produced and which ones may
        become cleanup candidates once PostgreSQL readers no longer depend on them.
        """
        import glob

        def rowToDict(row):
            if row is None:
                return {}

            try:
                return dict(row)
            except Exception:
                result = {}

                try:
                    for key in row.keys():
                        result[key] = row[key]
                except Exception:
                    pass

                return result

        def safeSize(filePath):
            try:
                if filePath and os.path.exists(str(filePath)):
                    return os.path.getsize(str(filePath))
            except Exception:
                pass

            return None

        def normalizePathKey(value):
            text = str(value or "").strip()

            if not text:
                return None

            # Some mapper paths come as "path.sqlite, "
            text = text.strip().strip(",")

            if not text:
                return None

            return text

        def buildPostgresqlViewerReadiness(storedSet):
            if not storedSet:
                return {
                    "ready": False,
                    "reason": "stored_set_not_found",
                }

            setClassName = str(storedSet.get("setClassName") or "")
            itemClassName = str(storedSet.get("itemClassName") or "")
            classText = ("%s %s" % (setClassName, itemClassName)).replace(" ", "").lower()

            itemsCount = None
            properties = storedSet.get("properties") or {}

            if isinstance(properties, dict):
                itemsCount = properties.get("itemsCount") or properties.get("_size")

            try:
                itemsCount = int(itemsCount)
            except Exception:
                itemsCount = None

            setId = storedSet.get("id")
            rootItemsCount = None
            tablesCount = None
            tableItemsCount = None

            try:
                if setId is not None:
                    row = mapper.db.fetchOne(
                        """
                        SELECT COUNT(*) AS count
                          FROM scipion_set_items
                         WHERE "setId" = %s
                        """,
                        (int(setId),),
                    )
                    rootItemsCount = int(row.get("count") or 0) if row else 0
            except Exception:
                rootItemsCount = None

            try:
                if setId is not None:
                    row = mapper.db.fetchOne(
                        """
                        SELECT COUNT(*) AS count
                          FROM scipion_set_tables
                         WHERE "setId" = %s
                        """,
                        (int(setId),),
                    )
                    tablesCount = int(row.get("count") or 0) if row else 0
            except Exception:
                tablesCount = None

            try:
                if setId is not None:
                    row = mapper.db.fetchOne(
                        """
                        SELECT COUNT(ti.id) AS count
                          FROM scipion_set_tables t
                          JOIN scipion_set_table_items ti
                            ON ti."tableId" = t.id
                         WHERE t."setId" = %s
                        """,
                        (int(setId),),
                    )
                    tableItemsCount = int(row.get("count") or 0) if row else 0
            except Exception:
                tableItemsCount = None

            supportedReader = None

            if "tiltseries" in classText and "ctftomo" not in classText:
                supportedReader = "PostgresqlTiltSeriesReader"
            elif "ctftomo" in classText:
                supportedReader = "PostgresqlCtftomoReader"
            elif "coordinates3d" in classText or "coordinate3d" in classText:
                supportedReader = "PostgresqlCoords3dReader"
            elif "tomogram" in classText or "volume" in classText:
                supportedReader = "PostgresqlIntegratedContextReader"

            hasRootItems = rootItemsCount is not None and rootItemsCount > 0
            hasLogicalTables = tablesCount is not None and tablesCount > 0
            hasTableItems = tableItemsCount is not None and tableItemsCount > 0

            ready = bool(
                supportedReader
                and (
                        hasRootItems
                        or hasTableItems
                        or itemsCount is not None
                )
            )

            reason = "postgresql_reader_available" if ready else "postgresql_reader_or_items_missing"

            return {
                "ready": ready,
                "reason": reason,
                "reader": supportedReader,
                "setClassName": setClassName,
                "itemClassName": itemClassName,
                "itemsCount": itemsCount,
                "rootItemsCount": rootItemsCount,
                "tablesCount": tablesCount,
                "tableItemsCount": tableItemsCount,
            }

        def addPersistedSqliteReference(value):
            if not value:
                return

            # _mapperPath may contain comma-separated values.
            for part in str(value).split(","):
                part = normalizePathKey(part)

                if not part:
                    continue

                persistedSqliteReferences.add(part)
                persistedSqliteReferences.add(os.path.basename(part))

                if os.path.isabs(part):
                    persistedSqliteReferences.add(os.path.abspath(part))
                    continue

                # Values like Runs/001175_ProtImportTsMovies/TiltSeriesM.sqlite
                # are project-relative, not workingDir-relative.
                try:
                    if projectPath:
                        persistedSqliteReferences.add(
                            os.path.abspath(os.path.join(str(projectPath), part))
                        )
                except Exception:
                    pass

                # Values like TiltSeriesM.sqlite are workingDir-relative.
                try:
                    if workingDir and not str(part).startswith("Runs/"):
                        persistedSqliteReferences.add(
                            os.path.abspath(os.path.join(str(workingDir), part))
                        )
                except Exception:
                    pass

        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if protocol is None:
            try:
                protocol = self._getScipionProtocolByRuntimeId(scipionProtocolId)
            except Exception:
                protocol = None

        projectPath = self._getCurrentProjectPath()

        workingDir = None
        runDbPath = None

        if protocol is not None:
            try:
                workingDir = protocol.getWorkingDir()
            except Exception:
                workingDir = None

            try:
                runDbPath = protocol.getDbPath()
            except Exception:
                runDbPath = None

        if workingDir and projectPath and not os.path.isabs(str(workingDir)):
            workingDir = os.path.abspath(
                os.path.join(str(projectPath), str(workingDir))
            )

        if runDbPath:
            runDbPath = str(runDbPath)

            if not os.path.isabs(runDbPath):
                if workingDir:
                    runDbPath = os.path.abspath(
                        os.path.join(
                            str(workingDir),
                            "logs",
                            os.path.basename(runDbPath),
                        )
                    )
                elif projectPath:
                    runDbPath = os.path.abspath(
                        os.path.join(str(projectPath), runDbPath)
                    )

        if not runDbPath and workingDir:
            runDbPath = os.path.abspath(
                os.path.join(str(workingDir), "logs", "run.db")
            )

        runDbExists = bool(runDbPath and os.path.exists(str(runDbPath)))

        persistedSetRows = mapper.db.fetchAll(
            """
            SELECT
                s.id,
                s."projectId",
                s."protocolDbId",
                s."objectId",
                s."outputName",
                s."setClassName",
                s."itemClassName",
                s.properties
              FROM scipion_sets s
              JOIN protocols p
                ON p.id = s."protocolDbId"
             WHERE s."projectId" = %s
               AND p."protocolId" = %s
             ORDER BY s."outputName"
            """,
            (projectId, str(scipionProtocolId)),
        )

        persistedObjectRows = mapper.db.fetchAll(
            """
            SELECT
                o.name,
                o.path,
                o."className",
                o."scipionObjId"
              FROM scipion_objects o
              JOIN protocols p
                ON p.id = o."protocolDbId"
             WHERE o."projectId" = %s
               AND p."protocolId" = %s
               AND o."parentObjectId" IS NULL
             ORDER BY o.path, o.name
            """,
            (projectId, str(scipionProtocolId)),
        )

        persistedSets = [rowToDict(row) for row in (persistedSetRows or [])]
        persistedObjects = [rowToDict(row) for row in (persistedObjectRows or [])]

        outputsPersisted = bool(persistedSets or persistedObjects)

        persistedSqliteReferences = set()

        for row in persistedSets:
            properties = row.get("properties") or {}

            if not isinstance(properties, dict):
                continue

            addPersistedSqliteReference(properties.get("fileName"))
            addPersistedSqliteReference(properties.get("_mapperPath"))

        sqliteFiles = []
        runtimeSqlites = []
        outputSqlites = []
        unknownSqlites = []

        if workingDir and os.path.exists(str(workingDir)):
            for filePath in glob.glob(
                    os.path.join(str(workingDir), "**", "*.sqlite"),
                    recursive=True,
            ):
                try:
                    relativePath = os.path.relpath(filePath, str(workingDir))
                except Exception:
                    relativePath = os.path.basename(filePath)

                sqliteItem = {
                    "path": filePath,
                    "relativePath": relativePath,
                    "sizeBytes": safeSize(filePath),
                }

                sqliteFiles.append(sqliteItem)

        viewerReadinessBySqliteRef = {}

        for row in persistedSets:
            properties = row.get("properties") or {}

            if not isinstance(properties, dict):
                continue

            readiness = buildPostgresqlViewerReadiness(row)

            for key in ("fileName", "_mapperPath"):
                value = properties.get(key)

                if not value:
                    continue

                for part in str(value).split(","):
                    part = normalizePathKey(part)

                    if not part:
                        continue

                    refs = {
                        part,
                        os.path.basename(part),
                    }

                    if os.path.isabs(part):
                        refs.add(os.path.abspath(part))
                    else:
                        if projectPath:
                            refs.add(os.path.abspath(os.path.join(str(projectPath), part)))

                        if workingDir and not str(part).startswith("Runs/"):
                            refs.add(os.path.abspath(os.path.join(str(workingDir), part)))

                    for ref in refs:
                        viewerReadinessBySqliteRef[ref] = readiness

        for sqliteItem in sqliteFiles:
            filePath = sqliteItem.get("path") or ""
            relativePath = sqliteItem.get("relativePath") or ""
            basename = os.path.basename(relativePath)

            normalizedFilePath = os.path.abspath(filePath) if filePath else ""
            normalizedRelativePath = normalizePathKey(relativePath)

            isStepsSqlite = normalizedRelativePath == "logs/steps.sqlite"

            isPersistedOutputSqlite = any([
                normalizedFilePath in persistedSqliteReferences,
                normalizedRelativePath in persistedSqliteReferences,
                basename in persistedSqliteReferences,
            ])

            if isStepsSqlite:
                sqliteItem["legacyRole"] = "steps"
                sqliteItem["legacyRequired"] = True
                sqliteItem["cleanupCandidate"] = False
                sqliteItem["safeToDelete"] = False
                sqliteItem["reason"] = (
                    "Scipion runtime may still use steps.sqlite for protocol "
                    "steps, restart and runtime inspection"
                )

                runtimeSqlites.append(sqliteItem)

            elif isPersistedOutputSqlite:
                viewerReadiness = (
                        viewerReadinessBySqliteRef.get(normalizedFilePath)
                        or viewerReadinessBySqliteRef.get(normalizedRelativePath)
                        or viewerReadinessBySqliteRef.get(basename)
                        or {
                            "ready": False,
                            "reason": "viewer_readiness_not_resolved",
                        }
                )

                sqliteItem["legacyRole"] = "output_set"
                sqliteItem["legacyRequired"] = True
                sqliteItem["cleanupCandidate"] = True
                sqliteItem["postgresqlViewerReady"] = bool(viewerReadiness.get("ready"))
                sqliteItem["viewerReadiness"] = viewerReadiness
                sqliteItem["safeToDeleteForViewers"] = bool(viewerReadiness.get("ready"))
                sqliteItem["safeToDeleteForRuntime"] = False
                sqliteItem["safeToDelete"] = False
                sqliteItem["reason"] = (
                    "Output is persisted in PostgreSQL and PostgreSQL viewer readers appear ready, "
                    "but runtime cleanup is still disabled"
                    if viewerReadiness.get("ready")
                    else
                    "Output is persisted in PostgreSQL, but PostgreSQL viewer readiness could not be confirmed"
                )

                outputSqlites.append(sqliteItem)

            else:
                sqliteItem["legacyRole"] = "unknown"
                sqliteItem["legacyRequired"] = True
                sqliteItem["cleanupCandidate"] = False
                sqliteItem["safeToDelete"] = False
                sqliteItem["reason"] = "Unclassified sqlite artifact"

                unknownSqlites.append(sqliteItem)

        outputSqlitesCandidateForCleanup = [
            item
            for item in outputSqlites
            if item.get("cleanupCandidate")
        ]

        return {
            "projectId": int(projectId),
            "protocolId": str(scipionProtocolId),
            "workingDir": str(workingDir) if workingDir else None,

            "runDb": {
                "path": str(runDbPath) if runDbPath else None,
                "exists": runDbExists,
                "sizeBytes": safeSize(runDbPath) if runDbExists else None,
                "legacyRequired": True,
                "cleanupCandidate": False,
                "safeToDelete": False,
                "reason": (
                    "Scipion runtime still loads protocol/status/steps from run.db"
                ),
            },

            "sqliteFiles": sqliteFiles,
            "sqliteFilesCount": len(sqliteFiles),

            "legacyArtifactsByRole": {
                "runtimeSqlites": runtimeSqlites,
                "outputSqlites": outputSqlites,
                "unknownSqlites": unknownSqlites,
            },

            "postgresqlOutputs": {
                "sets": persistedSets,
                "objects": persistedObjects,
                "outputsPersisted": outputsPersisted,
            },

            "persistedSqliteReferences": sorted(persistedSqliteReferences),

            "outputSqlitesCandidateForCleanup": outputSqlitesCandidateForCleanup,

            "safeToDeleteOutputSqlites": False,
            "safeToDeleteRunDb": False,

            "notes": [
                "Do not delete legacy artifacts yet.",
                "run.db is still required by the Scipion runtime path.",
                "steps.sqlite is still considered runtime-owned.",
                "output sqlite files are only cleanup candidates after PostgreSQL readers stop using fileName/_mapperPath.",
            ],
        }

    def _loadProtocolFromRuntimeDb(self, protocolId: int):
        """
        Load the real runtime protocol from logs/run.db.

        This is the source of truth after launch, because the external Scipion
        runner updates that database while the protocol is executing.
        """
        if self.currentProject is None:
            return None

        try:
            protocol = self._getScipionProtocolByRuntimeId(protocolId)
        except Exception:
            protocol = None

        if protocol is None:
            return None

        try:
            runDbPath = protocol.getDbPath()
        except Exception:
            runDbPath = None

        if not runDbPath:
            return protocol

        if not os.path.isabs(str(runDbPath)):
            workingDir = None
            try:
                workingDir = protocol.getWorkingDir()
            except Exception:
                workingDir = None

            if workingDir:
                runDbPath = os.path.abspath(os.path.join(str(workingDir), "logs", os.path.basename(str(runDbPath))))
            else:
                projectPath = self._getCurrentProjectPath()
                runDbPath = os.path.abspath(os.path.join(str(projectPath), str(runDbPath)))

        if not os.path.exists(str(runDbPath)):
            logger.debug(
                "Runtime db does not exist yet. protocolId=%s runDbPath=%s",
                protocolId,
                runDbPath,
            )
            return protocol

        projectPath = self._getCurrentProjectPath()
        if not projectPath:
            return protocol

        try:
            runtimeProtocol = getProtocolFromDb(
                projectPath,
                str(runDbPath),
                int(protocolId),
                chdir=False,
            )

            if runtimeProtocol is not None:
                return runtimeProtocol

        except Exception:
            logger.debug(
                "Could not load protocol from runtime db. protocolId=%s runDbPath=%s",
                protocolId,
                runDbPath,
                exc_info=True,
            )

        return protocol

    def _getCurrentProjectPath(self) -> Optional[str]:
        project = getattr(self, "currentProject", None)
        if project is None:
            return None

        for attrName in ("path", "_path"):
            value = getattr(project, attrName, None)
            if value:
                return str(value)

        try:
            value = project.getPath()
            if value:
                return str(value)
        except Exception:
            pass

        return None

    def _isRuntimeProtocolTerminal(self, protocol) -> bool:
        for methodName in ("isFinished", "isFailed", "isAborted"):
            method = getattr(protocol, methodName, None)
            if callable(method):
                try:
                    if bool(method()):
                        return True
                except Exception:
                    pass

        statusValue = self._safeCall(protocol, "getStatus", None)
        statusText = str(statusValue or "").strip().lower()

        return statusText in {
            "finished",
            "failed",
            "aborted",
            "interactive",
        }

    def _countRuntimeOutputKinds(self, outputs: List[Dict[str, Any]]) -> Dict[str, int]:
        result: Dict[str, int] = {}

        for item in outputs or []:
            mapperKind = str(item.get("mapperKind") or "unknown")
            result[mapperKind] = result.get(mapperKind, 0) + 1

        return result

    def syncProjectProtocolsAndDependencies(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            refresh: bool = False,
            checkPid: bool = False,
    ) -> Dict[str, Any]:
        if self.currentProject is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No current project loaded",
            )

        runs = self.currentProject.getRunsGraph(refresh=refresh, checkPids=checkPid)
        nodesDict = getattr(runs, "_nodesDict", {}) or {}

        protocolDbIdByScipionId: Dict[str, int] = {}
        currentProtocolIds: TypingSet[str] = set()
        protocolsByScipionId: Dict[str, Any] = {}

        outputSyncResults: List[Dict[str, Any]] = []
        outputSyncErrors: List[Dict[str, Any]] = []
        outputSyncDeclared: List[Dict[str, Any]] = []
        outputSyncMissing: List[Dict[str, Any]] = []

        stepsSyncCount = 0
        stepsSyncProtocolsCount = 0
        stepsSyncErrors: List[Dict[str, Any]] = []

        # 1) Save all protocol nodes that are currently present in the real Scipion graph
        for nodeId, nodeObj in nodesDict.items():
            nodeIdText = str(nodeId)
            if nodeIdText == "PROJECT":
                continue

            protocol = getattr(nodeObj, "run", None)
            if protocol is None:
                protocol = self._tryGetScipionProtocolByRuntimeId(nodeId)

            if protocol is None:
                continue

            protocolContext = self._buildProtocolContext(projectId, protocol)
            protocolDbId = mapper.saveProtocol(protocolContext)

            try:
                protocolSteps = self._buildProtocolStepsForPostgresql(protocol)
                protocolScipionId = self._getScipionObjectId(protocol)

                if protocolSteps and protocolScipionId is not None:
                    mapper.replaceProtocolSteps(
                        projectId=projectId,
                        protocolDbId=int(protocolDbId),
                        protocolId=int(protocolScipionId),
                        steps=protocolSteps,
                    )

                    stepsSyncCount += len(protocolSteps)
                    stepsSyncProtocolsCount += 1
            except Exception as exc:
                stepsSyncErrors.append({
                    "protocolId": nodeIdText,
                    "error": str(exc),
                })
                logger.exception(
                    "Failed to sync protocol steps. projectId=%s protocolId=%s",
                    projectId,
                    nodeIdText,
                )

            if self._shouldRegisterProtocolOutputs(protocol):
                try:
                    outputReport = self.registerOutput(
                        projectId=projectId,
                        protocol=protocol,
                        mapper=mapper,
                        returnReport=True,
                    )

                    outputSyncResults.extend(outputReport.get("persisted") or [])
                    declaredOutputs = outputReport.get("declared") or []
                    persistedOutputs = outputReport.get("persisted") or []
                    skippedOutputs = outputReport.get("skipped") or []
                    erroredOutputs = outputReport.get("errors") or []

                    for declaredOutput in declaredOutputs:
                        outputSyncDeclared.append({
                            "protocolId": nodeIdText,
                            "outputName": declaredOutput.get("outputName"),
                            "outputClassName": declaredOutput.get("outputClassName"),
                        })

                    outputSyncMissing.extend(
                        self._buildMissingOutputSyncItems(
                            protocolId=nodeIdText,
                            declaredOutputs=declaredOutputs,
                            persistedOutputs=persistedOutputs,
                            skippedOutputs=skippedOutputs,
                            outputErrors=erroredOutputs,
                        )
                    )

                    for skippedOutput in outputReport.get("skipped") or []:
                        outputSyncErrors.append({
                            "protocolId": nodeIdText,
                            "outputName": skippedOutput.get("outputName"),
                            "outputClassName": skippedOutput.get("outputClassName"),
                            "reason": skippedOutput.get("reason"),
                        })

                    for outputError in outputReport.get("errors") or []:
                        outputSyncErrors.append({
                            "protocolId": nodeIdText,
                            "outputName": outputError.get("outputName"),
                            "outputClassName": outputError.get("outputClassName"),
                            "error": outputError.get("error"),
                        })
                except Exception as exc:
                    outputSyncErrors.append({
                        "protocolId": nodeIdText,
                        "error": str(exc),
                    })
                    logger.exception(
                        "Failed to sync protocol outputs. projectId=%s protocolId=%s",
                        projectId,
                        nodeIdText,
                    )

            currentProtocolIds.add(nodeIdText)
            protocolDbIdByScipionId[nodeIdText] = int(protocolDbId)
            protocolsByScipionId[nodeIdText] = protocol

        # 2) Do not purge PostgreSQL protocol rows while PostgreSQL runtime mapper
        # is active/migrating.
        #
        # PostgreSQL can now contain protocols that do not exist in project.sqlite.
        # If we purge rows based only on the legacy Scipion/SQLite graph, loading or
        # refreshing a project can delete valid PostgreSQL-only protocols.
        purgedProtocols = 0

        if not self._shouldPreservePostgresqlOnlyProtocols():
            purgedProtocols = mapper.deleteProjectProtocolsNotInProtocolIds(
                projectId,
                sorted(currentProtocolIds),
            )

        # 3) Build edges parent -> child using DB ids
        edges: List[Tuple[int, int]] = []

        for nodeId, nodeObj in nodesDict.items():
            childDbId = protocolDbIdByScipionId.get(str(nodeId))
            if not childDbId:
                continue

            for parent in getattr(nodeObj, "_parents", []) or []:
                parentNodeId = str(parent.getName())
                if parentNodeId == "PROJECT":
                    continue

                parentDbId = protocolDbIdByScipionId.get(parentNodeId)
                if not parentDbId:
                    continue

                edges.append((parentDbId, childDbId))

        savedEdges = mapper.replaceProjectProtocolDependencies(projectId, edges)

        inputRefs: List[Dict[str, Any]] = []

        for protocolIdText, protocol in protocolsByScipionId.items():
            inputRefs.extend(
                self._buildProtocolInputRefsForPostgresql(
                    projectId=projectId,
                    protocol=protocol,
                    protocolDbIdByScipionId=protocolDbIdByScipionId,
                )
            )

        savedInputRefs = 0
        replaceInputRefs = getattr(mapper, "replaceProjectProtocolInputRefs", None)
        if callable(replaceInputRefs):
            savedInputRefs = replaceInputRefs(projectId, inputRefs)

        outputResultsByKind: Dict[str, int] = {}
        for item in outputSyncResults:
            mapperKind = str(item.get("mapperKind") or "unknown")
            outputResultsByKind[mapperKind] = outputResultsByKind.get(mapperKind, 0) + 1

        return {
            "protocols": len(protocolDbIdByScipionId),
            "dependencies": int(savedEdges),
            "inputRefs": int(savedInputRefs),
            "steps": int(stepsSyncCount),
            "stepsProtocols": int(stepsSyncProtocolsCount),
            "stepErrors": stepsSyncErrors,
            "outputsDeclared": len(outputSyncDeclared),
            "outputs": len(outputSyncResults),
            "outputsMissing": len(outputSyncMissing),
            "outputsByKind": outputResultsByKind,
            "outputMissing": outputSyncMissing,
            "outputErrors": outputSyncErrors,
            "purgedProtocols": int(purgedProtocols or 0),
        }

    def syncProjectGraphAfterMutation(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            actionLabel: str,
            refresh: bool = True,
            checkPid: bool = True,
    ) -> Dict[str, Any]:
        try:
            return self.syncProjectProtocolsAndDependencies(
                mapper,
                projectId,
                refresh=refresh,
                checkPid=checkPid,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(
                "Failed to sync protocol graph after %s. projectId=%s",
                actionLabel,
                projectId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{actionLabel} succeeded but graph sync to PostgreSQL failed: {e}",
            )

    def importProject(
            self,
            mapper: PostgresqlFlatMapper,
            projectData,
            currentUser,
    ) -> dict:
        rawLocation = (getattr(projectData, "projectLocation", None) or "").strip()
        if not rawLocation:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="projectLocation is required",
            )

        try:
            sourcePath = Path(rawLocation).expanduser().resolve(strict=True)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source project path does not exist",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source project path: {e}",
            )

        if not sourcePath.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source project path must be a directory",
            )

        # Validate that this is a real Scipion project before importing it
        try:
            importedProject = ScipionProject(
                pyworkflow.Config.getDomain(),
                str(sourcePath),
            )
            importedProject.load(dbPath=importedProject.getDbPath())
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source path is not a valid Scipion project: {e}",
            )

        copyProject = bool(getattr(projectData, "copyProject", True))

        requestedName = (getattr(projectData, "projectName", None) or "").strip()
        rawName = requestedName or sourcePath.name
        sanitizedName = self.sanitizeProjectName(rawName)

        existingProjects = mapper.listProjects(ownerId=currentUser["id"]) or []

        existingNames = set()
        existingResolvedPaths = set()

        for proj in existingProjects:
            storedName = str(proj.get("name") or "").strip()
            if not storedName:
                continue

            storedPath = Path(storedName)
            if not storedPath.is_absolute():
                storedPath = Path(self.manager.getProjectPath(storedName))

            existingNames.add(os.path.basename(str(storedPath)))

            try:
                if storedPath.exists():
                    existingResolvedPaths.add(str(storedPath.resolve()))
            except Exception:
                pass

        if sanitizedName in existingNames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A project with this name already exists: '{sanitizedName}'",
            )

        if str(sourcePath) in existingResolvedPaths:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This Scipion project is already imported for the current user",
            )

        targetPath = Path(self.manager.getProjectPath(sanitizedName)).expanduser()

        if targetPath.exists() or targetPath.is_symlink():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target project path already exists: '{targetPath}'",
            )

        try:
            targetResolved = targetPath.resolve(strict=False)
        except Exception:
            targetResolved = targetPath

        if sourcePath == targetPath or sourcePath == targetResolved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source and target project paths cannot be the same",
            )

        targetPath.parent.mkdir(parents=True, exist_ok=True)

        try:
            if copyProject:
                shutil.copytree(str(sourcePath), str(targetPath), symlinks=True)
            else:
                targetPath.symlink_to(sourcePath, target_is_directory=True)
        except Exception as e:
            try:
                if targetPath.is_symlink() or targetPath.exists():
                    if targetPath.is_dir() and not targetPath.is_symlink():
                        shutil.rmtree(targetPath, ignore_errors=True)
                    else:
                        targetPath.unlink(missing_ok=True)
            except Exception:
                pass

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Failed to {'copy' if copyProject else 'link'} project directory: {e}"
                ),
            )

        try:
            description = importedProject.getComment() or ""
        except Exception:
            description = ""

        try:
            importedStatus = importedProject.getStatus()
            statusValue = str(importedStatus) if importedStatus else "active"
        except Exception:
            statusValue = "active"

        storedProjectPath = str(targetPath)

        dbProjectId = mapper.insertProject(
            ownerId=currentUser["id"],
            name=storedProjectPath,
            description=description,
            status=statusValue,
        )

        try:
            self.loadProjectForThumbnails({"name": storedProjectPath})
            self.syncProjectProtocolsAndDependencies(mapper, dbProjectId)
        except Exception as e:
            logger.exception(
                "Failed to sync imported project protocols. projectId=%s path=%s",
                dbProjectId,
                storedProjectPath,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Project was imported but protocols could not be synced to the database: {e}",
            )

        sizePath = sourcePath if not copyProject else targetPath

        try:
            sizeGB = self.getProjectSize(str(sizePath)) / (1024 ** 3)
        except Exception:
            sizeGB = 0.0

        try:
            protCount = self.countProtocols(os.path.join(str(targetPath), "Runs"))
        except Exception:
            protCount = 0

        return {
            "id": dbProjectId,
            "name": sanitizedName,
            "description": description,
            "createdAt": datetime.utcnow(),
            "status": statusValue,
            "protocolsCount": protCount,
            "diskUsage": f"{sizeGB:.2f} GB",
            "isOwner": True,
            "isShared": False,
            "permission": "full",
            "projectOwnerId": currentUser["id"],
            "thumbnailUrl": self.buildProjectThumbnailUrl(dbProjectId),
            "thumbnailRebuildUrl": self.buildProjectThumbnailRebuildUrl(dbProjectId),
            "thumbnailItemsUrl": self.buildProjectThumbnailItemsUrl(dbProjectId),
        }

    def updateProject(self, mapper: PostgresqlFlatMapper, projectId: int, currentUser: dict, projectData: ProjectUpdate):
        dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
        if not dbProj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        currentPath = self._normalizeProjectPath(dbProj["name"])

        if not os.path.lexists(currentPath):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project path not found on disk",
            )

        if not self._isManagedProjectPath(currentPath):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Renaming external imported projects is not supported",
            )

        newName = self.sanitizeProjectName(projectData.name)
        newPath = self._normalizeProjectPath(self.manager.getProjectPath(newName))

        if currentPath != newPath and os.path.lexists(newPath):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A project with this name already exists: '{newName}'",
            )

        try:
            if self._isLinkedProjectPath(currentPath):
                os.rename(currentPath, newPath)
            else:
                self.manager.renameProject(currentPath, newName)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to rename project: {e}",
            )

        description = projectData.description
        if description is None:
            description = dbProj.get("description")

        project = mapper.updateProject(
            projectId,
            currentUser["id"],
            newPath,
            description,
        )

        return project

    def deleteProject(self, mapper: PostgresqlFlatMapper, currentUser, projectId) -> Optional[dict]:
        dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
        if not dbProj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        projectPath = self._normalizeProjectPath(dbProj["name"])
        isManagedEntry = self._isManagedProjectPath(projectPath)
        isLinkedEntry = self._isLinkedProjectPath(projectPath)

        deleted = mapper.deleteProject(projectId, currentUser["id"])
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        if isLinkedEntry:
            try:
                if os.path.lexists(projectPath):
                    os.unlink(projectPath)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Project was unregistered but the symbolic link could not be removed: {e}",
                )

            return {"message": "Linked project unregistered successfully"}

        if not isManagedEntry:
            return {"message": "Project unregistered successfully"}

        if not os.path.exists(projectPath):
            return {"message": "Project deleted successfully"}

        try:
            cwd = self.manager.PROJECTS
            self.manager.deleteProject(projectPath)
            os.chdir(cwd)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Project was unregistered but the managed project folder could not be removed: {e}",
            )

        return {"message": "Project deleted successfully"}

    def _getProjectDisplayNameFromPostgresqlPath(self, storedProjectPath: Any) -> str:
        pathText = str(storedProjectPath or "").strip()
        if not pathText:
            return ""

        return Path(pathText).expanduser().name or pathText

    def _countProjectProtocolsFromPostgresql(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
    ) -> int:
        countProjectProtocols = getattr(mapper, "countProjectProtocols", None)
        if not callable(countProjectProtocols):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PostgreSQL mapper does not expose countProjectProtocols",
            )

        try:
            return int(countProjectProtocols(projectId) or 0)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(
                "Failed to count project protocols from PostgreSQL. projectId=%s",
                projectId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to count project protocols from PostgreSQL: {e}",
            )

    def _getProjectDiskUsageFromFilesystem(self, storedProjectPath: Any) -> str:
        pathText = str(storedProjectPath or "").strip()
        if not pathText:
            return "0.00 GB"

        projectPath = Path(pathText).expanduser()
        if not projectPath.is_absolute():
            projectPath = Path(self.manager.getProjectPath(str(projectPath)))

        try:
            realProjectPath = projectPath.resolve(strict=True)
        except Exception:
            realProjectPath = projectPath

        try:
            sizeGB = self.getProjectSize(str(realProjectPath)) / (1024 ** 3)
        except Exception:
            sizeGB = 0.0

        return f"{sizeGB:.2f} GB"

    def _buildProjectOutFromPostgresqlRow(
            self,
            mapper: PostgresqlFlatMapper,
            dbProj: Dict[str, Any],
            currentUser: dict,
    ) -> Dict[str, Any]:
        projectId = int(dbProj["id"])
        storedProjectPath = dbProj.get("name")
        displayName = self._getProjectDisplayNameFromPostgresqlPath(storedProjectPath)

        protocolsCount = self._countProjectProtocolsFromPostgresql(
            mapper=mapper,
            projectId=projectId,
        )

        currentUserId = currentUser["id"]
        isOwner = dbProj.get("isOwner", dbProj.get("ownerId") == currentUserId)
        isShared = dbProj.get("isShared", False)
        permission = dbProj.get("permission", "owner" if isOwner else "full")
        projectOwnerId = dbProj.get("ownerId")
        updatedAt = dbProj.get("updatedAt")

        thumbnailVersion = "%s:%s:%s:postgresql" % (
            projectId,
            updatedAt or "",
            protocolsCount,
        )

        return {
            "id": projectId,
            "name": displayName,
            "description": dbProj.get("description", ""),
            "createdAt": dbProj.get("createdAt"),
            "status": dbProj.get("status", "active"),
            "protocolsCount": protocolsCount,
            "diskUsage": self._getProjectDiskUsageFromFilesystem(storedProjectPath),
            "isOwner": bool(isOwner),
            "isShared": bool(isShared),
            "permission": permission,
            "projectOwnerId": projectOwnerId,
            "updatedAt": updatedAt,
            "thumbnailUrl": self.buildProjectThumbnailUrl(projectId),
            "thumbnailRebuildUrl": self.buildProjectThumbnailRebuildUrl(projectId),
            "thumbnailItemsUrl": self.buildProjectThumbnailItemsUrl(projectId),
            "thumbnailVersion": thumbnailVersion,
        }

    def getProjectSummaryFromPostgresql(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
    ) -> Optional[dict]:
        """
        Return project metadata from PostgreSQL without loading Scipion runtime.

        This is the cheap read path for project screens that only need project
        metadata. It must not call loadProject(), refresh runs, check PIDs or
        populate currentProject.
        """
        dbProj = mapper.getProject(
            projectId=projectId,
            userId=currentUser["id"],
        )

        if not dbProj:
            return None

        return self._buildProjectOutFromPostgresqlRow(
            mapper=mapper,
            dbProj=dbProj,
            currentUser=currentUser,
        )

    def listProjects(self, mapper: PostgresqlFlatMapper, currentUser) -> List[dict]:
        """
        List all projects visible for the current user using PostgreSQL only.

        This endpoint should not load Scipion projects nor scan project folders.
        It is used by the project list screen, so it must stay cheap even when
        projects contain many runs or large files.
        """
        dbProjects = mapper.listProjects(ownerId=currentUser["id"]) or []

        result = []
        for dbProj in dbProjects:
            if not dbProj.get("name"):
                continue

            result.append(
                self._buildProjectOutFromPostgresqlRow(
                    mapper=mapper,
                    dbProj=dbProj,
                    currentUser=currentUser,
                )
            )

        return result

    def shareProjectWithUser(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
            targetUserIds: list,
            permission: str = "full",
    ) -> dict:
        """
        Share a project owned by currentUser with another user.

        Only the project owner is allowed to call this method.
        """
        # Ensure project exists and is owned by currentUser
        dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
        if not dbProj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found or you are not the owner",
            )

        if targetUserIds == currentUser["id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot share a project with yourself",
            )

        for userId in targetUserIds:
            shareRow = mapper.shareProjectWithUser(
                projectId=projectId,
                targetUserId=int(userId),
                permission=permission or "full",
            )

        return {
            "id": shareRow["id"],
            "projectId": shareRow["projectId"],
            "userId": shareRow["userId"],
            "permission": shareRow["permission"],
            "createdAt": shareRow.get("createdAt"),
            "updatedAt": shareRow.get("updatedAt"),
        }

    def listProjectShares(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
    ) -> List[dict]:
        """
        List users that have access to a project.

        Only the project owner is allowed to call this method.
        """
        dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
        if not dbProj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found or you are not the owner",
            )

        return mapper.listProjectShares(projectId)

    def revokeProjectShareForUser(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            targetUserId: int,
            currentUser: dict,
    ) -> dict:
        """
        Revoke project access for targetUserId.
        Only the project owner is allowed to perform this action.
        """
        # Ensure currentUser has access and get full project row
        dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
        if not dbProj:
            raise HTTPException(status_code=404, detail="Project not found")

        # Ensure current user is the owner
        if int(dbProj["ownerId"]) != int(currentUser["id"]):
            raise HTTPException(status_code=403, detail="Only project owner can revoke shares")

        # Prevent removing owner from a project
        if int(targetUserId) == int(currentUser["id"]):
            raise HTTPException(status_code=400, detail="Owner cannot be removed from the project")

        deleted = mapper.revokeProjectShare(projectId=projectId, userId=targetUserId)
        if not deleted:
            raise HTTPException(status_code=404, detail="Share entry not found")

        return {"success": True}

    def syncActivePostgresqlRuntimeProtocolStatuses(
            self,
            mapper,
            projectId: int,
    ) -> dict:
        """
        Refresh only active PostgreSQL runtime protocol statuses from logs/run.db.

        This is intentionally status-only:
          - no outputs
          - no object persistence
          - no full graph sync
        """
        rows = mapper.db.fetchAll(
            """
            SELECT "protocolId", status
              FROM protocols
             WHERE "projectId" = %s
               AND LOWER(COALESCE(status, '')) IN ('launched', 'running', 'scheduled')
             ORDER BY "protocolId"
            """,
            (projectId,),
        )

        report = {
            "checked": len(rows or []),
            "updated": [],
            "unchanged": [],
            "errors": [],
        }

        for row in rows or []:
            protocolId = row.get("protocolId")
            previousStatus = row.get("status")

            try:
                result = self.syncPostgresqlRuntimeProtocolStatusFromRunDb(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )

                newStatus = result.get("status")

                item = {
                    "protocolId": str(protocolId),
                    "previousStatus": previousStatus,
                    "status": newStatus,
                }

                normalizedNewStatus = str(newStatus or "").strip().lower()

                if normalizedNewStatus in ("finished", "interactive"):
                    try:
                        runtimeSync = self.syncPostgresqlRuntimeProtocol(
                            mapper=mapper,
                            projectId=projectId,
                            protocolId=protocolId,
                            registerOutputs=True,
                        )

                        item["runtimeSync"] = runtimeSync
                        item["outputsRegistered"] = runtimeSync.get("outputs", 0)
                        item["outputsDeclared"] = runtimeSync.get("outputsDeclared", 0)
                        item["outputErrors"] = runtimeSync.get("outputErrors", [])

                    except Exception as e:
                        logger.exception(
                            "Failed to sync PostgreSQL runtime outputs after terminal status. "
                            "projectId=%s protocolId=%s status=%s",
                            projectId,
                            protocolId,
                            newStatus,
                        )

                        item["outputsRegistered"] = 0
                        item["outputSyncError"] = str(e)

                if str(previousStatus or "").strip().lower() != str(newStatus or "").strip().lower():
                    report["updated"].append(item)
                else:
                    report["unchanged"].append(item)

            except Exception as e:
                logger.debug(
                    "Could not refresh PostgreSQL runtime protocol status. projectId=%s protocolId=%s",
                    projectId,
                    protocolId,
                    exc_info=True,
                )
                report["errors"].append({
                    "protocolId": str(protocolId),
                    "error": str(e),
                })

        return report

    def getProjectById(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
            refresh: bool = True,
            checkPid: bool = True,
            validateConsistency: bool = False,
            failOnConsistencyError: bool = False,
            loadWorkflowFromPostgresql: bool = False,
            usePostgresqlRuntimeProject: bool = False,
            usePostgresqlRuntimeWriteFallback: bool = False,
    ) -> Optional[dict]:
        # Retrieve project from PostgreSQL using the mapper
        userId = currentUser["id"]
        dbProj = mapper.getProject(projectId=projectId, userId=userId)
        if not dbProj:
            return None

        projectPath = dbProj["name"]
        if not os.path.exists(projectPath):
            return None

        usingPostgresqlRuntimeProject = self._shouldUsePostgresqlRuntimeProject(
            usePostgresqlRuntimeProject
        )

        postgresqlRuntimeStatusSync = None

        def syncRuntimeStatusesIfNeeded():
            nonlocal postgresqlRuntimeStatusSync

            if not usingPostgresqlRuntimeProject:
                return False

            if not refresh:
                return False

            try:
                postgresqlRuntimeStatusSync = self.syncActivePostgresqlRuntimeProtocolStatuses(
                    mapper=mapper,
                    projectId=projectId,
                )

                if postgresqlRuntimeStatusSync.get("updated"):
                    logger.info(
                        "Refreshed PostgreSQL runtime protocol statuses while loading project. "
                        "projectId=%s report=%s",
                        projectId,
                        postgresqlRuntimeStatusSync,
                    )
                    return True

                return False

            except Exception as e:
                logger.exception(
                    "Failed to refresh PostgreSQL runtime protocol statuses while loading project. "
                    "projectId=%s",
                    projectId,
                )

                postgresqlRuntimeStatusSync = {
                    "checked": 0,
                    "updated": [],
                    "unchanged": [],
                    "errors": [{
                        "error": str(e),
                    }],
                }

                return False

        if loadWorkflowFromPostgresql and not validateConsistency:
            if usingPostgresqlRuntimeProject:
                # We still need to load the real Scipion project first because
                # runtime status comes from Runs/.../logs/run.db, not from PostgreSQL.
                self.loadProject(
                    dbProj,
                    mapper,
                    refresh=refresh,
                    checkPid=checkPid,
                    syncPostgresqlGraph=False,
                )

                self._replaceCurrentProjectWithPostgresqlProject(
                    mapper=mapper,
                    projectId=projectId,
                    enableReadFallback=True,
                    enableWriteFallback=usePostgresqlRuntimeWriteFallback,
                )

                syncRuntimeStatusesIfNeeded()

            # Now load the workflow payload from PostgreSQL after the runtime status refresh.
            project = self.loadProjectFromPostgresql(
                dbProj=dbProj,
                mapper=mapper,
            )

        else:
            project = self.loadProject(
                dbProj,
                mapper,
                refresh=refresh,
                checkPid=checkPid,
                syncPostgresqlGraph=False,
            )

            if usingPostgresqlRuntimeProject:
                self._replaceCurrentProjectWithPostgresqlProject(
                    mapper=mapper,
                    projectId=projectId,
                    enableReadFallback=True,
                    enableWriteFallback=usePostgresqlRuntimeWriteFallback,
                )

                statusChanged = syncRuntimeStatusesIfNeeded()

                if statusChanged:
                    # Return a PostgreSQL payload with the refreshed statuses.
                    project = self.loadProjectFromPostgresql(
                        dbProj=dbProj,
                        mapper=mapper,
                    )

        if validateConsistency:
            try:
                from app.backend.api.services.project_consistency_service import (
                    ProjectConsistencyService,
                )

                consistencyService = ProjectConsistencyService(self)
                project["postgresqlConsistency"] = (
                    consistencyService.validateProjectPostgresqlConsistency(
                        mapper=mapper,
                        projectId=projectId,
                        currentUser=currentUser,
                        refresh=refresh,
                        checkPid=checkPid,
                    )
                )

            except HTTPException:
                if failOnConsistencyError:
                    raise

                logger.exception(
                    "PostgreSQL consistency validation failed. projectId=%s",
                    projectId,
                )

                project["postgresqlConsistency"] = {
                    "ok": False,
                    "error": "PostgreSQL consistency validation failed",
                }

            except Exception as e:
                if failOnConsistencyError:
                    raise

                logger.exception(
                    "PostgreSQL consistency validation failed. projectId=%s",
                    projectId,
                )

                project["postgresqlConsistency"] = {
                    "ok": False,
                    "error": str(e),
                }

        if postgresqlRuntimeStatusSync is not None and isinstance(project, dict):
            project["postgresqlRuntimeStatusSync"] = postgresqlRuntimeStatusSync

        return project

    def getProjectEffectiveSettings(
            self,
            mapper,
            projectId: int,
            currentUser: Any,
    ) -> Dict[str, Any]:
        # getProjectEffectiveSettings
        project = self.getProjectDbRow(mapper, projectId, currentUser)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        settingsService = SettingsService()

        userSettings = None
        instanceSettings = None
        hostSettings = None

        # userSettings
        try:
            userSettings = settingsService.getUserSettings(mapper, currentUser)
            if hasattr(userSettings, "model_dump"):
                userSettings = userSettings.model_dump()
            elif hasattr(userSettings, "dict"):
                userSettings = userSettings.dict()
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error loading user settings for project %s: %s", projectId, e)
            userSettings = None

        # runtimeInstanceSettings
        try:
            instanceSettings = settingsService.getRuntimeInstanceSettings(mapper, currentUser)
        except Exception as e:
            logger.exception("Error loading runtime instance settings for project %s: %s", projectId, e)
            instanceSettings = None

        # runtimeHostSettings
        try:
            hostSettings = settingsService.getRuntimeHostSettings(mapper, currentUser)
        except Exception as e:
            logger.exception("Error loading runtime host settings for project %s: %s", projectId, e)
            hostSettings = None

        return {
            "projectId": projectId,
            "settings": {
                "user": userSettings,
                "instance": instanceSettings,
                "host": hostSettings,
            },
        }

    def getProjectDbRow(self, mapper: PostgresqlFlatMapper, projectId: int, currentUser: dict) -> Optional[dict]:
        dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
        if not dbProj:
            return None

        projectPath = dbProj.get("name")
        if not projectPath:
            return None

        if not os.path.isabs(projectPath):
            projectPath = self.manager.getProjectPath(projectPath)

        if not os.path.exists(projectPath):
            return None

        dbProj = dict(dbProj)
        dbProj["name"] = projectPath
        return dbProj

    def loadProjectForThumbnails(self, dbProj: dict):
        projPath = Path(dbProj["name"])
        self.currentProject = ScipionProject(pyworkflow.Config.getDomain(), str(projPath))
        self.currentProject.load(dbPath=self.currentProject.getDbPath())
        return self.currentProject

    @staticmethod
    def getProjectSize(path: Path) -> int:
        result = subprocess.run(["du", "-sb", path], stdout=subprocess.PIPE, text=True)
        return int(result.stdout.split()[0]) if result.stdout else 0

    @staticmethod
    def countProtocols(path: str) -> int:
        try:
            return sum(1 for entry in Path(path).iterdir() if entry.is_dir())
        except Exception:
            return 0

    @staticmethod
    def _buildProjectThumbnailVersion(
            projectPath: str,
            projectId,
            updatedAt=None,
            protocolsCount: int = 0,
    ) -> str:
        # _buildProjectThumbnailVersion
        runsPath = os.path.join(projectPath, "Runs")

        try:
            runsMtime = int(os.path.getmtime(runsPath)) if os.path.exists(runsPath) else 0
        except Exception:
            runsMtime = 0

        updatedText = str(updatedAt) if updatedAt is not None else ""

        return f"{projectId}:{updatedText}:{protocolsCount}:{runsMtime}"

    def _loadPersistedOutputSummariesByProtocolId(
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

    def _loadPersistedOutputsByProtocolId(
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

    def _formatProtocolElapsedSecondsFromPostgresql(self, value: Any) -> str:
        elapsedSeconds = self._toPersistedOutputFloat(value)
        if elapsedSeconds is None or elapsedSeconds <= 0:
            return ""

        return str(int(elapsedSeconds))

    def buildProtocolsGraph(
            self,
            projectId: int,
            protocolRows: List[Dict[str, Any]],
            tags: Dict[str, List[str]],
            dependencyMap: Optional[Dict[str, Dict[str, List[str]]]] = None,
            runMap: Optional[Dict[str, Any]] = None,
            persistedOutputsByProtocolId: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
            protocolStepSummaryByProtocolId: Optional[Dict[str, Dict[str, Any]]] = None,
            allowRuntimeFallback: bool = True,
    ) -> dict:
        """Assemble protocol graph using PostgreSQL as source of truth for nodes + edges."""
        graphData: Dict[str, Any] = {}
        adjacency = dependencyMap or {}
        liveRuns = runMap or {}
        persistedOutputsByProtocolId = persistedOutputsByProtocolId or {}
        protocolStepSummaryByProtocolId = protocolStepSummaryByProtocolId or {}

        def sortKey(row: Dict[str, Any]):
            raw = str(row.get("protocolId") or "")
            try:
                return (0, int(raw))
            except Exception:
                return (1, raw)

        orderedRows = sorted(protocolRows or [], key=sortKey)

        protocolIds: List[str] = []
        for row in orderedRows:
            rawId = row.get("protocolId")
            if rawId is None:
                continue
            protocolIds.append(str(rawId))

        # Root node synthesized from DB graph:
        # protocols without parents hang directly from PROJECT
        rootChildren = [
            pid for pid in protocolIds
            if not (adjacency.get(pid, {}).get("parents") or [])
        ]

        projectLabel = "PROJECT"
        try:
            if self.currentProject is not None:
                projectLabel = os.path.basename(self.currentProject.getPath()) or "PROJECT"
        except Exception:
            projectLabel = "PROJECT"

        graphData["PROJECT"] = {
            "protocolId": "PROJECT",
            "children": rootChildren,
            "parents": [],
            "label": projectLabel,
            "status": "",
            "parameter": [],
            "inputs": [],
            "outputs": [],
            "cpuTime": "",
            "elapsedTime": "",
            "isInteractive": False,
            "numberOfSteps": 0,
            "stepsDone": 0,
            "tags": [],
            "thumbnailUrl": None,
            "thumbnailRebuildUrl": None,
        }

        for row in orderedRows:
            rawNodeId = row.get("protocolId")
            if rawNodeId is None:
                continue

            nodeId = str(rawNodeId)
            persistedOutputsByName = persistedOutputsByProtocolId.get(nodeId, {})
            stepSummary = protocolStepSummaryByProtocolId.get(nodeId, {}) or {}
            nodeDeps = adjacency.get(nodeId, {"parents": [], "children": []})
            childrenIds = list(nodeDeps.get("children") or [])
            parentIds = list(nodeDeps.get("parents") or [])

            statusValue = row.get("status")
            status = str(statusValue) if statusValue is not None else ""

            protocolClassName = str(row.get("protocolClassName") or "")

            params = row.get("params") or {}
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except Exception:
                    params = {}

            if not isinstance(params, dict):
                params = {}

            def getParamValue(*names):
                for name in names:
                    if name not in params:
                        continue

                    value = params.get(name)

                    if isinstance(value, dict):
                        for valueKey in (
                                "value",
                                "editableValue",
                                "default",
                                "objValue",
                                "_value",
                        ):
                            if valueKey in value:
                                value = value.get(valueKey)
                                break

                    if value is None:
                        continue

                    text = str(value).strip()
                    if text and text.lower() not in ("none", "null"):
                        return text

                return ""

            storedRunName = getParamValue(
                "runName",
                "_runName",
            )

            storedTitle = getParamValue(
                "title",
                "_title",
                "objLabel",
                "_objLabel",
            )

            storedComment = getParamValue(
                "_objComment",
                "objComment",
                "comment",
                "_comment",
            )

            label = storedTitle or storedRunName or protocolClassName or nodeId

            inputs = []
            outputs = []
            seenOutputNames = set()

            cpuTime = ''
            elapsedTime = self._formatProtocolElapsedSecondsFromPostgresql(
                stepSummary.get("elapsedSeconds")
            )
            isinteractive = bool(stepSummary.get("isInteractive"))
            numberOfSteps = self._toPersistedOutputInt(
                stepSummary.get("numberOfSteps")
            ) or 0
            stepsDone = self._toPersistedOutputInt(
                stepSummary.get("stepsDone")
            ) or 0
            thumbnailUrl = None
            thumbnailRebuildUrl = None
            runName = storedRunName
            comment = storedComment
            title = storedTitle

            # Prefer the live protocol object coming from runs graph.
            # Runtime fallback is optional so the graph can be built from PostgreSQL only.
            protocol = liveRuns.get(nodeId)

            if protocol is None and allowRuntimeFallback:
                protocol = self._tryGetScipionProtocolByRuntimeId(nodeId)

            if protocol is not None:
                try:
                    runtimeLabel = str(protocol) or ""
                    if runtimeLabel:
                        label = runtimeLabel
                        if not title:
                            title = runtimeLabel
                except Exception:
                    pass

                try:
                    runtimeRunName = protocol.runName.get()
                    if runtimeRunName is None:
                        runtimeRunName = protocol.getRunName()

                    runtimeRunName = str(runtimeRunName or "").strip()
                    if runtimeRunName:
                        runName = runtimeRunName
                except Exception:
                    pass

                try:
                    comment = protocol._objComment
                except Exception:
                    pass

                try:
                    protStatus = protocol.getStatus()
                    if protStatus:
                        status = str(protStatus)
                except Exception:
                    pass

                try:
                    cpuTime = str(protocol.cpuTime)
                except Exception:
                    cpuTime = ""

                try:
                    elapsedTime = str(protocol.getElapsedTime().total_seconds()).split(".")[0]
                except Exception:
                    elapsedTime = ""

                try:
                    isinteractive = bool(protocol.isInteractive())
                except Exception:
                    isinteractive = False

                try:
                    numberOfSteps = protocol.numberOfSteps
                except Exception:
                    numberOfSteps = 0

                try:
                    stepsDone = protocol.stepsDone
                except Exception:
                    stepsDone = 0

                try:
                    self.currentProject._fixProtParamsConfiguration(protocol)
                except Exception:
                    pass

                try:
                    protocolIdInt = int(nodeId)
                    thumbnailUrl = self.buildProtocolThumbnailUrl(projectId, protocolIdInt)
                    thumbnailRebuildUrl = self.buildProtocolThumbnailRebuildUrl(projectId, protocolIdInt)
                except Exception:
                    thumbnailUrl = None
                    thumbnailRebuildUrl = None

                try:
                    for key, attr in protocol.iterInputAttributes():
                        inputItem = {}
                        try:
                            inputItem["name"] = key
                            inputItem["paramClass"] = "PointerParam"
                            inputItem["pointerClass"] = attr.get().getClassName() if attr and attr.get() else ""
                            inputItem["info"] = str(attr.get())
                        except Exception:
                            inputItem["pointerClass"] = ""
                            inputItem["info"] = ""

                        try:
                            parentId = attr.getObjValue().getObjId()
                            inputItem["value"] = "%s.%s" % (str(parentId), attr.getExtended())
                            inputItem["parentId"] = parentId
                        except Exception:
                            inputItem["value"] = ""
                            inputItem["parentId"] = None

                        inputs.append(inputItem)
                except Exception:
                    inputs = []

                try:
                    for key, attr in protocol.iterOutputAttributes():
                        outputName = str(key)
                        seenOutputNames.add(outputName)

                        outputItem = {}
                        outputItem["name"] = key
                        outputItem["paramClass"] = "PointerParam"
                        outputItem["pointerClass"] = attr.__class__.__name__

                        try:
                            outputItem["info"] = attr.__str__()
                        except Exception:
                            outputItem["info"] = ""

                        try:
                            parentId = protocol.getObjId()
                            outputItem["value"] = "%s.%s" % (str(parentId), key)
                            outputItem["parentId"] = parentId
                        except Exception:
                            outputItem["value"] = ""
                            outputItem["parentId"] = None

                        persistedOutput = persistedOutputsByName.get(outputName)
                        outputItem["persisted"] = bool(persistedOutput)
                        outputItem["persistence"] = persistedOutput
                        if not outputItem.get("info") and persistedOutput:
                            outputItem["info"] = persistedOutput.get("info") or ""

                        outputs.append(outputItem)

                except Exception:
                    outputs = []
                    seenOutputNames = set()

            else:
                try:
                    protocolIdInt = int(nodeId)
                    thumbnailUrl = self.buildProtocolThumbnailUrl(projectId, protocolIdInt)
                    thumbnailRebuildUrl = self.buildProtocolThumbnailRebuildUrl(projectId, protocolIdInt)
                except Exception:
                    thumbnailUrl = None
                    thumbnailRebuildUrl = None

            # Add persisted outputs even when there is no runtime protocol object.
            # If runtime already provided the output, only enrich that runtime output above.
            for outputName, persistedOutput in persistedOutputsByName.items():
                if outputName in seenOutputNames:
                    continue

                outputs.append({
                    "name": outputName,
                    "paramClass": "PointerParam",
                    "pointerClass": persistedOutput.get("className") or "",
                    "info": persistedOutput.get("info") or "",
                    "value": "%s.%s" % (nodeId, outputName),
                    "parentId": nodeId,
                    "persisted": True,
                    "persistence": persistedOutput,
                })

            graphData[nodeId] = {
                "protocolId": nodeId,
                "children": childrenIds,
                "parents": parentIds,
                "label": label,
                "title": title,
                "runName": runName,
                "comment": comment,
                "status": status,
                "parameter": [],
                "inputs": inputs,
                "outputs": outputs,
                "cpuTime": cpuTime,
                "elapsedTime": elapsedTime,
                "isInteractive": isinteractive,
                "numberOfSteps": numberOfSteps,
                "stepsDone": stepsDone,
                "tags": tags.get(nodeId, []),
                "thumbnailUrl": thumbnailUrl,
                "thumbnailRebuildUrl": thumbnailRebuildUrl,
            }

        return graphData

    def _loadProjectGraphDataFromPostgresql(
            self,
            mapper: Optional[PostgresqlFlatMapper],
            projectId: int,
    ) -> Dict[str, Any]:
        """
        Load all PostgreSQL-backed data needed to build the project protocol graph.

        This method does not touch Scipion runtime. It only reads PostgreSQL
        protocol rows, dependencies, tags and persisted output summaries.
        """
        tags: Dict[str, List[str]] = {}
        dependencyMap: Dict[str, Dict[str, List[str]]] = {}
        protocolRows: List[Dict[str, Any]] = []
        persistedOutputsByProtocolId: Dict[str, Dict[str, Dict[str, Any]]] = {}
        protocolStepSummaryByProtocolId: Dict[str, Dict[str, Any]] = {}

        if mapper is None:
            return {
                "tags": tags,
                "dependencyMap": dependencyMap,
                "protocolRows": protocolRows,
                "persistedOutputsByProtocolId": persistedOutputsByProtocolId,
                "protocolStepSummaryByProtocolId": protocolStepSummaryByProtocolId,
            }

        try:
            tags = mapper.getProjectProtocolTagIdsByProtocolId(projectId) or {}
        except Exception:
            logger.exception(
                "Failed to load protocol tags from PostgreSQL for project %s",
                projectId,
            )
            tags = {}

        try:
            dependencyMap = mapper.getProjectProtocolAdjacencyMap(projectId) or {}
        except Exception:
            logger.exception(
                "Failed to load protocol dependencies from PostgreSQL for project %s",
                projectId,
            )
            dependencyMap = {}

        try:
            getStepSummary = getattr(
                mapper,
                "getProjectProtocolStepSummaryByProtocolId",
                None,
            )
            if callable(getStepSummary):
                protocolStepSummaryByProtocolId = getStepSummary(projectId) or {}
        except Exception:
            logger.exception(
                "Failed to load protocol step summaries from PostgreSQL for project %s",
                projectId,
            )
            protocolStepSummaryByProtocolId = {}

        try:
            protocolRows = mapper.getProtocols(projectId) or []
        except Exception:
            logger.exception(
                "Failed to load protocol rows from PostgreSQL for project %s",
                projectId,
            )
            protocolRows = []

        try:
            persistedOutputsByProtocolId = self._loadPersistedOutputsByProtocolId(
                mapper,
                projectId,
            ) or {}
        except Exception:
            logger.exception(
                "Failed to load persisted Scipion outputs for graph. projectId=%s",
                projectId,
            )
            persistedOutputsByProtocolId = {}

        return {
            "tags": tags,
            "dependencyMap": dependencyMap,
            "protocolRows": protocolRows,
            "persistedOutputsByProtocolId": persistedOutputsByProtocolId,
            "protocolStepSummaryByProtocolId": protocolStepSummaryByProtocolId,
        }

    def loadProject(
            self,
            dbProj: dict,
            mapper: PostgresqlFlatMapper = None,
            refresh=True,
            checkPid=True,
            syncPostgresqlGraph: bool = True,
    ) -> dict:
        projPath = Path(dbProj['name'])
        self.currentProject = ScipionProject(pyworkflow.Config.getDomain(), str(projPath))
        self.currentProject.load(dbPath=self.currentProject.getDbPath())

        # Refresh Scipion graph and keep a live map of protocol objects
        runMap: Dict[str, Any] = {}
        scipionProtocolCount = 0
        scipionEdgeCount = 0

        liveProtocolStatusById: Dict[str, str] = {}
        activeOutputProtocolIds: TypingSet[str] = set()

        def normalizeStatus(value: Any) -> str:
            return str(value or "").strip().lower()

        activeOutputStatuses = {
            normalizeStatus(STATUS_LAUNCHED),
            normalizeStatus(STATUS_RUNNING),
            normalizeStatus(STATUS_SCHEDULED),
        }

        try:
            runs = self.currentProject.getRunsGraph(refresh=refresh, checkPids=checkPid)
            nodesDict = getattr(runs, "_nodesDict", {}) or {}

            for nodeId, nodeObj in nodesDict.items():
                if str(nodeId) == "PROJECT":
                    continue

                scipionProtocolCount += 1
                protocol = getattr(nodeObj, "run", None)
                runMap[str(nodeId)] = protocol

                if protocol is not None:
                    try:
                        liveStatus = protocol.getStatus()
                        liveProtocolStatusById[str(nodeId)] = normalizeStatus(liveStatus)
                    except Exception:
                        liveStatus = None

                    try:
                        if (
                                normalizeStatus(liveStatus) in activeOutputStatuses
                                and self._shouldRegisterProtocolOutputs(protocol)
                        ):
                            activeOutputProtocolIds.add(str(nodeId))
                    except Exception:
                        pass

                for parent in getattr(nodeObj, "_parents", []) or []:
                    parentNodeId = str(parent.getName())
                    if parentNodeId != "PROJECT":
                        scipionEdgeCount += 1

        except Exception:
            logger.exception(
                "Failed to refresh Scipion runs graph for project %s",
                dbProj['id'],
            )
            runMap = {}
            scipionProtocolCount = 0
            scipionEdgeCount = 0

        pgGraphData = self._loadProjectGraphDataFromPostgresql(
            mapper=mapper,
            projectId=dbProj['id'],
        )

        tags = pgGraphData["tags"]
        dependencyMap = pgGraphData["dependencyMap"]
        protocolRows = pgGraphData["protocolRows"]
        persistedOutputsByProtocolId = pgGraphData["persistedOutputsByProtocolId"]

        if mapper is not None and syncPostgresqlGraph:
            dbProtocolCount = len(protocolRows)
            dbEdgeCount = sum(len(v.get("parents") or []) for v in dependencyMap.values())

            dbStatusByProtocolId = {
                str(row.get("protocolId")): normalizeStatus(row.get("status"))
                for row in protocolRows
                if row.get("protocolId") is not None
            }

            statusChangedProtocolIds = [
                protocolId
                for protocolId, liveStatus in liveProtocolStatusById.items()
                if dbStatusByProtocolId.get(protocolId) != liveStatus
            ]

            shouldResyncGraph = (
                    scipionProtocolCount != dbProtocolCount or
                    scipionEdgeCount != dbEdgeCount or
                    bool(statusChangedProtocolIds) or
                    bool(activeOutputProtocolIds)
            )

            if shouldResyncGraph:
                try:
                    logger.info(
                        "Resyncing protocol graph from Scipion to PostgreSQL. "
                        "projectId=%s scipionProtocols=%s dbProtocols=%s scipionEdges=%s dbEdges=%s",
                        dbProj['id'],
                        scipionProtocolCount,
                        dbProtocolCount,
                        scipionEdgeCount,
                        dbEdgeCount,
                    )

                    self.syncProjectProtocolsAndDependencies(
                        mapper,
                        dbProj['id'],
                        refresh=False,
                        checkPid=False,
                    )

                    pgGraphData = self._loadProjectGraphDataFromPostgresql(
                        mapper=mapper,
                        projectId=dbProj['id'],
                    )

                    tags = pgGraphData["tags"]
                    dependencyMap = pgGraphData["dependencyMap"]
                    protocolRows = pgGraphData["protocolRows"]
                    persistedOutputsByProtocolId = pgGraphData["persistedOutputsByProtocolId"]

                except Exception:
                    logger.exception(
                        "Failed to resync protocol graph during project load for project %s",
                        dbProj['id'],
                    )

        graphData = self.buildProtocolsGraph(
            dbProj['id'],
            protocolRows,
            tags,
            dependencyMap=dependencyMap,
            runMap=runMap,
            persistedOutputsByProtocolId=persistedOutputsByProtocolId,
            protocolStepSummaryByProtocolId=pgGraphData.get("protocolStepSummaryByProtocolId"),
            allowRuntimeFallback=False,
        )

        stats = projPath.stat()
        updatedAt = datetime.fromtimestamp(stats.st_mtime)
        if updatedAt != dbProj['updatedAt']:
            mapper.updateProjectModificationTime(dbProj['id'], dbProj['ownerId'], updatedAt)

        return {
            "id": dbProj['id'],
            "name": dbProj['name'],
            "shortName": os.path.basename(dbProj['name']),
            "createdAt": str(dbProj['createdAt']),
            "status": str(dbProj['status']),
            "path": projPath,
            "protocols": graphData,
            "thumbnailUrl": self.buildProjectThumbnailUrl(dbProj['id']),
            "thumbnailRebuildUrl": self.buildProjectThumbnailRebuildUrl(dbProj['id']),
            "thumbnailItemsUrl": self.buildProjectThumbnailItemsUrl(dbProj['id']),
        }

    def loadProjectFromPostgresql(
            self,
            dbProj: dict,
            mapper: PostgresqlFlatMapper,
    ) -> dict:
        """
        Load a project workflow tree using PostgreSQL only.

        This method must not instantiate ScipionProject, must not load the
        Scipion sqlite project and must not refresh the Scipion runs graph.
        """
        projPath = Path(dbProj['name'])

        pgGraphData = self._loadProjectGraphDataFromPostgresql(
            mapper=mapper,
            projectId=dbProj['id'],
        )

        graphData = self.buildProtocolsGraph(
            dbProj['id'],
            pgGraphData["protocolRows"],
            pgGraphData["tags"],
            dependencyMap=pgGraphData["dependencyMap"],
            runMap={},
            persistedOutputsByProtocolId=pgGraphData["persistedOutputsByProtocolId"],
            protocolStepSummaryByProtocolId=pgGraphData.get("protocolStepSummaryByProtocolId"),
            allowRuntimeFallback=False,
        )

        return {
            "id": dbProj['id'],
            "name": dbProj['name'],
            "shortName": os.path.basename(dbProj['name']),
            "createdAt": str(dbProj['createdAt']),
            "status": str(dbProj['status']),
            "path": projPath,
            "protocols": graphData,
            "thumbnailUrl": self.buildProjectThumbnailUrl(dbProj['id']),
            "thumbnailRebuildUrl": self.buildProjectThumbnailRebuildUrl(dbProj['id']),
            "thumbnailItemsUrl": self.buildProjectThumbnailItemsUrl(dbProj['id']),
        }

    def validateProjectPostgresqlConsistency(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
            refresh: bool = True,
            checkPid: bool = True,
    ) -> Dict[str, Any]:
        from app.backend.api.services.project_consistency_service import ProjectConsistencyService

        return ProjectConsistencyService(self).validateProjectPostgresqlConsistency(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            refresh=refresh,
            checkPid=checkPid,
        )

    def listProjectWorkflows(self, raw: bool = False):
        """
        Return available workflow templates.

        By default this method returns JSON-serializable workflow objects
        with parsed content and a small preview graph for the frontend.

        If raw=True, return the original Template objects. This is useful for
        internal operations such as applyWorkflowToProject, where the selected
        template object needs replaceEnvVariables() and createTemplateFile().
        """
        def getValue(item: Any, key: str, default: Any = None) -> Any:
            if isinstance(item, dict):
                return item.get(key, default)
            return getattr(item, key, default)

        def safeString(value: Any) -> str:
            if value is None:
                return ""
            return str(value)

        def makeWorkflowId(source: Any, name: Any, fallbackIndex: int) -> str:
            sourceText = safeString(source).strip()
            nameText = safeString(name).strip()

            if sourceText and nameText:
                return "%s:%s" % (sourceText, nameText)

            if nameText:
                return nameText

            return str(fallbackIndex)

        def parseWorkflowContent(rawContent: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            if rawContent is None:
                return [], None

            if isinstance(rawContent, list):
                return [item for item in rawContent if isinstance(item, dict)], None

            if isinstance(rawContent, str):
                text = rawContent.strip()
                if not text:
                    return [], None

                text = self._extractWorkflowJsonText(text)

                try:
                    parsed = json.loads(text)
                except Exception as e:
                    return [], "Invalid workflow content JSON: %s" % e

                if isinstance(parsed, list):
                    return [item for item in parsed if isinstance(item, dict)], None

                return [], "Workflow content JSON is not a list."

            return [], "Unsupported workflow content format."

        def normalizeParams(rawParams: Any) -> Any:
            if rawParams is None:
                return None

            if isinstance(rawParams, collections.OrderedDict):
                return dict(rawParams)

            if isinstance(rawParams, dict):
                return rawParams

            try:
                return dict(rawParams)
            except Exception:
                return rawParams

        def iterReferenceValues(value: Any) -> List[Tuple[str, str]]:
            refs: List[Tuple[str, str]] = []

            if isinstance(value, str):
                for match in re.finditer(r"\b(\d+)\.([A-Za-z_][A-Za-z0-9_\.]*)\b", value.strip()):
                    refs.append((match.group(1), match.group(2)))
                return refs

            if isinstance(value, list):
                for item in value:
                    refs.extend(iterReferenceValues(item))
                return refs

            if isinstance(value, dict):
                for item in value.values():
                    refs.extend(iterReferenceValues(item))
                return refs

            return refs

        def buildWorkflowPreviewGraph(protocols: List[Dict[str, Any]]) -> Dict[str, Any]:
            nodeIds: TypingSet[str] = set()
            nodes: List[Dict[str, Any]] = []
            edges: List[Dict[str, Any]] = []

            for index, protocol in enumerate(protocols):
                protocolId = safeString(
                    protocol.get("object.id")
                    or protocol.get("id")
                    or index
                ).strip()

                if not protocolId:
                    protocolId = str(index)

                nodeIds.add(protocolId)

                className = safeString(
                    protocol.get("object.className")
                    or protocol.get("className")
                    or ""
                ).strip()

                label = safeString(
                    protocol.get("object.label")
                    or protocol.get("label")
                    or protocol.get("runName")
                    or className
                    or protocolId
                ).strip()

                comment = safeString(
                    protocol.get("object.comment")
                    or protocol.get("comment")
                    or ""
                ).strip()

                nodes.append(
                    {
                        "id": protocolId,
                        "protocolId": protocolId,
                        "className": className,
                        "label": label,
                        "comment": comment,
                        "runName": protocol.get("runName"),
                        "order": index,
                    }
                )

            edgeSeen: TypingSet[Tuple[str, str, str, str]] = set()

            for index, protocol in enumerate(protocols):
                targetId = safeString(
                    protocol.get("object.id")
                    or protocol.get("id")
                    or index
                ).strip()

                if not targetId:
                    targetId = str(index)

                for paramName, value in protocol.items():
                    if str(paramName).startswith("object."):
                        continue

                    refs = iterReferenceValues(value)

                    for sourceId, outputName in refs:
                        if sourceId not in nodeIds:
                            continue

                        edgeKey = (sourceId, targetId, outputName, str(paramName))
                        if edgeKey in edgeSeen:
                            continue

                        edgeSeen.add(edgeKey)

                        edges.append(
                            {
                                "id": "%s:%s->%s:%s" % (sourceId, outputName, targetId, paramName),
                                "source": sourceId,
                                "target": targetId,
                                "sourceOutput": outputName,
                                "targetParam": str(paramName),
                            }
                        )

            childIds = {edge["target"] for edge in edges}
            rootIds = [node["id"] for node in nodes if node["id"] not in childIds]

            return {
                "nodes": nodes,
                "edges": edges,
                "rootIds": rootIds,
            }

        tempList = TemplateList()
        tempId = None

        if not (tempId is not None and len(tempList.templates) == 1):
            tempList.addPluginTemplates(tempId)

        templates = tempList.sortListByPluginName().templates

        if raw:
            return templates

        workflows: List[Dict[str, Any]] = []
        pluginAvailabilityCache: Dict[str, bool] = {}

        for index, template in enumerate(templates or []):
            try:
                source = getValue(template, "source")
                name = getValue(template, "name")
                description = getValue(template, "description")
                rawContent = getValue(template, "content")
                params = normalizeParams(getValue(template, "params"))
                projectName = getValue(template, "projectName")
                templatePath = getValue(template, "templatePath")
                templateIdValue = getValue(template, "id")

                protocols, parseError = parseWorkflowContent(rawContent)
                previewGraph = buildWorkflowPreviewGraph(protocols)

                requiredPluginNames = []
                missingPluginNames = []

                if isinstance(rawContent, str):
                    requiredPluginNames = self._extractRequiredPluginNamesFromWorkflowText(rawContent)

                if not requiredPluginNames and templatePath:
                    try:
                        templateText = Path(str(templatePath)).expanduser().read_text(encoding="utf-8")
                        requiredPluginNames = self._extractRequiredPluginNamesFromWorkflowText(templateText)
                    except Exception:
                        requiredPluginNames = []

                missingPluginNames = self._getMissingWorkflowPluginNames(
                    requiredPluginNames,
                    availabilityCache=pluginAvailabilityCache,
                )

                workflowId = safeString(templateIdValue).strip()
                if not workflowId:
                    workflowId = makeWorkflowId(source, name, index)

                workflows.append(
                    {
                        "id": workflowId,
                        "source": safeString(source),
                        "name": safeString(name),
                        "description": safeString(description),
                        "params": params,
                        "projectName": projectName,
                        "templatePath": safeString(templatePath),
                        "content": protocols,
                        "parseError": parseError,
                        "protocolsCount": len(protocols),
                        "previewGraph": previewGraph,
                        "requiredPluginNames": requiredPluginNames,
                        "missingPluginNames": missingPluginNames,
                        "canLoad": len(missingPluginNames) == 0,
                        "disabledReason": (
                            "Missing required plugins: %s" % ", ".join(missingPluginNames)
                            if missingPluginNames
                            else ""
                        ),
                    }
                )
            except Exception:
                logger.exception("Failed to normalize workflow template")
                continue

        return workflows

    def applyWorkflowToProject(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            workflowId: Union[int, str],
            currentUser: dict,
    ) -> dict:
        """
        Apply a predefined workflow template to an existing project.
        Returns a JSON-serializable dict suitable for sending to the frontend.
        """
        # 1) Check that the target project exists and is accessible
        project = self.getProjectById(mapper, projectId, currentUser)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {projectId} not found or not accessible",
            )

        # 2) Get available templates/workflows
        templates = self.listProjectWorkflows(raw=True) or []
        if not templates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No workflows are currently available",
            )

        # 3) Find the template by id or name
        workflowIdStr = str(workflowId).strip()
        selectedTemplate: Any = None

        def getTemplateValue(template: Any, key: str, default: Any = None) -> Any:
            if isinstance(template, dict):
                return template.get(key, default)
            return getattr(template, key, default)

        def toCleanString(value: Any) -> str:
            if value is None:
                return ""
            return str(value).strip()

        def buildTemplateCandidateIds(template: Any, fallbackIndex: int) -> TypingSet[str]:
            templateId = toCleanString(getTemplateValue(template, "id"))
            templateName = toCleanString(getTemplateValue(template, "name"))
            templateSource = toCleanString(getTemplateValue(template, "source"))
            templatePath = toCleanString(getTemplateValue(template, "templatePath"))

            candidates: TypingSet[str] = set()

            if templateId:
                candidates.add(templateId)

            if templateName:
                candidates.add(templateName)

            if templateSource and templateName:
                candidates.add("%s:%s" % (templateSource, templateName))

            if templatePath:
                candidates.add(templatePath)

            candidates.add(str(fallbackIndex))

            return candidates

        # 3) Find the template by normalized id, source:name, name or path
        for index, template in enumerate(templates):
            candidateIds = buildTemplateCandidateIds(template, index)

            if workflowIdStr in candidateIds:
                selectedTemplate = template
                break

        if selectedTemplate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow '{workflowIdStr}' not found",
            )

        # 4) Ensure params attribute exists and is an ordered mapping
        if not hasattr(selectedTemplate, "params") or selectedTemplate.params is None:
            selectedTemplate.params = collections.OrderedDict()

        # 5) Materialize the workflow template file
        try:
            selectedTemplate.replaceEnvVariables()
            workflowFile = selectedTemplate.createTemplateFile()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to materialize workflow '{workflowIdStr}': {e}",
            )

        if not workflowFile:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Workflow '{workflowIdStr}' did not generate a valid template file",
            )

        # 6) Apply the workflow to the current project in Scipion
        workflowImportInfo = self._prepareWorkflowFileForImport(workflowFile)
        importWorkflowFile = workflowImportInfo.get("workflowFile") or workflowFile
        cleanupFile = workflowImportInfo.get("cleanupFile")

        try:
            loadResult = self.currentProject.loadProtocols(importWorkflowFile)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to apply workflow '{workflowIdStr}' to project {projectId}: {e}",
            )
        finally:
            if cleanupFile:
                try:
                    os.remove(str(cleanupFile))
                except Exception:
                    logger.debug(
                        "Could not remove temporary workflow import file: %s",
                        cleanupFile,
                        exc_info=True,
                    )

        # 7) Sync protocols + dependencies to PostgreSQL
        try:
            syncInfo = self.syncProjectProtocolsAndDependencies(
                mapper,
                projectId,
                refresh=True,
                checkPid=True,
            )
        except Exception as e:
            logger.exception(
                "Failed to sync workflow-applied project graph. projectId=%s workflowId=%s",
                projectId,
                workflowIdStr,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Workflow was applied but graph sync to PostgreSQL failed: {e}",
            )

        # 8) Return a compact, useful payload for the frontend
        return {
            "status": 0,
            "projectId": projectId,
            "workflowId": workflowIdStr,
            "workflowName": getattr(selectedTemplate, "name", workflowIdStr),
            "workflowFile": str(workflowFile),
            "protocolsCount": syncInfo.get("protocols"),
            "dependenciesCount": syncInfo.get("dependencies"),
            "loadResult": str(loadResult) if loadResult is not None else None,
            "scipionWebWrapped": bool(workflowImportInfo.get("wrapped")),
            "scipionWebMetadata": bool(workflowImportInfo.get("hasScipionWebMetadata")),
            "requiredPluginNames": workflowImportInfo.get("requiredPluginNames") or [],
        }

    @staticmethod
    def getProtocolColor(status: str) -> str:
        """Return hex color based on protocol status."""
        statusColors = {
            "finished": "#D2F5CB",
            "failed": "#F5CCCB",
            "aborted": "#F5CCCB",
            "running": "#FCCE62",
            "saved": "#D9F1FA",
            "launched": "#FCCE62",
            "scheduled": "#918516",
            "new": "#D9F1FA",
        }
        return statusColors.get(status.lower(), "#9e9e9e")

    @staticmethod
    def buildProjectThumbnailUrl(projectId: int) -> str:
        # buildProjectThumbnailUrl
        return f"/projects/{projectId}/thumbnail"

    @staticmethod
    def buildProjectThumbnailRebuildUrl(projectId: int) -> str:
        # buildProjectThumbnailRebuildUrl
        return f"/projects/{projectId}/thumbnail/rebuild"

    @staticmethod
    def buildProjectThumbnailItemsUrl(projectId: int) -> str:
        # buildProjectThumbnailItemsUrl
        return f"/projects/{projectId}/thumbnail-items"

    @staticmethod
    def buildProtocolThumbnailUrl(projectId: int, protocolId: int) -> str:
        # buildProtocolThumbnailUrl
        return f"/projects/{projectId}/protocols/{protocolId}/thumbnail"

    @staticmethod
    def buildProtocolThumbnailRebuildUrl(projectId: int, protocolId: int) -> str:
        # buildProtocolThumbnailRebuildUrl
        return f"/projects/{projectId}/protocols/{protocolId}/thumbnail/rebuild"

    @staticmethod
    def buildProtocolOutputThumbnailUrl(projectId: int, protocolId: int, outputName: str) -> str:
        # buildProtocolOutputThumbnailUrl
        return f"/projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/thumbnail"

    def _getPostgresqlStoredSetForIntegratedContext(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            outputName: str,
    ) -> Optional[Dict[str, Any]]:
        if mapper is None:
            return None

        try:
            from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper

            setMapper = ScipionSetPostgresqlMapper(mapper.db)
            return setMapper.getStoredSet(
                projectId=projectId,
                protocolDbId=protocolId,
                outputName=outputName,
                limit=None,
                offset=0,
            )
        except Exception:
            logger.debug(
                "Could not load PostgreSQL stored set for integrated context. projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
                exc_info=True,
            )
            return None

    def _getPostgresqlIntegratedKind(self, storedSet: Dict[str, Any]) -> Optional[str]:
        classText = "%s %s" % (
            storedSet.get("setClassName") or "",
            storedSet.get("itemClassName") or "",
        )
        classText = classText.replace(" ", "").lower()

        if "setofcoordinates3d" in classText or "coordinate3d" in classText:
            return "coordinates3d"

        if "setofctftomoseries" in classText or "ctftomoseries" in classText:
            return "ctf"

        if "setoftiltseries" in classText or "tiltseries" in classText:
            return "tiltSeries"

        if "setoftomograms" in classText or "tomogram" in classText:
            return "tomogram"

        return None

    def _getPostgresqlStoredSetProperty(
            self,
            storedSet: Dict[str, Any],
            key: str,
            default=None,
    ):
        properties = storedSet.get("properties") or {}

        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except Exception:
                properties = {}

        if isinstance(properties, dict) and key in properties:
            return properties.get(key)

        for item in storedSet.get("setProperties") or []:
            if str(item.get("key")) == str(key):
                return item.get("value")

        return default

    def _buildPostgresqlIntegratedLink(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            storedSet: Dict[str, Any],
            label: Optional[str] = None,
            statusValue: str = "available",
    ) -> Dict[str, Any]:
        return {
            "protocolId": protocolId,
            "outputName": outputName,
            "itemId": storedSet.get("objectId") or storedSet.get("id"),
            "label": label or outputName,
            "status": statusValue,
        }

    def _buildPostgresqlIntegratedSummary(
            self,
            storedSet: Dict[str, Any],
            extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        items = storedSet.get("items") or []
        itemsCount = self._getPostgresqlStoredSetProperty(storedSet, "itemsCount", None)

        if itemsCount is None:
            itemsCount = len(items)

        summary = {
            "objectClass": storedSet.get("setClassName") or storedSet.get("itemClassName"),
            "objectId": storedSet.get("objectId") or storedSet.get("id"),
            "size": itemsCount,
            "fileName": self._getPostgresqlStoredSetProperty(storedSet, "fileName", None),
            "samplingRate": self._getPostgresqlStoredSetProperty(storedSet, "samplingRate", None),
        }

        if extra:
            summary.update(extra)

        return self._safeScipionValue(summary)

    def _firstPostgresqlValueByName(
            self,
            values: Dict[str, Any],
            names: List[str],
    ):
        normalizedNames = {
            str(name).replace("_", "").replace(".", "").replace("-", "").lower()
            for name in names
        }

        for key, value in (values or {}).items():
            normalizedKey = str(key).replace("_", "").replace(".", "").replace("-", "").lower()
            if normalizedKey in normalizedNames:
                return value

        return None

    def _addPostgresqlIntegratedRelation(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            keyValue: Any,
            **values: Any,
    ) -> None:
        key = str(keyValue) if keyValue is not None else ""
        if not key:
            return

        relation = relationsByKey.setdefault(
            key,
            {
                "key": key,
                "label": key,
            },
        )

        for name, value in values.items():
            if value is not None:
                relation[name] = value

    def _addPostgresqlTiltSeriesRelations(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            items: List[Dict[str, Any]],
    ) -> None:
        for index, item in enumerate(items or []):
            tiltSeriesId = item.get("tiltSeriesId") or item.get("id") or index
            label = item.get("label") or str(tiltSeriesId)

            self._addPostgresqlIntegratedRelation(
                relationsByKey,
                tiltSeriesId,
                tiltSeriesId=tiltSeriesId,
                label=label,
            )

    def _addPostgresqlCtftomoRelations(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            items: List[Dict[str, Any]],
    ) -> None:
        for index, item in enumerate(items or []):
            tiltSeriesId = item.get("tiltSeriesId") or item.get("id") or index
            label = item.get("label") or str(tiltSeriesId)

            self._addPostgresqlIntegratedRelation(
                relationsByKey,
                tiltSeriesId,
                ctfSeriesId=tiltSeriesId,
                tiltSeriesId=tiltSeriesId,
                label=label,
            )

    def _addPostgresqlTomogramRelations(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            items: List[Dict[str, Any]],
    ) -> None:
        for index, item in enumerate(items or []):
            tomogramId = (
                    item.get("tomoId")
                    or item.get("tomogramId")
                    or item.get("id")
                    or item.get("label")
                    or index
            )

            label = item.get("label") or item.get("name") or str(tomogramId)
            volumeId = item.get("tomogramVolumeId") or item.get("volumeId") or index

            self._addPostgresqlIntegratedRelation(
                relationsByKey,
                tomogramId,
                tomogramId=tomogramId,
                tomogramVolumeId=volumeId,
                label=label,
            )

    def _addPostgresqlCoordinates3dRelations(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            items: List[Dict[str, Any]],
    ) -> None:
        for index, item in enumerate(items or []):
            tomogramId = (
                    item.get("tomoId")
                    or item.get("tomogramId")
                    or item.get("id")
                    or item.get("label")
                    or index
            )

            label = item.get("label") or item.get("name") or str(tomogramId)
            volumeId = item.get("tomogramVolumeId") or item.get("volumeId") or index

            self._addPostgresqlIntegratedRelation(
                relationsByKey,
                tomogramId,
                coordinatesTomogramId=tomogramId,
                tomogramId=tomogramId,
                tomogramVolumeId=volumeId,
                label=label,
            )

    def _getPostgresqlIntegratedAnalyzeContextIfAvailable(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            outputName: str,
    ) -> Optional[Dict[str, Any]]:
        if mapper is None:
            return None

        try:
            from app.backend.viewers.postgresql_integrated_context_reader import PostgresqlIntegratedContextReader

            readerProtocolId = self._resolvePostgresqlReaderProtocolId(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

            reader = PostgresqlIntegratedContextReader(
                db=mapper.db,
                projectId=projectId,
                protocolId=readerProtocolId,
                outputName=outputName,
            )

            return reader.getContext()
        except Exception:
            logger.debug(
                "Could not build PostgreSQL integrated analyze context. projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
                exc_info=True,
            )
            return None

    def getIntegratedAnalyzeContextService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            mapper=None,
    ) -> Dict[str, Any]:

        pgContext = self._getPostgresqlIntegratedAnalyzeContextIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgContext is not None:
            return pgContext

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Integrated Analyze Context",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason="context_not_available",
            )

        if self.currentProject is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No current project loaded",
            )

        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol {protocolId} not found: {e}",
            )

        outputObj = getattr(protocol, outputName, None)
        if outputObj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Output '{outputName}' not found in protocol {protocolId}",
            )

        def className(obj: Any) -> str:
            try:
                return obj.getClassName()
            except Exception:
                return obj.__class__.__name__ if obj is not None else ""

        def normalizedClassName(obj: Any) -> str:
            return className(obj).replace(" ", "").lower()

        def safeCall(obj: Any, methodName: str, default: Any = None) -> Any:
            try:
                method = getattr(obj, methodName, None)
                if method is None:
                    return default
                return method()
            except Exception:
                return default

        def safeList(value: Any) -> List[Any]:
            if value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                return list(value)
            return [value]

        def firstNonEmpty(*values: Any) -> Optional[Any]:
            for value in values:
                if value is None:
                    continue
                text = str(value)
                if text:
                    return value
            return None

        def getTsIds(obj: Any) -> TypingSet[str]:
            values = safeCall(obj, "getTSIds", [])
            return {str(v) for v in safeList(values) if v is not None and str(v)}

        def getObjId(obj: Any) -> Optional[Any]:
            return safeCall(obj, "getObjId", None)

        def iterItems(obj: Any) -> List[Any]:
            if obj is None:
                return []

            try:
                return list(obj.iterItems())
            except Exception:
                pass

            try:
                return list(obj)
            except Exception:
                return []

        def getItemTsId(item: Any) -> Optional[Any]:
            return firstNonEmpty(
                safeCall(item, "getTsId", None),
                safeCall(item, "getTSId", None),
                safeCall(item, "getTomoId", None),
                safeCall(item, "getTomogramId", None),
            )

        def getItemLabel(item: Any, fallback: Any = None) -> Optional[Any]:
            return firstNonEmpty(
                safeCall(item, "getTsId", None),
                safeCall(item, "getTSId", None),
                safeCall(item, "getObjLabel", None),
                safeCall(item, "getFileName", None),
                fallback,
            )

        def isTiltSeriesSet(obj: Any) -> bool:
            name = normalizedClassName(obj)
            return "setoftiltseries" in name and "setoftiltseriesm" not in name

        def isTomogramSet(obj: Any) -> bool:
            return "setoftomograms" in normalizedClassName(obj)

        def isCoordinates3dSet(obj: Any) -> bool:
            return "setofcoordinates3d" in normalizedClassName(obj)

        def isCtfTomoSeriesSet(obj: Any) -> bool:
            return "setofctftomoseries" in normalizedClassName(obj)

        def getFirstIteratorItem(value: Any) -> Any:
            if value is None:
                return None

            try:
                iterator = value.iterItems() if hasattr(value, "iterItems") else iter(value)
                return next(iterator, None)
            except Exception:
                return None

        def getCoordinates3dTomograms(coordsSet: Any) -> Any:
            for methodName in ("getTomograms", "getVolumes", "getPrecedents"):
                tomograms = safeCall(coordsSet, methodName, None)
                if tomograms is not None and isTomogramSet(tomograms):
                    return tomograms

            for methodName in ("iterTomograms", "iterVolumes"):
                tomogramsIter = safeCall(coordsSet, methodName, None)
                firstTomogram = getFirstIteratorItem(tomogramsIter)
                if firstTomogram is None:
                    continue

                parent = safeCall(firstTomogram, "getObjParent", None)
                if parent is None:
                    parent = getattr(firstTomogram, "_objParent", None)

                if parent is not None and isTomogramSet(parent):
                    return parent

            return None

        def buildLink(
                obj: Any,
                source: Optional[Dict[str, Any]] = None,
                statusValue: str = "available",
                label: Optional[str] = None,
        ) -> Dict[str, Any]:
            source = source or {}
            return {
                "protocolId": source.get("protocolId"),
                "outputName": source.get("outputName"),
                "itemId": getObjId(obj),
                "label": label or source.get("label") or className(obj),
                "status": statusValue,
            }

        def buildSummary(obj: Any, tsIds: Optional[TypingSet[str]] = None) -> Dict[str, Any]:
            summary = {
                "objectClass": className(obj),
                "objectId": getObjId(obj),
                "size": safeCall(obj, "getSize", None),
                "tsIds": sorted(tsIds if tsIds is not None else getTsIds(obj)),
                "samplingRate": safeCall(obj, "getSamplingRate", None),
                "dimensions": safeCall(obj, "getDimensions", safeCall(obj, "getDim", None)),
                "fileName": safeCall(obj, "getFileName", None),
            }

            boxSize = safeCall(obj, "getBoxSize", None)
            if boxSize is not None:
                summary["boxSize"] = boxSize

            ctfCorrected = safeCall(obj, "ctfCorrected", None)
            if ctfCorrected is not None:
                summary["ctfCorrected"] = ctfCorrected

            return self._safeScipionValue(summary)

        def getProtocolInputRefs(protocolObj: Any) -> List[Dict[str, Any]]:
            refs: List[Dict[str, Any]] = []

            for inputName, pointer in protocolObj.iterInputAttributes():
                try:
                    inputObj = pointer.get() if pointer else None
                except Exception:
                    inputObj = None

                if inputObj is None:
                    continue

                try:
                    inputProtocolId = pointer.getObjValue().getObjId()
                except Exception:
                    inputProtocolId = None

                try:
                    inputOutputName = pointer.getExtended()
                except Exception:
                    inputOutputName = None

                refs.append({
                    "name": inputName,
                    "object": inputObj,
                    "protocolId": inputProtocolId,
                    "outputName": inputOutputName,
                    "label": inputName,
                })

            return refs

        def getProtocolInputRefsById(sourceProtocolId: Any) -> List[Dict[str, Any]]:
            if sourceProtocolId is None:
                return []

            try:
                sourceProtocol = self.currentProject.getProtocol(int(sourceProtocolId))
            except Exception:
                return []

            return getProtocolInputRefs(sourceProtocol)

        def getProtocolOutputRefs(protocolObj: Any) -> List[Dict[str, Any]]:
            refs: List[Dict[str, Any]] = []

            for outputAttrName, outputObjRef in protocolObj.iterOutputAttributes():
                if outputObjRef is None:
                    continue

                refs.append({
                    "name": outputAttrName,
                    "object": outputObjRef,
                    "protocolId": safeCall(protocolObj, "getObjId", None),
                    "outputName": outputAttrName,
                    "label": outputAttrName,
                })

            return refs

        inputRefs = getProtocolInputRefs(protocol)
        outputRefs = getProtocolOutputRefs(protocol)
        localRefs = inputRefs + outputRefs

        def findInputRef(predicate, tsIds: Optional[TypingSet[str]] = None) -> Optional[Dict[str, Any]]:
            for ref in inputRefs:
                obj = ref["object"]
                if not predicate(obj):
                    continue

                if tsIds:
                    candidateTsIds = getTsIds(obj)
                    if candidateTsIds and not candidateTsIds.intersection(tsIds):
                        continue

                return ref

            return None

        def findInputRefForObject(
                targetObj: Any,
                refs: List[Dict[str, Any]],
                predicate=None,
        ) -> Optional[Dict[str, Any]]:
            if targetObj is None:
                return None

            targetClass = className(targetObj)
            targetObjId = getObjId(targetObj)
            targetFileName = safeCall(targetObj, "getFileName", None)
            targetTsIds = getTsIds(targetObj)

            for ref in refs:
                obj = ref["object"]

                if predicate is not None and not predicate(obj):
                    continue

                if obj is targetObj:
                    return ref

                objId = getObjId(obj)
                if targetObjId is not None and objId is not None and str(objId) == str(targetObjId):
                    return ref

                fileName = safeCall(obj, "getFileName", None)
                if targetFileName and fileName and str(fileName) == str(targetFileName):
                    return ref

                objTsIds = getTsIds(obj)
                if targetTsIds and objTsIds and targetTsIds == objTsIds:
                    return ref

                if className(obj) != targetClass:
                    continue

            return None

        links = {
            "tiltSeries": None,
            "ctf": None,
            "tomogram": None,
            "coordinates3d": None,
        }
        summaries = {
            "tiltSeries": None,
            "ctf": None,
            "tomogram": None,
            "coordinates3d": None,
        }
        relationObjects = {
            "tiltSeries": None,
            "ctf": None,
            "tomogram": None,
            "coordinates3d": None,
        }
        relationsByKey: Dict[str, Dict[str, Any]] = {}

        def upsertRelation(keyValue: Any, **values: Any) -> None:
            key = str(keyValue) if keyValue is not None else ""
            if not key:
                return

            relation = relationsByKey.setdefault(key, {
                "key": key,
                "label": key,
            })

            for name, value in values.items():
                if value is not None:
                    relation[name] = value

        def addSetRelations(kind: str, obj: Any) -> None:
            items = iterItems(obj)

            if not items:
                for tsId in sorted(getTsIds(obj)):
                    if kind == "tiltSeries":
                        upsertRelation(tsId, tiltSeriesId=tsId, label=tsId)
                    elif kind == "ctf":
                        upsertRelation(tsId, ctfSeriesId=tsId, tiltSeriesId=tsId, label=tsId)
                    elif kind == "tomogram":
                        upsertRelation(tsId, tomogramId=tsId, label=tsId)
                    elif kind == "coordinates3d":
                        upsertRelation(tsId, coordinatesTomogramId=tsId, label=tsId)
                return

            for index, item in enumerate(items):
                tsId = getItemTsId(item)
                objId = getObjId(item)
                key = firstNonEmpty(tsId, objId, index)
                label = getItemLabel(item, key)

                if kind == "tiltSeries":
                    upsertRelation(
                        key,
                        tiltSeriesId=firstNonEmpty(tsId, objId, index),
                        label=label,
                    )
                elif kind == "ctf":
                    upsertRelation(
                        key,
                        ctfSeriesId=firstNonEmpty(tsId, objId, index),
                        tiltSeriesId=tsId,
                        label=label,
                    )
                elif kind == "tomogram":
                    upsertRelation(
                        key,
                        tomogramId=firstNonEmpty(tsId, objId, index),
                        tomogramVolumeId=index,
                        label=label,
                    )
                elif kind == "coordinates3d":
                    upsertRelation(
                        key,
                        coordinatesTomogramId=firstNonEmpty(tsId, objId, index),
                        label=label,
                    )

        rootSource = {
            "protocolId": protocolId,
            "outputName": outputName,
            "label": outputName,
        }

        outputTsIds = getTsIds(outputObj)

        if isCoordinates3dSet(outputObj):
            links["coordinates3d"] = buildLink(outputObj, rootSource)
            summaries["coordinates3d"] = buildSummary(outputObj, outputTsIds)
            relationObjects["coordinates3d"] = outputObj

            tomograms = getCoordinates3dTomograms(outputObj)
            if tomograms is not None:
                tomoTsIds = outputTsIds or getTsIds(tomograms)
                tomogramRef = findInputRefForObject(tomograms, localRefs, isTomogramSet)
                links["tomogram"] = buildLink(tomograms, tomogramRef, statusValue="inferred")
                summaries["tomogram"] = buildSummary(tomograms, tomoTsIds)
                relationObjects["tomogram"] = tomograms
                outputTsIds = tomoTsIds

        elif isTomogramSet(outputObj):
            links["tomogram"] = buildLink(outputObj, rootSource)
            summaries["tomogram"] = buildSummary(outputObj, outputTsIds)
            relationObjects["tomogram"] = outputObj

        elif isCtfTomoSeriesSet(outputObj):
            links["ctf"] = buildLink(outputObj, rootSource)
            summaries["ctf"] = buildSummary(outputObj, outputTsIds)
            relationObjects["ctf"] = outputObj

            tiltSeries = safeCall(outputObj, "getSetOfTiltSeries", None)
            if tiltSeries is not None and isTiltSeriesSet(tiltSeries):
                tiltRef = findInputRefForObject(tiltSeries, localRefs, isTiltSeriesSet)
                links["tiltSeries"] = buildLink(tiltSeries, tiltRef, statusValue="inferred")
                summaries["tiltSeries"] = buildSummary(tiltSeries, outputTsIds)
                relationObjects["tiltSeries"] = tiltSeries

        elif isTiltSeriesSet(outputObj):
            links["tiltSeries"] = buildLink(outputObj, rootSource)
            summaries["tiltSeries"] = buildSummary(outputObj, outputTsIds)
            relationObjects["tiltSeries"] = outputObj

        if outputTsIds and links["ctf"] is None:
            ctfRef = findInputRef(isCtfTomoSeriesSet, outputTsIds)
            if ctfRef is not None:
                ctfSet = ctfRef["object"]
                links["ctf"] = buildLink(ctfSet, ctfRef)
                summaries["ctf"] = buildSummary(ctfSet, outputTsIds)
                relationObjects["ctf"] = ctfSet

                tiltSeries = safeCall(ctfSet, "getSetOfTiltSeries", None)
                if tiltSeries is not None and links["tiltSeries"] is None and isTiltSeriesSet(tiltSeries):
                    ctfInputRefs = getProtocolInputRefsById(ctfRef.get("protocolId"))
                    tiltRef = (
                            findInputRefForObject(tiltSeries, ctfInputRefs, isTiltSeriesSet)
                            or findInputRefForObject(tiltSeries, inputRefs, isTiltSeriesSet)
                    )
                    links["tiltSeries"] = buildLink(tiltSeries, tiltRef, statusValue="inferred")
                    summaries["tiltSeries"] = buildSummary(tiltSeries, outputTsIds)
                    relationObjects["tiltSeries"] = tiltSeries

        if outputTsIds and links["tiltSeries"] is None:
            tiltRef = findInputRef(isTiltSeriesSet, outputTsIds)
            if tiltRef is not None:
                tiltSeries = tiltRef["object"]
                links["tiltSeries"] = buildLink(tiltSeries, tiltRef)
                summaries["tiltSeries"] = buildSummary(tiltSeries, outputTsIds)
                relationObjects["tiltSeries"] = tiltSeries

        addSetRelations("tiltSeries", relationObjects["tiltSeries"])
        addSetRelations("ctf", relationObjects["ctf"])
        addSetRelations("tomogram", relationObjects["tomogram"])

        if relationObjects["tomogram"] is not None:
            addSetRelations("coordinates3d", relationObjects["tomogram"])
        else:
            addSetRelations("coordinates3d", relationObjects["coordinates3d"])

        relations = self._safeScipionValue({
            "items": list(relationsByKey.values()),
        })

        return {
            "root": {
                "projectId": projectId,
                "protocolId": protocolId,
                "outputName": outputName,
                "outputClass": className(outputObj),
            },
            "links": links,
            "summaries": summaries,
            "relations": relations,
        }

    def buildProtocolOutputThumbnail(
            self,
            protocolId: Union[int, str],
            outputName: str,
            force: bool = False,
            size: int = 320,
            mapper=None,
            projectId: Optional[int] = None,
    ) -> Dict[str, Any]:
        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        thumbnailService = ThumbnailService(self.currentProject)
        return thumbnailService.buildProtocolOutputThumbnail(
            protocolId=scipionProtocolId,
            outputName=outputName,
            force=force,
            size=size,
        )

    def listProjectThumbnailItems(
            self,
            projectId: int,
            force: bool = False,
            size: int = 320,
            maxProtocols: int = 12,
            maxOutputsPerProtocol: int = 4,
            inlineImages: bool = False,
            mapper=None,
    ):
        thumbnailService = ThumbnailService(self.currentProject)
        items = thumbnailService.listProtocolThumbnailItems(
            projectId=projectId,
            force=force,
            size=size,
            maxProtocols=maxProtocols,
            maxOutputsPerProtocol=maxOutputsPerProtocol,
            inlineImages=inlineImages,
        )

        if mapper is None:
            return items

        validItems = []

        for group in items or []:
            if not isinstance(group, dict):
                continue

            protocolIdValue = group.get("protocolId")

            try:
                scipionProtocolId = self._resolveScipionProtocolId(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolIdValue,
                )
                protocol = self.currentProject.getProtocol(int(scipionProtocolId))
            except Exception:
                logger.warning(
                    "Skipping thumbnail group because protocol was not found. "
                    "projectId=%s protocolId=%s group=%s",
                    projectId,
                    protocolIdValue,
                    group,
                )
                continue

            validOutputs = []

            for output in group.get("outputs") or []:
                if not isinstance(output, dict):
                    continue

                outputNameValue = output.get("outputName")
                if not outputNameValue:
                    continue

                if not hasattr(protocol, str(outputNameValue)):
                    logger.warning(
                        "Skipping thumbnail output because it does not belong to protocol. "
                        "projectId=%s protocolId=%s outputName=%s",
                        projectId,
                        protocolIdValue,
                        outputNameValue,
                    )
                    continue

                validOutputs.append(output)

            if not validOutputs:
                continue

            nextGroup = dict(group)
            nextGroup["outputs"] = validOutputs
            validItems.append(nextGroup)

        return validItems

    def _buildMissingOutputSyncItems(
            self,
            protocolId: Union[int, str],
            declaredOutputs: List[Dict[str, Any]],
            persistedOutputs: List[Dict[str, Any]],
            skippedOutputs: List[Dict[str, Any]],
            outputErrors: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        persistedByName = {
            str(item.get("outputName") or ""): item
            for item in persistedOutputs or []
            if item.get("outputName") is not None
        }

        skippedByName = {
            str(item.get("outputName") or ""): item
            for item in skippedOutputs or []
            if item.get("outputName") is not None
        }

        errorsByName = {
            str(item.get("outputName") or ""): item
            for item in outputErrors or []
            if item.get("outputName") is not None
        }

        missingOutputs: List[Dict[str, Any]] = []

        for declaredOutput in declaredOutputs or []:
            outputName = str(declaredOutput.get("outputName") or "")
            if not outputName or outputName in persistedByName:
                continue

            missingItem = {
                "protocolId": str(protocolId),
                "outputName": outputName,
                "outputClassName": declaredOutput.get("outputClassName"),
            }

            skippedOutput = skippedByName.get(outputName)
            outputError = errorsByName.get(outputName)

            if skippedOutput is not None:
                missingItem["reason"] = skippedOutput.get("reason") or "skipped"
            elif outputError is not None:
                missingItem["reason"] = "persistence_error"
                missingItem["error"] = outputError.get("error")
            else:
                missingItem["reason"] = "not_persisted"

            missingOutputs.append(missingItem)

        return missingOutputs

    def _resolveProtocolDbIdForOutputPersistence(self, db, projectId: int, protocol: Any) -> int:
        scipionProtocolId = self._getScipionObjId(protocol)
        if scipionProtocolId is None:
            raise ValueError("Cannot persist Scipion outputs without protocol getObjId()/getId()")

        row = db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (projectId, str(scipionProtocolId)),
        )
        if row is not None:
            return int(row["id"])

        row = db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE id = %s
               AND "projectId" = %s
            """,
            (scipionProtocolId, projectId),
        )
        if row is not None:
            return int(row["id"])

        raise ValueError(
            "Protocol %s was not found in PostgreSQL protocols table for project %s"
            % (scipionProtocolId, projectId)
        )

    def _isScipionSetOutput(self, outputObj: Any) -> bool:
        className = self._getOutputClassName(outputObj)

        if className.startswith("SetOf"):
            return True

        iterItems = getattr(outputObj, "iterItems", None)
        if callable(iterItems):
            return True

        return False

    def _isScipionObjectOutput(self, outputObj: Any) -> bool:
        if outputObj is None:
            return False

        getClassName = getattr(outputObj, "getClassName", None)
        if callable(getClassName):
            return True

        getAttributesToStore = getattr(outputObj, "getAttributesToStore", None)
        if callable(getAttributesToStore):
            return True

        return False

    def _getOutputClassName(self, outputObj: Any) -> str:
        getClassName = getattr(outputObj, "getClassName", None)
        if callable(getClassName):
            try:
                className = getClassName()
                if className:
                    return str(className)
            except Exception:
                pass

        return outputObj.__class__.__name__ if outputObj is not None else ""

    def _getScipionObjId(self, obj: Any) -> Optional[int]:
        for getterName in ("getObjId", "getId"):
            getter = getattr(obj, getterName, None)
            if not callable(getter):
                continue

            try:
                value = getter()
            except Exception:
                continue

            if value is None:
                continue

            try:
                return int(value)
            except Exception:
                continue

        return None

    def _buildProtocolContext(self, projectId, protocol) -> dict:
        """
        Build the common context dictionary for a protocol,
        including inputs, outputs, definition, status, color, logos, etc.
        """
        from pyworkflow.protocol import Line, Group

        def attachContainerWizardMetadata(container: Optional[Dict[str, Any]]) -> None:
            if not container:
                return

            wizardItems: List[Dict[str, Any]] = []
            for child in container.get("params", []) or []:
                childWizards = child.get("wizards") or []
                for wiz in childWizards:
                    if not any(existing.get("id") == wiz.get("id") for existing in wizardItems):
                        wizardItems.append(copy.deepcopy(wiz))

            container["hasWizard"] = bool(wizardItems)
            container["wizards"] = wizardItems
            container["wizard"] = wizardItems[0] if wizardItems else None

        headerParams = ['runName', '_objComment', '_useQueue', '_prerequisites', 'gpuList', 'numberOfThreads', 'numberOfMpi']
        package = protocol.getClassPackage()
        hasExpert = protocol.hasExpert()
        if hasExpert:
            headerParams.append('expertLevel')

        logoPath = ''
        path = getattr(package, '_logo', '')
        if path != '':
            logoPath = self.getResourceLogo(path)

        protName = str(protocol)

        if protocol.runName.get() is None:
            runName = protocol.getRunName()
        else:
            runName = protocol.runName.get()
        status = protocol.getStatus()
        protocolClassName = protocol.getClassName()
        hosts = self.currentProject.getHostNames()

        context = {}
        info = {
            "protocolId": protocol.getObjId(),
            "label": protName,
            "runName": runName,
            "status": status,
            "expertLevel": hasExpert,
            "packageLogo": logoPath,
            "color": self.getProtocolColor(status),
            "hosts": hosts,
            "projectId": projectId,
            "protocolClassName": protocolClassName,
            "thumbnailUrl": self.buildProtocolThumbnailUrl(projectId,
                                                           int(protocol.getObjId())) if protocol.hasObjId() else None,
            "thumbnailRebuildUrl": self.buildProtocolThumbnailRebuildUrl(projectId,
                                                                         int(protocol.getObjId())) if protocol.hasObjId() else None,
        }

        references = protocol.citations()
        protHelp = protocol.getHelpText() + '\n\n'
        if references != ['No references provided']:
            for reference in references:
                protHelp += reference + '\n'

        form = {
            "references": references,
            "help": protHelp,
        }

        # Detect available wizards and viewers
        wizards = findProtocolWizardsWeb(self.currentProject, protocol)
        viewers = self.findViewersWeb(protocol)

        # Inputs
        # Inputs
        inputs = []

        for key, attr in protocol.iterInputAttributes():
            inp = {
                "inputName": key,
                "paramClass": "PointerParam",
                "pointerClass": "",
                "info": "",
                "value": "",
                "parentId": None,
            }

            targetObj = None
            objValue = None
            extended = None

            try:
                targetObj = attr.get() if attr else None
            except Exception:
                targetObj = None

            try:
                objValue = attr.getObjValue() if attr else None
            except Exception:
                objValue = None

            try:
                extended = attr.getExtended() if attr else None
            except Exception:
                extended = None

            # PostgreSQL runtime can restore a pointer param as raw string:
            #   "1.outputTiltSeriesM"
            # Do not assume attr.get() is always a Scipion object.
            if isinstance(targetObj, str):
                rawValue = targetObj.strip()
                parentId, outputName = self._splitPointerValue(rawValue)

                inp["info"] = rawValue
                inp["value"] = rawValue

                if parentId:
                    try:
                        inp["parentId"] = int(parentId)
                    except Exception:
                        inp["parentId"] = parentId

                if outputName and not extended:
                    extended = outputName

            elif targetObj is not None:
                getClassName = getattr(targetObj, "getClassName", None)
                if callable(getClassName):
                    try:
                        inp["pointerClass"] = getClassName() or ""
                    except Exception:
                        inp["pointerClass"] = ""

                try:
                    inp["info"] = str(targetObj)
                except Exception:
                    inp["info"] = ""

            if objValue is not None:
                getObjId = getattr(objValue, "getObjId", None)
                if callable(getObjId):
                    try:
                        parentObjId = getObjId()
                        if parentObjId is not None:
                            inp["parentId"] = parentObjId
                    except Exception:
                        pass

            if not inp["value"]:
                if inp["parentId"] is not None and extended:
                    inp["value"] = "%s.%s" % (str(inp["parentId"]), str(extended))
                elif isinstance(targetObj, str):
                    inp["value"] = targetObj

            inputs.append(inp)

        info["inputs"] = inputs

        # Outputs
        outputs = []
        for key, attr in protocol.iterOutputAttributes():
            outp = {}
            outp['outputName'] = key
            outp['paramClass'] = 'PointerParam'
            outp['pointerClass'] = attr.__class__.__name__
            try:
                outp['info'] = str(attr)
            except Exception:
                outp['info'] = ""
            outp['value'] = f"{protName}.{key}"
            outp['parentId'] = protocol.getObjId()
            outputs.append(outp)
        info['outputs'] = outputs

        # Definition (params, sections, Line/Group)
        paramsData = []
        paramsValue = {}

        for section in protocol._definition.iterSections():
            if section.getLabel() == 'Parallelization':
                continue

            sectionData = {"label": section.getLabel(), "params": []}

            if section.getLabel() != 'General':
                for paramName, param in section.iterParams():
                    if paramName in headerParams:
                        continue

                    protVar = getattr(protocol, paramName, None)

                    if protVar is None:
                        # Handle Group
                        if isinstance(param, Group):
                            group, _ = self.PreprocessParamForm(param, paramName, wizards, None, 0, protVar)
                            if group is not None:
                                group['collapsed'] = False
                                group['params'] = []

                                for paramGroupName, paramGroup in param.iterParams():
                                    protVar = getattr(protocol, paramGroupName, None)

                                    if isinstance(paramGroup, Line):
                                        for paramLineName, paramLine in paramGroup.iterParams():
                                            protVar = getattr(protocol, paramLineName, None)
                                            if protVar:
                                                paramChild, paramValue = self.PreprocessParamForm(
                                                    paramLine, paramLineName, wizards, None, 0, protVar
                                                )
                                                if paramChild:
                                                    group['params'].append(paramChild)
                                                    paramsValue[paramLineName] = paramValue
                                    elif protVar:
                                        paramChild, paramValue = self.PreprocessParamForm(
                                            paramGroup, paramGroupName, wizards, None, 0, protVar
                                        )
                                        if paramChild:
                                            group['params'].append(paramChild)
                                            paramsValue[paramGroupName] = paramValue

                                # attachContainerWizardMetadata(group)

                                if group:
                                    sectionData["params"].append(group)

                        # Handle Line
                        elif isinstance(param, Line):
                            line, _ = self.PreprocessParamForm(param, paramName, wizards, None, 0, protVar)
                            if line is not None:
                                line['params'] = []

                                for paramLineName, paramLine in param.iterParams():
                                    protVar = getattr(protocol, paramLineName, None)
                                    if protVar:
                                        paramChild, paramValue = self.PreprocessParamForm(
                                            paramLine, paramLineName, wizards, None, 0, protVar
                                        )
                                        if paramChild:
                                            line['params'].append(paramChild)
                                            paramsValue[paramLineName] = paramValue

                                # attachContainerWizardMetadata(line)

                                if line:
                                    sectionData["params"].append(line)

                    else:
                        paramProcessed, paramValue = self.PreprocessParamForm(
                            param, paramName, wizards, None, 0, protVar
                        )
                        if paramProcessed:
                            sectionData["params"].append(paramProcessed)
                            paramsValue[paramName] = paramValue

            if section.getLabel() == 'General':
                # Special params
                for paramName in headerParams:
                    paramProcessed = {'name': paramName}
                    paramValue = getattr(protocol, paramName, None)

                    if paramName == '_objComment':
                        paramProcessed.setdefault(paramName, {})
                        paramProcessed['label'] = 'Comment'
                        paramProcessed['expertLevel'] = 0
                        paramProcessed['condition'] = None
                        paramProcessed['_isImportant'] = True
                        paramProcessed['help'] = 'Protocol comments'
                        paramProcessed['paramClass'] = 'StringParam'
                        paramProcessed['default'] = ''
                        paramProcessed['readOnly'] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None
                        sectionData["params"].append(paramProcessed)
                        paramsValue[paramName] = paramValue

                    elif paramName == '_useQueue':
                        paramProcessed['label'] = 'Use a queue engine?'
                        paramProcessed['expertLevel'] = 0
                        paramProcessed['condition'] = None
                        paramProcessed['_isImportant'] = True
                        paramProcessed['help'] = pwutils.Message.HELP_USEQUEUE % (
                            pyworkflow.Config.SCIPION_HOSTS, pyworkflow.DOCSITEURLS.HOST_CONFIG
                        )
                        paramProcessed['paramClass'] = 'BooleanParam'
                        paramProcessed['default'] = False
                        paramProcessed['readOnly'] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None
                        sectionData["params"].append(paramProcessed)
                        paramsValue[paramName] = paramValue.get()

                    elif paramName == '_prerequisites':
                        paramProcessed.setdefault(paramName, {})
                        paramProcessed['label'] = 'Wait for'
                        paramProcessed['expertLevel'] = 0
                        paramProcessed['condition'] = None
                        paramProcessed['_isImportant'] = True
                        paramProcessed['help'] = pwutils.Message.HELP_WAIT_FOR % (
                            pyworkflow.DOCSITEURLS.WAIT_FOR
                        )
                        paramProcessed['paramClass'] = 'StringParam'
                        paramProcessed['default'] = []
                        paramProcessed['readOnly'] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None
                        sectionData["params"].append(paramProcessed)
                        paramsValue[paramName] = paramValue

                    elif paramName == 'expertLevel':
                        paramProcessed['label'] = 'Expert Level'
                        paramProcessed['display'] = 0
                        paramProcessed['choices'] = ['Normal', 'Advanced']
                        paramProcessed['condition'] = None
                        paramProcessed['_isImportant'] = True
                        paramProcessed['paramClass'] = 'EnumParam'
                        paramProcessed['default'] = 0
                        paramProcessed['readOnly'] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None
                        sectionData["params"].append(paramProcessed)
                        paramsValue[paramName] = 0

                    elif paramName == 'runMode':
                        paramProcessed['label'] = 'Run Mode'
                        paramProcessed['display'] = 0
                        paramProcessed['choices'] = ['Continue', 'Restart']
                        paramProcessed['condition'] = None
                        paramProcessed['_isImportant'] = True
                        paramProcessed['paramClass'] = 'EnumParam'
                        paramProcessed['default'] = 0
                        paramProcessed['readOnly'] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None
                        sectionData["params"].append(paramProcessed)
                        paramsValue[paramName] = 0

                    else:
                        param = protocol.getParam(paramName)
                        if param is not None:
                            if paramName == 'gpuList':
                                param.label.set('GPU IDs')
                                param.condition.set(None)

                            paramProcessed, paramValue = self.PreprocessParamForm(
                                param, paramName, wizards, None, 0, None
                            )

                            if paramProcessed:
                                if paramName == 'runName':
                                    paramProcessed['default'] = ''
                                    paramValue = runName
                                elif paramName == 'numberOfThreads':
                                    paramValue = protocol.getScipionThreads()
                                elif paramName == 'gpuList':
                                    paramValue = protocol.gpuList.get()
                                elif paramName == 'numberOfMpi':
                                    paramValue = protocol.getMPIs()

                                sectionData["params"].append(paramProcessed)

                            paramsValue[paramName] = paramValue

            paramsData.append(sectionData)

        info['executeMode'] = {
            'launch': {
                'label': 'Launch',
                'help': 'Start the protocol from its current configuration'
            },
            'restart': {
                'label': 'Restart',
                'help': 'Restart the protocol execution from scratch (keeps current params).'
            },
        }

        emptyInput, openSetPointer, emptyPointers = protocol.getInputStatus()
        if openSetPointer or emptyPointers:
            info['executeMode'] = {
                'schedule': {
                    'label': 'Schedule',
                    'help': 'Schedule the protocol from its current configuration'
                }
            }

        if protocol.getStatus() in [STATUS_LAUNCHED, STATUS_RUNNING, STATUS_SCHEDULED]:
            info['executeMode'] = {
                'stop': {
                    'label': 'Stop',
                    'help': 'Stop the protocol'
                }
            }

        form["sections"] = paramsData
        context['info'] = info
        context['form'] = form
        context['values'] = paramsValue
        return context

    def _buildNewProtocolContextInSubprocess(self, projectId: int, protocolClassName: str) -> Dict[str, Any]:
        # buildNewProtocolContextInSubprocess
        projectPath = None
        for attr in ("path", "_path"):
            if hasattr(self.currentProject, attr):
                projectPath = getattr(self.currentProject, attr)
                break
        if not projectPath and hasattr(self.currentProject, "getPath"):
            projectPath = self.currentProject.getPath()

        if not projectPath:
            raise RuntimeError("Cannot resolve currentProject path for subprocess protocol build")

        code = """
    import contextlib
    import os
    import sys

    with contextlib.redirect_stdout(sys.stderr):
        from pyworkflow.project import Manager
        from app.backend.api.services.project_service import ProjectService

        projectPath = os.environ["SCIPIONWEB_PROJECT_PATH"]
        projectId = int(os.environ["SCIPIONWEB_PROJECT_ID"])
        protocolClassName = os.environ["SCIPIONWEB_PROTOCOL_CLASS"]

        mgr = Manager()
        project = mgr.loadProject(projectPath)

        domain = project.getDomain()
        protClass = domain.getProtocols().get(protocolClassName)
        if protClass is None:
            raise RuntimeError(f"Protocol class not found: {protocolClassName}")

        protocol = project.newProtocol(protClass)
        project._fixProtParamsConfiguration(protocol)

        svc = ProjectService()
        svc.currentProject = project

        _scipionPayload = svc._buildProtocolContext(projectId, protocol)
    """

        projectRoot = Path(__file__).resolve().parents[4]
        env = os.environ.copy()

        env["SCIPIONWEB_PROJECT_PATH"] = str(projectPath)
        env["SCIPIONWEB_PROJECT_ID"] = str(int(projectId))
        env["SCIPIONWEB_PROTOCOL_CLASS"] = str(protocolClassName)

        existingPythonPath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(projectRoot) + (os.pathsep + existingPythonPath if existingPythonPath else "")

        return self._runJsonSubprocess(
            code=code,
            operationName="Build new protocol context",
        )

    def getNewProtocolParams(self, projectId, protocolClassName: str) -> dict:
        # getNewProtocolParams
        _invalidateNewProtocolCacheIfNeeded()

        key = "%s:%s" % (str(projectId), str(protocolClassName))

        with _newProtocolLock:
            cached = _newProtocolCache.get(key)
            if cached is not None:
                return copy.deepcopy(cached)

        # tryInProcessFirst
        protClass = self.currentProject.getDomain().getProtocols().get(protocolClassName)
        if protClass:
            protocol = self.currentProject.newProtocol(protClass)
            self.currentProject._fixProtParamsConfiguration(protocol)
            ctx = self._buildProtocolContext(projectId, protocol)

            with _newProtocolLock:
                _newProtocolCache[key] = ctx

            return copy.deepcopy(ctx)

        # fallbackSubprocessWhenDomainIsStale
        ctx = self._buildNewProtocolContextInSubprocess(int(projectId), str(protocolClassName))

        with _newProtocolLock:
            _newProtocolCache[key] = ctx

        return copy.deepcopy(ctx)

    def getProtocolParams(
            self,
            mapper,
            projectId: int,
            protocolId: int,
    ) -> dict:
        """
        Returns the parameters of an existing protocol given its ID.
        """
        usingPostgresqlRuntime = self._currentProjectUsesPostgresqlRuntimeMapper()

        if usingPostgresqlRuntime:
            self.syncPostgresqlRuntimeProtocol(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                registerOutputs=False,
            )

        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol.getPlugin()

        # Do not call Scipion's _fixProtParamsConfiguration for PostgreSQL-runtime
        # reconstructed protocols. It assumes pointer.get() returns a Scipion object,
        # but PostgreSQL can restore saved pointers as raw strings like:
        #   "1.outputTSMovies"
        if not usingPostgresqlRuntime:
            self.currentProject._fixProtParamsConfiguration(protocol)

        return self._buildProtocolContext(projectId, protocol)

    def getNextProtocolSuggestions(self, mapper, projectId, protocolId):
        """ Returns the suggestions from the Scipion website for the next protocols to the protocol passed
        """
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )
        protName = protocol.getClassName()
        try:
            url = Config.SCIPION_STATS_SUGGESTION % protName  # protocol.getClassName()
            suggestions = json.loads(urlopen(url).read().decode('utf-8'))
            protList = []
            for suggestion in suggestions:
                # Fields comming from the site:
                # https://scipion.i2pc.es/report_protocols/api/v2/nextprotocol/suggestion/None/
                # 'next_protocol__name', 'count', 'next_protocol__friendlyName', 'next_protocol__package', 'next_protocol__description'
                nextProtName, count, name, package, descr = suggestion
                streamstate = "unknown"
                if package is None and name is not None:
                    package = "scipion-em-%s" % name.split('-')[0].strip()

                installed = "Missing. Available in %s plugin." % package
                protClass = Config.getDomain().getProtocols().get(nextProtName, None)

                # Get accurate values from existing installations
                if protClass is not None:
                    name = protClass.getClassLabel().lower()
                    descr = protClass.getHelpText() + '\n\n'
                    references = self.currentProject.newProtocol(protClass).citations()
                    if references != ['No references provided']:
                        for reference in references:
                            descr += reference + '\n'
                    streamstate = "streamified" if protClass.worksInStreaming() else "static"
                    if protClass.isInstalled():
                        installed = "installed"

                line = {count: {'protocolName': name,
                        'protocolClass': nextProtName,
                        'help': descr,
                        'installed': installed}}

                # line = (nextProtName, name,
                #         installed,
                #         descr,
                #         streamstate,
                #         "",
                #         "",
                #         "",
                #         count)

                protList.append(line)

            def extractValuesSortedByMaxKeyDesc(items: Sequence[Dict[Any, Dict]], *, castKey=int) -> List[Dict]:
                # Sort the list by the maximum key inside each dict (desc), then return values ordered by that key
                sortedItems = sorted(items, key=lambda d: max(castKey(k) for k in d.keys()), reverse=True)
                return [d[max(d.keys(), key=lambda k: castKey(k))] for d in sortedItems]

            sortedList = extractValuesSortedByMaxKeyDesc(protList)

            return sortedList
        except Exception as e:
            logger.error("Suggestions system not available", exc_info=e)
            return []

    def castParamValue(self, param, rawValue):
        """Cast rawValue to the correct type depending on param type."""
        if isinstance(param, EnumParam):
            if isinstance(rawValue, int):
                return rawValue
            try:
                return param.choices.index(str(rawValue))
            except ValueError:
                for index, choice in enumerate(param.choices):
                    if str(choice).lower() == str(rawValue).lower():
                        return index
                return 0
        elif isinstance(param, IntParam):
            return int(rawValue) if rawValue not in (None, "") else None
        elif isinstance(param, FloatParam):
            return float(rawValue) if rawValue not in (None, "") else None
        elif isinstance(param, BooleanParam):
            return str(rawValue).lower() in ("true", "1", "yes", "y")
        elif isinstance(param, (StringParam, EnumParam)):
            return str(rawValue) if rawValue is not None else None
        elif isinstance(param, CsvList):
            return [rawValue]
        else:
            return rawValue

    def _getParentProtocolForPointer(
            self,
            mapper,
            projectId: int,
            parentId,
    ):
        parentScipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=parentId,
        )

        parentProtocol = None

        if self._currentProjectUsesPostgresqlRuntimeMapper():
            parentProtocol = self._loadProtocolFromRuntimeDb(
                protocolId=parentScipionProtocolId,
            )

        if parentProtocol is None:
            parentProtocol = self._getScipionProtocolByRuntimeId(
                parentScipionProtocolId,
            )

        return parentScipionProtocolId, parentProtocol

    def _splitPointerValue(self, value):
        valueText = str(value or "").strip()

        if not valueText:
            return "", ""

        if "." not in valueText:
            return "", valueText

        parentId, outputName = valueText.split(".", 1)
        return parentId.strip(), outputName.strip()

    def applyParamsToProtocol(
            self,
            mapper,
            projectId: int,
            protocol,
            params,
    ):
        """Apply pointer parameters to protocol."""
        errorList = []
        for key, value in params.items():
            param = protocol.getParam(key)
            if param is None:
                continue

            if isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):

                if isinstance(param, MultiPointerParam):
                    newInputs = PointerList()

                    for v in value or []:
                        parentId, rawValue = self._splitPointerValue(v)

                        if rawValue:
                            try:
                                parentScipionProtocolId, parentProtocol = self._getParentProtocolForPointer(
                                    mapper=mapper,
                                    projectId=projectId,
                                    parentId=parentId,
                                )

                                parentProtocolDbId = self._resolvePostgresqlProtocolDbId(
                                    mapper=mapper,
                                    projectId=projectId,
                                    protocolId=parentScipionProtocolId,
                                )

                                if parentProtocolDbId is None:
                                    errorList.append(
                                        '**%s** parent protocol %s was not found in PostgreSQL.'
                                        % (param.label.get(), parentScipionProtocolId)
                                    )
                                    continue

                                resolvedOutput = self._resolveParentOutputForRuntimePointer(
                                    mapper=mapper,
                                    projectId=projectId,
                                    parentProtocolDbId=int(parentProtocolDbId),
                                    parentScipionProtocolId=parentScipionProtocolId,
                                    parentProtocol=parentProtocol,
                                    outputName=output,
                                )

                                if not resolvedOutput.get("exists"):
                                    errorList.append(
                                        '**%s** parent protocol %s does not have output %s in PostgreSQL or runtime.'
                                        % (param.label.get(), parentScipionProtocolId, rawValue)
                                    )
                                    continue

                                newInputs.append(
                                    Pointer(parentProtocol, extended=rawValue)
                                )

                                logger.debug(
                                    "MultiPointer param %s set from parent %s output %s source=%s hasRuntimeAttribute=%s",
                                    key,
                                    parentScipionProtocolId,
                                    rawValue,
                                    resolvedOutput.get("source"),
                                    resolvedOutput.get("hasRuntimeAttribute"),
                                )

                                logger.info(
                                    "[INFO] MultiPointer param %s set from parent %s output %s",
                                    key,
                                    parentScipionProtocolId,
                                    rawValue,
                                )

                            except Exception as e:
                                logger.exception(
                                    "[ERROR] Could not set multipointer param %s from value %s",
                                    key,
                                    v,
                                )
                                errorList.append(
                                    '**%s** could not resolve input %s: %s'
                                    % (param.label.get(), v, e)
                                )
                        else:
                            param.set(None)

                    if newInputs.isEmpty() and not param.allowsNull.get():
                        errorList.append('**' + param.label.get() + '** it must not be empty.')

                    protocol.setAttributeValue(key, newInputs)

                elif isinstance(param, PointerParam):
                    pointerValues = self._normalizeRuntimePointerParamValues(value)
                    pointerValue = pointerValues[0] if pointerValues else None

                    parentId, rawValue = self._splitPointerValue(pointerValue)

                    if rawValue:
                        try:
                            parentScipionProtocolId, parentProtocol = self._getParentProtocolForPointer(
                                mapper=mapper,
                                projectId=projectId,
                                parentId=parentId,
                            )

                            output = rawValue
                            val = f"{parentScipionProtocolId}.{output}"

                            parentProtocolDbId = self._resolvePostgresqlProtocolDbId(
                                mapper=mapper,
                                projectId=projectId,
                                protocolId=parentScipionProtocolId,
                            )

                            if parentProtocolDbId is None:
                                errorList.append(
                                    '**%s** parent protocol %s was not found in PostgreSQL.'
                                    % (param.label.get(), parentScipionProtocolId)
                                )
                                continue

                            resolvedOutput = self._resolveParentOutputForRuntimePointer(
                                mapper=mapper,
                                projectId=projectId,
                                parentProtocolDbId=int(parentProtocolDbId),
                                parentScipionProtocolId=parentScipionProtocolId,
                                parentProtocol=parentProtocol,
                                outputName=output,
                            )

                            if not resolvedOutput.get("exists"):
                                errorList.append(
                                    '**%s** parent protocol %s does not have output %s in PostgreSQL or runtime.'
                                    % (param.label.get(), parentScipionProtocolId, output)
                                )
                                continue

                            pointer = getattr(protocol, key, None)

                            if pointer is None or isinstance(pointer, str) or not hasattr(pointer, "set"):
                                pointer = Pointer(parentProtocol, extended=output)
                                setattr(protocol, key, pointer)
                            else:
                                pointer.set(parentProtocol)
                                pointer.setExtended(output)

                            # Keep the form/default textual representation if available,
                            # but do not call param.set(val), because that stores the input as string.
                            try:
                                param.default.set(val)
                            except Exception:
                                pass

                            logger.debug(
                                "Pointer param %s set. childProtocol=%s parentProtocol=%s output=%s "
                                "source=%s hasRuntimeAttribute=%s pointer=%s pointerObj=%s extended=%s targetObjId=%s target=%s",
                                key,
                                getattr(protocol, "getObjId", lambda: None)(),
                                parentScipionProtocolId,
                                output,
                                resolvedOutput.get("source"),
                                resolvedOutput.get("hasRuntimeAttribute"),
                                pointer,
                                getattr(pointer, "getObjValue", lambda: None)() if pointer is not None else None,
                                getattr(pointer, "getExtended", lambda: None)() if pointer is not None else None,
                                getattr(
                                    getattr(pointer, "getObjValue", lambda: None)(),
                                    "getObjId",
                                    lambda: None,
                                )() if pointer is not None else None,
                                getattr(pointer, "get", lambda: None)() if pointer is not None else None,
                            )

                        except Exception as e:
                            logger.exception(
                                "[ERROR] Could not set pointer param %s from value %s",
                                key,
                                value,
                            )
                            errorList.append(
                                '**%s** could not resolve input %s: %s'
                                % (param.label.get(), value, e)
                            )

                    else:
                        conditionValue = None
                        try:
                            if hasattr(param, "condition") and param.condition is not None:
                                conditionValue = param.condition.get()
                        except Exception:
                            conditionValue = None

                        shouldValidate = True
                        if isinstance(conditionValue, str):
                            conditionText = conditionValue.strip()
                            if conditionText:
                                try:
                                    shouldValidate = bool(protocol.evalCondition(conditionText))
                                except Exception:
                                    shouldValidate = True

                        if not param.allowsNull.get() and shouldValidate:
                            errorList.append('**' + param.label.get() + '** it must not be empty.')

                        param.set(None)
        return errorList

    def syncPostgresqlRuntimeProtocolInputsAndDependencies(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            protocol,
            params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sync input refs and dependency edges for one PostgreSQL-runtime protocol.

        Important:
          - Dependency edges are resolved from raw params, not only from Scipion Pointer objects.
          - The workflow graph loaded from PostgreSQL uses protocol_dependencies.
        """
        protocolId = self._getScipionObjectId(protocol)
        if protocolId is None:
            return {
                "protocolId": None,
                "protocolDbId": None,
                "parents": [],
                "inputRefs": [],
                "dependencies": 0,
                "inputRefsSaved": 0,
                "skipped": True,
                "reason": "protocol_without_id",
            }

        protocolDbId = self._resolvePostgresqlProtocolDbId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if protocolDbId is None:
            return {
                "protocolId": str(protocolId),
                "protocolDbId": None,
                "parents": [],
                "inputRefs": [],
                "dependencies": 0,
                "inputRefsSaved": 0,
                "skipped": True,
                "reason": "protocol_not_found",
            }

        parentProtocolDbIds: List[int] = []
        parentProtocolIds: List[int] = []
        inputRefs: List[Dict[str, Any]] = []

        rawParams = params or {}

        params = self._mergeRuntimePointerParamsWithProtocolState(
            protocol=protocol,
            params=rawParams,
        )

        detectedPointerParams = []

        logger.debug(
            "Runtime dependency sync merged pointer params. projectId=%s protocolId=%s "
            "rawParams=%s mergedParams=%s",
            projectId,
            protocolId,
            rawParams,
            params,
        )

        for inputName, rawParamValue in params.items():
            try:
                param = protocol.getParam(inputName)
            except Exception:
                param = None

            if not isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
                continue

            pointerValues = self._normalizeRuntimePointerParamValues(rawParamValue)

            if not pointerValues:
                continue

            validPointerValues = []

            for pointerValue in pointerValues:
                parentId, outputName = self._splitPointerValue(pointerValue)

                if parentId and outputName:
                    validPointerValues.append(pointerValue)

            if not validPointerValues:
                continue

            detectedPointerParams.append({
                "inputName": inputName,
                "paramClass": param.__class__.__name__ if param is not None else None,
                "isPointerParam": isinstance(param, (PointerParam, MultiPointerParam, RelationParam)),
                "rawValue": rawParamValue,
                "pointerValues": validPointerValues,
            })

            for itemIndex, pointerValue in enumerate(pointerValues):
                parentId, outputName = self._splitPointerValue(pointerValue)

                if not parentId or not outputName:
                    continue

                try:
                    parentScipionProtocolId = self._resolveScipionProtocolId(
                        mapper=mapper,
                        projectId=projectId,
                        protocolId=parentId,
                    )
                except Exception:
                    logger.exception(
                        "Could not resolve parent protocol id from pointer param. "
                        "projectId=%s childProtocolId=%s inputName=%s value=%s",
                        projectId,
                        protocolId,
                        inputName,
                        pointerValue,
                    )
                    continue

                parentProtocolDbId = self._resolvePostgresqlProtocolDbId(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=parentScipionProtocolId,
                )

                if parentProtocolDbId is None:
                    logger.warning(
                        "Parent protocol row not found while syncing runtime dependency. "
                        "projectId=%s childProtocolId=%s parentProtocolId=%s inputName=%s outputName=%s",
                        projectId,
                        protocolId,
                        parentScipionProtocolId,
                        inputName,
                        outputName,
                    )
                    continue

                parentProtocolDbId = int(parentProtocolDbId)
                parentScipionProtocolId = int(parentScipionProtocolId)

                if parentProtocolDbId not in parentProtocolDbIds:
                    parentProtocolDbIds.append(parentProtocolDbId)

                if parentScipionProtocolId not in parentProtocolIds:
                    parentProtocolIds.append(parentScipionProtocolId)

                outputInfo = self._getPersistedOutputInfoForInputRef(
                    mapper=mapper,
                    projectId=projectId,
                    parentProtocolDbId=parentProtocolDbId,
                    outputName=outputName,
                )

                inputRefs.append({
                    "projectId": int(projectId),
                    "protocolDbId": int(protocolDbId),
                    "protocolId": str(protocolId),
                    "inputName": str(inputName),
                    "itemIndex": int(itemIndex),
                    "parentProtocolDbId": parentProtocolDbId,
                    "parentProtocolId": str(parentScipionProtocolId),
                    "parentOutputName": str(outputName),
                    "objectClassName": outputInfo.get("className"),
                    "objectId": outputInfo.get("objectId"),
                })

        logger.debug(
            "Runtime dependency sync from params. projectId=%s childProtocolId=%s protocolDbId=%s "
            "parentProtocolDbIds=%s parentProtocolIds=%s inputRefs=%s detectedPointerParams=%s allParams=%s",
            projectId,
            protocolId,
            protocolDbId,
            parentProtocolDbIds,
            parentProtocolIds,
            inputRefs,
            detectedPointerParams,
            params,
        )

        dependenciesSaved = self._replacePostgresqlDependenciesForProtocol(
            mapper=mapper,
            projectId=projectId,
            childProtocolDbId=int(protocolDbId),
            parentProtocolDbIds=parentProtocolDbIds,
        )

        inputRefsSaved = self._replacePostgresqlInputRefsForProtocol(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(protocolDbId),
            refs=inputRefs,
        )

        self._updatePostgresqlProtocolParentIds(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(protocolDbId),
            parentProtocolIds=parentProtocolIds,
        )

        return {
            "protocolId": str(protocolId),
            "protocolDbId": int(protocolDbId),
            "parents": parentProtocolDbIds,
            "parentProtocolIds": parentProtocolIds,
            "inputRefs": inputRefs,
            "dependencies": dependenciesSaved,
            "inputRefsSaved": inputRefsSaved,
            "skipped": False,
        }

    def _normalizeRuntimePointerValuesFromProtocolAttribute(self, attr: Any) -> List[str]:
        """
        Extract normalized pointer values from an already-applied Scipion pointer attribute.

        This protects PostgreSQL runtime dependency sync from partial launch payloads:
        if a pointer is already present on the protocol object, we should preserve it
        even if it is not present in the current request params.
        """
        if attr in (None, ""):
            return []

        result: List[str] = []

        def addValue(parentId, outputName):
            if parentId in (None, "") or outputName in (None, ""):
                return

            value = "%s.%s" % (str(parentId).strip(), str(outputName).strip())
            if value not in result:
                result.append(value)

        # PointerList / MultiPointer-like case.
        try:
            if isinstance(attr, PointerList):
                for item in attr:
                    for value in self._normalizeRuntimePointerValuesFromProtocolAttribute(item):
                        if value not in result:
                            result.append(value)

                return result
        except Exception:
            pass

        # Plain list/tuple fallback, just in case.
        if isinstance(attr, (list, tuple, set)):
            for item in attr:
                for value in self._normalizeRuntimePointerValuesFromProtocolAttribute(item):
                    if value not in result:
                        result.append(value)

            return result

        # Raw value already stored as frontend-like representation.
        if isinstance(attr, (str, dict)):
            return self._normalizeRuntimePointerParamValues(attr)

        targetObj = None
        objValue = None
        extended = None

        try:
            targetObj = attr.get() if hasattr(attr, "get") else None
        except Exception:
            targetObj = None

        try:
            objValue = attr.getObjValue() if hasattr(attr, "getObjValue") else None
        except Exception:
            objValue = None

        try:
            extended = attr.getExtended() if hasattr(attr, "getExtended") else None
        except Exception:
            extended = None

        # Sometimes the pointer target itself is a raw string: "1175.outputTiltSeriesM".
        if isinstance(targetObj, str):
            return self._normalizeRuntimePointerParamValues(targetObj)

        parentId = None

        # Normal Pointer: objValue is the parent protocol.
        if objValue is not None:
            try:
                parentId = objValue.getObjId()
            except Exception:
                parentId = None

        # Sometimes attr.get() returns the pointed output object.
        if parentId is None and targetObj is not None:
            try:
                parentId = targetObj.getObjParentId()
            except Exception:
                parentId = None

        if parentId is None and targetObj is not None:
            try:
                parentObj = targetObj.getObjParent()
                if parentObj is not None:
                    parentId = parentObj.getObjId()
            except Exception:
                parentId = None

        addValue(parentId, extended)

        return result

    def _mergeRuntimePointerParamsWithProtocolState(
            self,
            protocol,
            params: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Merge request params with pointer values already present in the protocol.

        Important:
          - If a param is explicitly present in params, respect the request value.
          - If a pointer param is missing from params, preserve the value already
            applied on the protocol object.
        """
        mergedParams: Dict[str, Any] = dict(params or {})
        explicitParamNames = set(mergedParams.keys())

        try:
            inputAttributes = list(protocol.iterInputAttributes())
        except Exception:
            inputAttributes = []

        for inputName, attr in inputAttributes:
            if inputName in explicitParamNames:
                # The request explicitly sent this param. Do not resurrect old values
                # if the frontend intentionally cleared it.
                continue

            pointerValues = self._normalizeRuntimePointerValuesFromProtocolAttribute(attr)

            if not pointerValues:
                continue

            mergedParams[inputName] = pointerValues[0] if len(pointerValues) == 1 else pointerValues

        return mergedParams

    def _normalizeRuntimePointerParamValues(self, rawValue: Any) -> List[str]:
        """
        Normalize PointerParam/MultiPointerParam values coming from the frontend.

        Supported shapes:
          "1.outputTSMovies"
          {"editableValue": "1.outputTSMovies"}
          {"value": "1.outputTSMovies"}
          {"parentId": 1, "value": "outputTSMovies"}
          {"parentId": 1, "outputName": "outputTSMovies"}
          {"parentProtocolId": 1, "parentOutputName": "outputTSMovies"}
          [{"editableValue": "1.outputA"}, {"parentId": 2, "value": "outputB"}]
        """
        if rawValue in (None, ""):
            return []

        if isinstance(rawValue, (list, tuple, set)):
            result: List[str] = []

            for item in rawValue:
                result.extend(self._normalizeRuntimePointerParamValues(item))

            return result

        if isinstance(rawValue, dict):
            parentId = (
                    rawValue.get("parentId")
                    or rawValue.get("protocolId")
                    or rawValue.get("parentProtocolId")
            )

            outputName = (
                    rawValue.get("outputName")
                    or rawValue.get("parentOutputName")
                    or rawValue.get("extended")
            )

            if parentId not in (None, ""):
                # If value/editableValue already has "1.outputX", keep that.
                for key in ("editableValue", "value", "default", "objValue", "name"):
                    candidate = rawValue.get(key)

                    if candidate in (None, "", []):
                        continue

                    candidateText = str(candidate).strip()

                    if "." in candidateText:
                        return self._normalizeRuntimePointerParamValues(candidateText)

                    if outputName in (None, ""):
                        outputName = candidateText

                    break

                if outputName not in (None, ""):
                    return [f"{parentId}.{outputName}"]

            # Direct textual value case, without separate parentId.
            for key in ("editableValue", "value", "default", "objValue"):
                value = rawValue.get(key)

                if value in (None, "", []):
                    continue

                return self._normalizeRuntimePointerParamValues(value)

            return []

        valueText = str(rawValue or "").strip()
        return [valueText] if valueText else []

    def _getPostgresqlRuntimeOutputInfo(
            self,
            mapper,
            projectId: int,
            parentProtocolDbId: int,
            outputName: str,
    ) -> Dict[str, Any]:
        """
        Resolve a persisted parent output from PostgreSQL.

        This is used by runtime input resolution so child protocols do not depend
        exclusively on the parent runtime db exposing the output as a live attribute.
        """
        row = mapper.db.fetchOne(
            """
            SELECT
                'set' AS kind,
                s.id AS "setId",
                s."objectId"::text AS "objectId",
                s."outputName" AS "outputName",
                s."setClassName" AS "className",
                s."itemClassName" AS "itemClassName",
                s.properties AS properties
              FROM scipion_sets s
             WHERE s."projectId" = %s
               AND s."protocolDbId" = %s
               AND s."outputName" = %s

            UNION ALL

            SELECT
                'object' AS kind,
                NULL AS "setId",
                o."scipionObjId"::text AS "objectId",
                o.name AS "outputName",
                o."className" AS "className",
                NULL AS "itemClassName",
                o.metadata AS properties
              FROM scipion_objects o
             WHERE o."projectId" = %s
               AND o."protocolDbId" = %s
               AND o."parentObjectId" IS NULL
               AND (o.path = %s OR o.name = %s)

             LIMIT 1
            """,
            (
                projectId,
                parentProtocolDbId,
                outputName,
                projectId,
                parentProtocolDbId,
                outputName,
                outputName,
            ),
        )

        if not row:
            return {
                "exists": False,
                "kind": None,
                "setId": None,
                "objectId": None,
                "outputName": outputName,
                "className": None,
                "itemClassName": None,
                "properties": {},
                "itemsCount": None,
                "tablesCount": None,
                "tableItemsCount": None,
            }

        info = dict(row)
        properties = info.get("properties") or {}

        if not isinstance(properties, dict):
            try:
                properties = json.loads(properties)
            except Exception:
                properties = {}

        info["properties"] = properties
        info["exists"] = True

        setId = info.get("setId")

        itemsCount = None
        tablesCount = None
        tableItemsCount = None

        if setId is not None:
            try:
                countRow = mapper.db.fetchOne(
                    """
                    SELECT COUNT(*) AS count
                      FROM scipion_set_items
                     WHERE "setId" = %s
                    """,
                    (int(setId),),
                )
                itemsCount = int(countRow.get("count") or 0) if countRow else 0
            except Exception:
                itemsCount = None

            try:
                countRow = mapper.db.fetchOne(
                    """
                    SELECT COUNT(*) AS count
                      FROM scipion_set_tables
                     WHERE "setId" = %s
                    """,
                    (int(setId),),
                )
                tablesCount = int(countRow.get("count") or 0) if countRow else 0
            except Exception:
                tablesCount = None

            try:
                countRow = mapper.db.fetchOne(
                    """
                    SELECT COUNT(ti.id) AS count
                      FROM scipion_set_tables t
                      JOIN scipion_set_table_items ti
                        ON ti."tableId" = t.id
                     WHERE t."setId" = %s
                    """,
                    (int(setId),),
                )
                tableItemsCount = int(countRow.get("count") or 0) if countRow else 0
            except Exception:
                tableItemsCount = None

        if itemsCount is None:
            try:
                itemsCount = int(
                    properties.get("itemsCount")
                    or properties.get("_size")
                    or 0
                )
            except Exception:
                itemsCount = None

        info["itemsCount"] = itemsCount
        info["tablesCount"] = tablesCount
        info["tableItemsCount"] = tableItemsCount

        return info

    def _attachPostgresqlRuntimeOutputPlaceholder(
            self,
            parentProtocol,
            outputName: str,
            outputInfo: Dict[str, Any],
            mapper=None,
    ):
        """
        Attach a PostgreSQL-backed output proxy to the parent protocol.

        This intentionally replaces the legacy sqlite-backed output attribute when
        PostgreSQL has the output persisted. The goal is that child PointerParams
        resolve through PostgreSQL instead of the original parent output sqlite.
        """
        from app.backend.utils.postgresql_runtime_output_adapter import (
            PostgresqlRuntimeOutputProxy,
        )

        db = getattr(mapper, "db", None)

        if db is None:
            raise ValueError("PostgreSQL mapper/db is required to attach runtime output proxy")

        proxy = PostgresqlRuntimeOutputProxy(
            db=db,
            parent=parentProtocol,
            outputName=outputName,
            outputInfo=outputInfo,
        )

        setattr(parentProtocol, outputName, proxy)

        return proxy

    def _preparePostgresqlRuntimePointerOutputsForLaunch(
            self,
            mapper,
            projectId: int,
            protocol,
    ) -> Dict[str, Any]:
        """
        Prepare child protocol pointers before launch using protocol_input_refs.

        This does not rewrite PostgreSQL graph and does not persist the protocol again.
        It only ensures that Scipion runtime can resolve Pointer(parentProtocol, extended=outputName)
        while launching.

        Important:
          - Existing runtime outputs are kept untouched.
          - PostgreSQL proxy is attached only when the parent runtime protocol does not
            expose the requested output attribute.
        """
        protocolId = self._getScipionObjectId(protocol)

        if protocolId is None:
            return {
                "prepared": 0,
                "skipped": True,
                "reason": "protocol_without_id",
                "items": [],
                "errors": [],
            }

        protocolDbId = self._resolvePostgresqlProtocolDbId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if protocolDbId is None:
            return {
                "protocolId": str(protocolId),
                "protocolDbId": None,
                "prepared": 0,
                "skipped": True,
                "reason": "protocol_not_found_in_postgresql",
                "items": [],
                "errors": [],
            }

        rows = mapper.db.fetchAll(
            """
            SELECT
                "inputName",
                "itemIndex",
                "parentProtocolDbId",
                "parentProtocolId",
                "parentOutputName",
                "objectClassName",
                "objectId"
              FROM protocol_input_refs
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "inputName", "itemIndex"
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        )

        preparedItems = []
        errors = []

        for row in rows or []:
            inputName = str(row.get("inputName") or "").strip()
            parentOutputName = str(row.get("parentOutputName") or "").strip()
            parentProtocolId = row.get("parentProtocolId")
            parentProtocolDbId = row.get("parentProtocolDbId")

            if not inputName or not parentOutputName or parentProtocolId in (None, ""):
                continue

            itemReport = {
                "inputName": inputName,
                "parentProtocolId": str(parentProtocolId),
                "parentProtocolDbId": parentProtocolDbId,
                "parentOutputName": parentOutputName,
                "attachedProxy": False,
                "hadRuntimeAttribute": False,
                "pointerReset": False,
            }

            try:
                parentScipionProtocolId = self._resolveScipionProtocolId(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=parentProtocolId,
                )

                parentProtocol = self._loadProtocolFromRuntimeDb(
                    protocolId=parentScipionProtocolId,
                )

                if parentProtocol is None:
                    parentProtocol = self._getScipionProtocolByRuntimeId(
                        parentScipionProtocolId,
                    )

                try:
                    hasRuntimeAttribute = hasattr(parentProtocol, parentOutputName)
                except Exception:
                    hasRuntimeAttribute = False

                itemReport["hadRuntimeAttribute"] = bool(hasRuntimeAttribute)

                if not hasRuntimeAttribute:
                    resolvedParentProtocolDbId = parentProtocolDbId

                    if resolvedParentProtocolDbId is None:
                        resolvedParentProtocolDbId = self._resolvePostgresqlProtocolDbId(
                            mapper=mapper,
                            projectId=projectId,
                            protocolId=parentScipionProtocolId,
                        )

                    if resolvedParentProtocolDbId is None:
                        raise ValueError(
                            "Parent protocol %s was not found in PostgreSQL"
                            % str(parentScipionProtocolId)
                        )

                    outputInfo = self._getPostgresqlRuntimeOutputInfo(
                        mapper=mapper,
                        projectId=projectId,
                        parentProtocolDbId=int(resolvedParentProtocolDbId),
                        outputName=parentOutputName,
                    )

                    if not outputInfo.get("exists"):
                        raise ValueError(
                            "Parent output %s.%s was not found in PostgreSQL"
                            % (str(parentScipionProtocolId), parentOutputName)
                        )

                    self._attachPostgresqlRuntimeOutputPlaceholder(
                        parentProtocol=parentProtocol,
                        outputName=parentOutputName,
                        outputInfo=outputInfo,
                        mapper=mapper,
                    )

                    itemReport["attachedProxy"] = True
                    itemReport["outputInfo"] = {
                        "kind": outputInfo.get("kind"),
                        "setId": outputInfo.get("setId"),
                        "objectId": outputInfo.get("objectId"),
                        "className": outputInfo.get("className"),
                        "itemClassName": outputInfo.get("itemClassName"),
                        "itemsCount": outputInfo.get("itemsCount"),
                    }

                param = protocol.getParam(inputName)

                if isinstance(param, MultiPointerParam):
                    # Do not rebuild the whole PointerList here yet. This helper is
                    # focused on normal PointerParam launch preparation.
                    # MultiPointer support can be added later if needed.
                    itemReport["pointerReset"] = False
                    itemReport["skippedPointerResetReason"] = "multipointer_not_rebuilt"
                else:
                    pointer = getattr(protocol, inputName, None)

                    if pointer is None or isinstance(pointer, str) or not hasattr(pointer, "set"):
                        pointer = Pointer(parentProtocol, extended=parentOutputName)
                        setattr(protocol, inputName, pointer)
                    else:
                        pointer.set(parentProtocol)
                        pointer.setExtended(parentOutputName)

                    itemReport["pointerReset"] = True

                preparedItems.append(itemReport)

            except Exception as e:
                logger.exception(
                    "Failed to prepare PostgreSQL runtime pointer output for launch. "
                    "projectId=%s protocolId=%s inputName=%s parentProtocolId=%s parentOutputName=%s",
                    projectId,
                    protocolId,
                    inputName,
                    parentProtocolId,
                    parentOutputName,
                )

                itemReport["error"] = str(e)
                errors.append(itemReport)

        report = {
            "protocolId": str(protocolId),
            "protocolDbId": int(protocolDbId),
            "prepared": len(preparedItems),
            "items": preparedItems,
            "errors": errors,
            "skipped": False,
        }

        logger.info(
            "Prepared PostgreSQL runtime pointer outputs for launch. "
            "projectId=%s protocolId=%s report=%s",
            projectId,
            protocolId,
            report,
        )

        return report

    def _repairPostgresqlRuntimeSetMapperInfo(
            self,
            mapper,
            projectId: int,
            outputObj,
            outputInfo: Dict[str, Any],
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
            projectPath = None

            try:
                projectPath = self._getCurrentProjectPath()
            except Exception:
                projectPath = None

            if not projectPath and mapper is not None:
                try:
                    row = mapper.db.fetchOne(
                        """
                        SELECT name
                          FROM projects
                         WHERE id = %s
                        """,
                        (int(projectId),),
                    )
                    if row:
                        projectPath = row.get("name")
                except Exception:
                    projectPath = None

            if projectPath:
                mapperPath = os.path.abspath(os.path.join(str(projectPath), mapperPath))

        if not mapperPath:
            return False

        # If the object already has a filename, do not force it unless mapper path is missing.
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

    def _resolveParentOutputForRuntimePointer(
            self,
            mapper,
            projectId: int,
            parentProtocolDbId: int,
            parentScipionProtocolId,
            parentProtocol,
            outputName: str,
            attachProxy: bool = False,
    ) -> Dict[str, Any]:
        """
        Resolve a parent output for a child PointerParam/MultiPointerParam.

        PostgreSQL is the source of truth for output existence.
        The Scipion runtime attribute is kept only as compatibility.
        """
        outputInfo = self._getPostgresqlRuntimeOutputInfo(
            mapper=mapper,
            projectId=projectId,
            parentProtocolDbId=parentProtocolDbId,
            outputName=outputName,
        )

        hasRuntimeAttribute = False

        try:
            hasRuntimeAttribute = hasattr(parentProtocol, outputName)
        except Exception:
            hasRuntimeAttribute = False

        if outputInfo.get("exists"):
            outputObj = None

            try:
                outputObj = getattr(parentProtocol, outputName, None)
            except Exception:
                outputObj = None

            repairedMapper = False

            persistedMapperRepair = False

            if outputObj is not None:
                repairedMapper = self._repairPostgresqlRuntimeSetMapperInfo(
                    mapper=mapper,
                    projectId=projectId,
                    outputObj=outputObj,
                    outputInfo=outputInfo,
                )

                if repairedMapper:
                    try:
                        # Important:
                        # The execution process may reload the parent protocol/output from
                        # the runtime DB, so an in-memory repair is not enough.
                        self.currentProject._storeProtocol(parentProtocol)
                        persistedMapperRepair = True

                        logger.info(
                            "Persisted repaired PostgreSQL runtime Set mapper metadata. "
                            "projectId=%s parentProtocolId=%s parentProtocolDbId=%s outputName=%s outputObj=%s",
                            projectId,
                            parentScipionProtocolId,
                            parentProtocolDbId,
                            outputName,
                            outputObj,
                        )

                    except Exception:
                        logger.exception(
                            "Could not persist repaired PostgreSQL runtime Set mapper metadata. "
                            "projectId=%s parentProtocolId=%s parentProtocolDbId=%s outputName=%s outputObj=%s",
                            projectId,
                            parentScipionProtocolId,
                            parentProtocolDbId,
                            outputName,
                            outputObj,
                        )

            logger.debug(
                "Resolved runtime output from PostgreSQL. "
                "projectId=%s parentProtocolId=%s parentProtocolDbId=%s "
                "outputName=%s hasRuntimeAttribute=%s repairedMapper=%s outputObj=%s outputInfo=%s",
                projectId,
                parentScipionProtocolId,
                parentProtocolDbId,
                outputName,
                hasRuntimeAttribute,
                repairedMapper,
                outputObj,
                outputInfo,
            )

            return {
                "exists": True,
                "source": "postgresql",
                "hasRuntimeAttribute": hasRuntimeAttribute,
                "repairedMapper": repairedMapper,
                "persistedMapperRepair": persistedMapperRepair,
                "outputInfo": outputInfo,
            }

        if hasRuntimeAttribute:
            return {
                "exists": True,
                "source": "scipion_runtime",
                "hasRuntimeAttribute": True,
                "outputInfo": outputInfo,
            }

        return {
            "exists": False,
            "source": None,
            "hasRuntimeAttribute": False,
            "outputInfo": outputInfo,
        }

    def _getPersistedOutputInfoForInputRef(
            self,
            mapper,
            projectId: int,
            parentProtocolDbId: int,
            outputName: str,
    ) -> Dict[str, Any]:
        row = mapper.db.fetchOne(
            """
            SELECT
                s."objectId"::text AS "objectId",
                s."setClassName" AS "className"
              FROM scipion_sets s
             WHERE s."projectId" = %s
               AND s."protocolDbId" = %s
               AND s."outputName" = %s

            UNION ALL

            SELECT
                o."scipionObjId"::text AS "objectId",
                o."className" AS "className"
              FROM scipion_objects o
             WHERE o."projectId" = %s
               AND o."protocolDbId" = %s
               AND o."parentObjectId" IS NULL
               AND (o.path = %s OR o.name = %s)

             LIMIT 1
            """,
            (
                projectId,
                parentProtocolDbId,
                outputName,
                projectId,
                parentProtocolDbId,
                outputName,
                outputName,
            ),
        )

        if not row:
            return {
                "objectId": None,
                "className": None,
            }

        return {
            "objectId": row.get("objectId"),
            "className": row.get("className"),
        }

    def _updatePostgresqlProtocolParentIds(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            parentProtocolIds: List[int],
    ) -> None:
        cleanParentIds = []
        seen = set()

        for parentId in parentProtocolIds or []:
            try:
                parentId = int(parentId)
            except Exception:
                continue

            if parentId <= 0:
                continue

            if parentId in seen:
                continue

            seen.add(parentId)
            cleanParentIds.append(parentId)

        mapper.db.execute(
            """
            UPDATE protocols
               SET "parentIds" = %s,
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND id = %s
            """,
            (
                cleanParentIds,
                int(projectId),
                int(protocolDbId),
            ),
        )

    def _replacePostgresqlDependenciesForProtocol(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            childProtocolDbId: int,
            parentProtocolDbIds: List[int],
    ) -> int:
        cleanParentDbIds = []
        seen = set()

        for parentDbId in parentProtocolDbIds or []:
            try:
                parentDbId = int(parentDbId)
            except Exception:
                continue

            if parentDbId <= 0:
                continue

            if parentDbId == int(childProtocolDbId):
                continue

            if parentDbId in seen:
                continue

            seen.add(parentDbId)
            cleanParentDbIds.append(parentDbId)

        with mapper.db.transaction():
            mapper.db.execute(
                """
                DELETE FROM protocol_dependencies
                 WHERE "projectId" = %s
                   AND "childProtocolDbId" = %s
                """,
                (projectId, childProtocolDbId),
                commit=False,
            )

            if not cleanParentDbIds:
                return 0

            valuesSql = ",".join(["(%s, %s, %s)"] * len(cleanParentDbIds))
            params = []

            for parentDbId in cleanParentDbIds:
                params.extend([
                    int(projectId),
                    int(parentDbId),
                    int(childProtocolDbId),
                ])

            mapper.db.execute(
                f"""
                INSERT INTO protocol_dependencies (
                    "projectId",
                    "parentProtocolDbId",
                    "childProtocolDbId"
                )
                VALUES {valuesSql}
                """,
                tuple(params),
                commit=False,
            )

        return len(cleanParentDbIds)

    def _replacePostgresqlInputRefsForProtocol(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            protocolDbId: int,
            refs: List[Dict[str, Any]],
    ) -> int:
        def toOptionalInt(value: Any) -> Optional[int]:
            if value is None or value == "":
                return None

            try:
                return int(value)
            except Exception:
                try:
                    return int(float(value))
                except Exception:
                    return None

        cleanRefs = []
        seen = set()

        for ref in refs or []:
            inputName = str(ref.get("inputName") or "").strip()
            if not inputName:
                continue

            itemIndex = toOptionalInt(ref.get("itemIndex"))
            if itemIndex is None or itemIndex < 0:
                itemIndex = 0

            protocolId = str(ref.get("protocolId") or "").strip()
            if not protocolId:
                continue

            key = (inputName, itemIndex)
            if key in seen:
                continue

            seen.add(key)

            cleanRefs.append({
                "projectId": int(projectId),
                "protocolDbId": int(protocolDbId),
                "protocolId": protocolId,
                "inputName": inputName,
                "itemIndex": int(itemIndex),
                "parentProtocolDbId": toOptionalInt(ref.get("parentProtocolDbId")),
                "parentProtocolId": str(ref.get("parentProtocolId")).strip()
                if ref.get("parentProtocolId") not in (None, "") else None,
                "parentOutputName": str(ref.get("parentOutputName")).strip()
                if ref.get("parentOutputName") not in (None, "") else None,
                "objectClassName": str(ref.get("objectClassName")).strip()
                if ref.get("objectClassName") not in (None, "") else None,
                "objectId": str(ref.get("objectId")).strip()
                if ref.get("objectId") not in (None, "") else None,
            })

        with mapper.db.transaction():
            mapper.db.execute(
                """
                DELETE FROM protocol_input_refs
                 WHERE "projectId" = %s
                   AND "protocolDbId" = %s
                """,
                (projectId, protocolDbId),
                commit=False,
            )

            if not cleanRefs:
                return 0

            valuesSql = ",".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(cleanRefs))
            params = []

            for ref in cleanRefs:
                params.extend([
                    ref["projectId"],
                    ref["protocolDbId"],
                    ref["protocolId"],
                    ref["inputName"],
                    ref["itemIndex"],
                    ref["parentProtocolDbId"],
                    ref["parentProtocolId"],
                    ref["parentOutputName"],
                    ref["objectClassName"],
                    ref["objectId"],
                ])

            mapper.db.execute(
                f"""
                INSERT INTO protocol_input_refs (
                    "projectId",
                    "protocolDbId",
                    "protocolId",
                    "inputName",
                    "itemIndex",
                    "parentProtocolDbId",
                    "parentProtocolId",
                    "parentOutputName",
                    "objectClassName",
                    "objectId"
                )
                VALUES {valuesSql}
                ON CONFLICT ("projectId", "protocolDbId", "inputName", "itemIndex")
                DO UPDATE SET
                    "protocolId" = EXCLUDED."protocolId",
                    "parentProtocolDbId" = EXCLUDED."parentProtocolDbId",
                    "parentProtocolId" = EXCLUDED."parentProtocolId",
                    "parentOutputName" = EXCLUDED."parentOutputName",
                    "objectClassName" = EXCLUDED."objectClassName",
                    "objectId" = EXCLUDED."objectId",
                    "updatedAt" = NOW()
                """,
                tuple(params),
                commit=False,
            )

        return len(cleanRefs)

    def setPointerParam(
            self,
            mapper,
            projectId: int,
            protocol,
            key,
            value,
            parentId,
    ):
        """Resolve and set a pointer param from parent protocol outputs."""
        param = protocol.getParam(key)
        if not isinstance(param, PointerParam):
            logger.warning(f"[WARN] Param {key} is not a PointerParam")
            return

        parentScipionProtocolId, parentProtocol = self._getParentProtocolForPointer(
            mapper=mapper,
            projectId=projectId,
            parentId=parentId,
        )

        editableValue = value.get("editableValue") if isinstance(value, dict) else value

        if editableValue and "." in str(editableValue):
            _rawParentId, outputName = str(editableValue).split(".", 1)
            editableValue = f"{parentScipionProtocolId}.{outputName}"
        else:
            outputName = str(editableValue or "").strip()

        if outputName and not hasattr(parentProtocol, outputName):
            raise ValueError(
                "Parent protocol %s does not have output %s"
                % (parentScipionProtocolId, outputName)
            )

        pointer = getattr(protocol, key, None)

        if pointer is None or isinstance(pointer, str) or not hasattr(pointer, "set"):
            pointer = Pointer(parentProtocol, extended=outputName)
            setattr(protocol, key, pointer)
        else:
            pointer.set(parentProtocol)
            if outputName:
                pointer.setExtended(outputName)

        try:
            param.default.set(editableValue)
        except Exception:
            pass

    def saveProtocol(self, mapper, projectId, protocolId, protocolClassName, params, setToSave=True):
        errorList = []

        if not protocolId:
            protClass = self.currentProject.getDomain().getProtocols().get(protocolClassName)
            if protClass is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Protocol class not found: {protocolClassName}",
                )
            protocol = self.currentProject.newProtocol(protClass)
        else:
            protocol = self._getScipionProtocolForRuntime(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

        protectedParams = ['_objComment', '_useQueue', '_prerequisites', 'gpuList', 'numberOfThreads']
        for paramName in protectedParams:
            protVar = getattr(protocol, paramName, None)
            if protVar is None or paramName not in params:
                continue

            value = params[paramName]
            try:
                protVar.set(value)
            except Exception:
                setattr(protocol, paramName, value)

        for key, value in params.items():
            param = protocol.getParam(key)
            if param is None:
                logger.warning("[WARN] Param not found: %s", key)
                continue

            if isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
                continue

            try:
                castedValue = self.castParamValue(param, value)
                errors = param.validate(castedValue) if hasattr(param, "validate") else []
                if errors:
                    errorList += ['**' + param.label.get() + '** ' + error for error in errors]

                param.set(castedValue)
                protocol.setAttributeValue(key, castedValue)

                if key == "runName":
                    protocol.runName.set(castedValue)
                    # protocol.setObjLabel(castedValue)

                logger.info("[INFO] Set param %s = %s", key, castedValue)
            except Exception as e:
                cleaned = re.sub(r'[^A-Za-z0-9\s+\-*/=<>!&|^%()\[\]{}_,.;:]', '', str(e))
                errorList.append('**' + param.label.get() + '** ' + cleaned)

        errorList += self.applyParamsToProtocol(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
            params=params,
        )

        # Persist protocol in Scipion always.
        # The setToSave flag only controls whether we also sync the graph to PostgreSQL now.
        try:
            isNewProtocol = not protocolId

            if isNewProtocol:
                # Important in PostgreSQL runtime mode:
                # A new protocol can already have an objId assigned by the runtime mapper,
                # but that does not mean it exists as a root object in Scipion's legacy SQLite.
                # _setupProtocol is the correct path for new protocols.
                self.currentProject._setupProtocol(protocol)
            else:
                self.currentProject._storeProtocol(protocol)

        except Exception as e:
            logger.exception(
                "Failed to persist protocol in Scipion. projectId=%s protocolId=%s protocolClassName=%s",
                projectId,
                protocolId,
                protocolClassName,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist protocol in Scipion: {e}",
            )

        if self._currentProjectUsesPostgresqlRuntimeMapper():
            try:
                dependencySync = self.syncPostgresqlRuntimeProtocolInputsAndDependencies(
                    mapper=mapper,
                    projectId=projectId,
                    protocol=protocol,
                    params=params,
                )

                logger.info(
                    "Synced PostgreSQL runtime protocol inputs/dependencies after save. "
                    "projectId=%s protocolId=%s sync=%s",
                    projectId,
                    getattr(protocol, "getObjId", lambda: protocolId)(),
                    dependencySync,
                )


            except Exception as e:
                logger.exception(
                    "Failed to sync PostgreSQL runtime protocol inputs/dependencies after save. "
                    "projectId=%s protocolId=%s",
                    projectId,
                    getattr(protocol, "getObjId", lambda: protocolId)(),
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to sync PostgreSQL runtime protocol dependencies after save: {e}",
                )

        if setToSave and not self._currentProjectUsesPostgresqlRuntimeMapper():
            try:
                self.syncProjectProtocolsAndDependencies(
                    mapper,
                    projectId,
                    refresh=True,
                    checkPid=True,
                )
            except Exception as e:
                logger.exception(
                    "Failed to sync protocol graph after save. projectId=%s protocolId=%s protocolClassName=%s",
                    projectId,
                    getattr(protocol, "getObjId", lambda: protocolId)(),
                    protocolClassName,
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Protocol was saved in Scipion but graph sync to PostgreSQL failed: {e}",
                )

        elif setToSave:
            logger.info(
                "Skipping legacy graph sync after PostgreSQL runtime save. "
                "projectId=%s protocolId=%s protocolClassName=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
                protocolClassName,
            )

        return protocol, errorList

    def listProtocolStepsService(self, mapper, projectId: int, protocolId: int):
        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if self._currentProjectUsesPostgresqlRuntimeMapper():
            self.syncPostgresqlRuntimeProtocol(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                registerOutputs=False,
            )

        return mapper.listProtocolSteps(projectId, scipionProtocolId)

    def updateProtocolStepStatusService(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            stepIndex: int,
            stepStatus: str,
    ):
        statusMap = {
            "new": STATUS_NEW,
            "finished": STATUS_FINISHED,
        }

        normalizedStatus = str(stepStatus or "").strip().lower()
        if normalizedStatus not in statusMap:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid step status. Allowed values: new, finished",
            )

        targetStatus = statusMap[normalizedStatus]

        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = self._getScipionProtocolByRuntimeId(scipionProtocolId)

        try:
            steps = protocol.loadSteps() or []
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load protocol steps: {e}",
            )

        targetStep = None
        for fallbackIndex, step in enumerate(steps, start=1):
            rawIndex = getattr(step, "_index", None) or fallbackIndex
            try:
                if int(rawIndex) == int(stepIndex):
                    targetStep = step
                    break
            except Exception:
                continue

        if targetStep is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Step not found: {stepIndex}",
            )

        stepObjId = None
        try:
            stepObjId = targetStep.getObjId()
        except Exception:
            stepObjId = None

        if stepObjId is None:
            stepObjId = getattr(targetStep, "_objId", None)
            try:
                if hasattr(stepObjId, "get"):
                    stepObjId = stepObjId.get()
            except Exception:
                pass

        if stepObjId is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not resolve object id for step {stepIndex}",
            )

        try:
            protocol._updateSteps(
                lambda step: step.setStatus(targetStatus),
                where="id='%s'" % stepObjId,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update Scipion step status: {e}",
            )

        row = mapper.updateProtocolStepStatus(
            projectId=projectId,
            protocolId=scipionProtocolId,
            stepIndex=stepIndex,
            stepStatus=targetStatus,
        )

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol step not found in PostgreSQL: {stepIndex}",
            )

        return row

    def launchProtocol(self, mapper, projectId, protocolId, protocolClassName, params, executeMode):
        """
        Save, validate, and execute a protocol action.
        Supported execute modes: launch, restart, schedule, stop.
        """
        modeAliases = {
            None: "launch",
            "resume": "launch",
        }
        executeMode = modeAliases.get(executeMode, executeMode)
        allowedModes = {"launch", "restart", "schedule", "stop"}
        if executeMode not in allowedModes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown executeMode: {executeMode}",
            )

        if executeMode == "stop":
            try:
                self.stopProtocol(mapper, projectId, [protocolId])

                return self.syncProjectProtocolsAndDependencies(
                    mapper,
                    projectId,
                    refresh=True,
                    checkPid=True,
                )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(e),
                ) from e

        protocol, errors = self.saveProtocol(
            mapper,
            projectId,
            protocolId,
            protocolClassName,
            params,
            setToSave=False,
        )

        usingPostgresqlRuntime = self._currentProjectUsesPostgresqlRuntimeMapper()

        # if usingPostgresqlRuntime:
        #
        #
        #     if postgresqlLaunchPointerReport.get("errors"):
        #         raise HTTPException(
        #             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        #             detail=(
        #                     "Failed to prepare PostgreSQL runtime pointer outputs for launch: %s"
        #                     % postgresqlLaunchPointerReport.get("errors")
        #             ),
        #         )

        if protocol.useQueue():
            queueName = params.get("_queueName")
            queueParams = params.get("_queueParams")
            protocol.setQueueParams([queueName, queueParams])

        try:
            validationErrors = protocol._validate()
            if validationErrors:
                errors += validationErrors
        except Exception:
            logger.exception("Unexpected error during protocol validation")
            errors += [
                "**Other errors:** There are other validation errors that may be resolved by correcting the previous ones."
            ]

        if errors:
            if not usingPostgresqlRuntime:
                try:
                    self.syncProjectProtocolsAndDependencies(
                        mapper,
                        projectId,
                        refresh=True,
                        checkPid=True,
                    )
                except Exception:
                    logger.exception(
                        "Failed to sync protocol graph after validation errors. projectId=%s protocolId=%s",
                        projectId,
                        getattr(protocol, "getObjId", lambda: protocolId)(),
                    )
            else:
                logger.info(
                    "Skipping legacy graph sync after PostgreSQL runtime validation errors. "
                    "projectId=%s protocolId=%s errors=%s",
                    projectId,
                    getattr(protocol, "getObjId", lambda: protocolId)(),
                    errors,
                )

            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=errors,
            )

        if not usingPostgresqlRuntime:
            self.syncProjectProtocolsAndDependencies(
                mapper,
                projectId,
                refresh=True,
                checkPid=False,
            )
        else:
            logger.info(
                "Skipping legacy pre-launch graph sync for PostgreSQL runtime protocol. "
                "projectId=%s protocolId=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
            )

        try:
            if executeMode == "schedule":
                self.currentProject.scheduleProtocol(protocol)
            else:
                modeToRunMode = {
                    "launch": MODE_RESUME,
                    "restart": MODE_RESTART,
                }
                runMode = modeToRunMode[executeMode]
                protocol.runMode.set(runMode)

                if executeMode == "restart":
                    cleanupInfo = self._deletePersistedProtocolOutputsForRuntimeProtocolsFromPostgresql(
                        mapper=mapper,
                        projectId=projectId,
                        protocols=[protocol],
                    )
                    logger.info(
                        "Deleted persisted protocol outputs before restart. projectId=%s protocolId=%s cleanup=%s",
                        projectId,
                        getattr(protocol, "getObjId", lambda: protocolId)(),
                        cleanupInfo,
                    )

                self.currentProject.launchProtocol(protocol)

                if usingPostgresqlRuntime:
                    launchedProtocolId = getattr(protocol, "getObjId", lambda: protocolId)()

                    try:
                        protocol.setStatus(STATUS_LAUNCHED)
                    except Exception:
                        statusAttr = getattr(protocol, "status", None)
                        setter = getattr(statusAttr, "set", None)
                        if callable(setter):
                            setter(STATUS_LAUNCHED)

                    self.currentProject._storeProtocol(protocol)

                    return {
                        "protocols": 1,
                        "dependencies": 0,
                        "postgresqlRuntimeLaunch": True,
                        "launchAccepted": True,
                        "protocolId": str(launchedProtocolId),
                        "protocolStatus": STATUS_LAUNCHED,
                    }

            if usingPostgresqlRuntime:
                try:
                    syncResult = self.syncPostgresqlRuntimeProtocol(
                        mapper=mapper,
                        projectId=projectId,
                        protocolId=getattr(protocol, "getObjId", lambda: protocolId)(),
                        registerOutputs=False,
                    )
                except Exception:
                    logger.exception(
                        "Failed to sync PostgreSQL runtime protocol immediately after launch. "
                        "projectId=%s protocolId=%s",
                        projectId,
                        getattr(protocol, "getObjId", lambda: protocolId)(),
                    )
                    syncResult = {
                        "protocols": 1,
                        "dependencies": 0,
                        "postgresqlRuntimeSync": False,
                        "syncError": "Immediate runtime sync failed",
                    }

                syncResult.update({
                    "postgresqlRuntimeLaunch": True,
                    "launchAccepted": True,
                    "syncSkipped": False,
                    "syncSkippedReason": None,
                })

                return syncResult

            return self.syncProjectProtocolsAndDependencies(
                mapper,
                projectId,
                refresh=True,
                checkPid=True,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(
                "Failed to sync protocol graph after execute. projectId=%s protocolId=%s executeMode=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
                executeMode,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{e}",
            )

    def findViewersWeb(self, protocol):
        # TODO: Find viewers...
        """Stub for finding web-based viewers (to be implemented)."""
        return {}

    def getResourceIcon(self, icon):
        """Return absolute path to an icon resource."""
        return os.path.join(self.currentProject.getPath(), icon)

    def getResourceLogo(self, logo):
        """Return absolute path to a logo resource."""
        return os.path.join(self.currentProject.getPath(), logo)

    def PreprocessParamForm(self, param, paramName, wizards, viewerDict, visualize, protVar):
        """
        Serialize a protocol parameter into a dict, handling scalar, pointer, and multipointer types.
        """
        try:
            paramDict = {}
            paramValue = ''

            from pyworkflow.protocol import MultiPointerParam, PointerParam, RelationParam

            # relationParam: keep current behavior (empty dict)
            if isinstance(param, RelationParam):
                return {}, None

            paramDict["name"] = paramName
            wizardItems = wizards.get(paramName, []) if wizards else []
            paramDict["hasWizard"] = bool(wizardItems)
            paramDict["wizards"] = wizardItems
            paramDict["wizard"] = wizardItems[0] if wizardItems else None

            # publicAttributes
            for name, value in param.getAttributes():
                paramDict[name] = value.get()

            # protectedAttributes
            for name, value in vars(param).items():
                if name == 'choices' or name == 'gpuList':
                    paramDict[name] = serializeToJson(value)

            paramClass = param.__class__.__name__
            if paramClass == 'LabelParam':
                paramClass = 'Label'

            # if paramClass == 'PathParam':
            #     paramDict["pointerClass"] = "StarFile"
            paramDict["paramClass"] = paramClass

            if protVar is not None:
                if isinstance(param, MultiPointerParam):
                    valueList = []
                    for pointer in protVar:
                        value = None

                        try:
                            targetObj = pointer.get()
                        except Exception:
                            targetObj = None

                        try:
                            extended = pointer.getExtended()
                        except Exception:
                            extended = None

                        if isinstance(targetObj, str):
                            value = targetObj

                        elif targetObj is not None:
                            try:
                                parentId = targetObj.getObjParentId()
                                value = "%s.%s" % (parentId, extended) if extended else None
                            except Exception:
                                value = None

                        valueList.append(value)

                    paramValue = valueList
                    paramDict["readOnly"] = True


                elif isinstance(param, PointerParam):
                    parentId = None
                    paramValue = None
                    try:
                        targetObj = protVar.get() if protVar is not None else None
                    except Exception:
                        targetObj = None
                    try:
                        objValue = protVar.getObjValue() if protVar is not None else None
                    except Exception:
                        objValue = None
                    try:
                        extended = protVar.getExtended() if protVar is not None else None
                    except Exception:
                        extended = None

                    if isinstance(targetObj, str):
                        # PostgreSQL runtime pointer can arrive as a raw value:
                        #   "1.outputTSMovies"
                        parentIdText, outputName = self._splitPointerValue(targetObj)
                        if parentIdText:
                            try:
                                parentId = int(parentIdText)
                            except Exception:
                                parentId = parentIdText

                        if outputName and not extended:
                            extended = outputName

                        paramValue = targetObj

                    elif targetObj is not None:
                        # Normal Scipion pointer: protVar.get() returns the pointed output object.
                        try:
                            parentId = targetObj.getObjParentId()
                        except Exception:
                            parentId = None
                        if parentId is None and objValue is not None:
                            try:
                                parentId = objValue.getObjId()
                            except Exception:
                                parentId = None

                        paramValue = "%s.%s" % (parentId, extended) if parentId is not None and extended else ""

                    elif objValue is not None:
                        # Pointer object exists but target output is not resolved.
                        try:
                            parentId = objValue.getObjId()
                        except Exception:
                            parentId = None
                        paramValue = "%s.%s" % (parentId, extended) if parentId is not None and extended else ""
                    else:
                        paramValue = None

                    if parentId is not None:
                        paramDict["parentId"] = parentId

                    paramDict["readOnly"] = True
                else:
                    paramValue = protVar.get() if protVar.get() is not None else None

            return paramDict, paramValue

        except Exception as ex:
            logger.error("ERROR with param: " + paramName)
            raise ex

    def _runJsonSubprocess(self, code: str, operationName: str) -> Dict[str, Any]:
        startMarker = "__SCIPION_JSON_START__"
        endMarker = "__SCIPION_JSON_END__"

        code = textwrap.dedent(code).strip()

        wrappedCode = "\n".join(
            [
                "import json",
                "import sys",
                "",
                code,
                "",
                "try:",
                "    _scipionPayload",
                "except NameError:",
                '    raise RuntimeError("Subprocess code did not define _scipionPayload")',
                "",
                f'sys.stdout.write("{startMarker}\\n")',
                "sys.stdout.write(json.dumps(_scipionPayload))",
                f'sys.stdout.write("\\n{endMarker}\\n")',
                "sys.stdout.flush()",
            ]
        )

        projectRoot = Path(__file__).resolve().parents[4]

        env = os.environ.copy()
        existingPythonPath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(projectRoot) + (os.pathsep + existingPythonPath if existingPythonPath else "")

        res = subprocess.run(
            [sys.executable, "-c", wrappedCode],
            cwd=str(projectRoot),
            env=env,
            capture_output=True,
            text=True,
        )

        stdout = (res.stdout or "").strip()
        stderr = (res.stderr or "").strip()

        if res.returncode != 0:
            raise RuntimeError(
                f"{operationName} failed in subprocess.\n"
                f"Return code: {res.returncode}\n"
                f"STDOUT:\n{stdout}\n\n"
                f"STDERR:\n{stderr}"
            )

        startIndex = stdout.find(startMarker)
        endIndex = stdout.find(endMarker)

        if startIndex == -1 or endIndex == -1:
            raise RuntimeError(
                f"{operationName} did not return a valid JSON payload block.\n"
                f"STDOUT:\n{stdout}\n\n"
                f"STDERR:\n{stderr}"
            )

        payload = stdout[startIndex + len(startMarker):endIndex].strip()

        if not payload:
            raise RuntimeError(
                f"{operationName} returned an empty JSON payload.\n"
                f"STDOUT:\n{stdout}\n\n"
                f"STDERR:\n{stderr}"
            )

        try:
            return json.loads(payload)
        except json.JSONDecodeError as ex:
            raise RuntimeError(
                f"{operationName} returned invalid JSON.\n"
                f"Payload:\n{payload}\n\n"
                f"STDOUT:\n{stdout}\n\n"
                f"STDERR:\n{stderr}"
            ) from ex

    def _buildProtocolsTreeInSubprocess(self) -> Dict[str, Any]:
        code = """
    import contextlib
    import os
    import sys

    with contextlib.redirect_stdout(sys.stderr):
        from pyworkflow import Config
        from pyworkflow.gui.project.viewprotocols_extra import ProtocolTreeConfig
        from app.utils.scipion_helper import serializeToJson

        Config.setDomain("pwem")
        domain = Config.getDomain()

        protConf = os.path.join(Config.SCIPION_LOCAL_CONFIG, Config.SCIPION_PROTOCOLS)
        tree = ProtocolTreeConfig.load(domain, protConf)
        _scipionPayload = serializeToJson(tree)
    """

        return self._runJsonSubprocess(
            code=code,
            operationName="Build protocols tree",
        )

    def getProtocols(self, mapper: PostgresqlFlatMapper, projectId: int, currentUser) -> Optional[dict]:
        # getProtocols
        _invalidateProtocolsTreeCacheIfNeeded()

        cacheKey = "protocolsTree"
        with _protocolsTreeLock:
            cached = _protocolsTreeCache.get(cacheKey)
            if cached is not None:
                tree = copy.deepcopy(cached)
                self.walkAndReplaceProtocols(tree, self.getProtocolName)
                return tree

        # computeFreshTreeOncePerRevision
        protocolsTree = self._buildProtocolsTreeInSubprocess()

        with _protocolsTreeLock:
            _protocolsTreeCache[cacheKey] = protocolsTree

        tree = copy.deepcopy(protocolsTree)
        self.walkAndReplaceProtocols(tree, self.getProtocolName)
        return tree

    def replaceDefaultProtocolText(self, node: dict, resolverFn):
        # Determine type and extract text, tag, and children
        if isinstance(node, dict):
            text = node.get("text")
            tag = node.get("tag")
            children = node.get("childs", [])
        else:
            text = getattr(node, "text", None)
            tag = getattr(node, "tag", None)
            children = getattr(node, "childs", [])

        # Replace text if conditions are met
        if text == "default" and tag == "protocol":
            newText = resolverFn(node)
            if newText:
                if isinstance(node, dict):
                    node["text"] = newText
                else:
                    setattr(node, "text", newText)

        # Recursively process children
        for child in children:
            self.replaceDefaultProtocolText(child, resolverFn)

    def walkAndReplaceProtocols(self, data: dict, resolverFn):
        """
        Walk through the entire JSON/tree structure and replace 'default' texts for protocol nodes.

        Parameters:
        - data: the root of the tree (can be a dictionary or a list of nodes)
        - resolverFn: a function to determine the new text for 'default' protocol nodes
        """
        if isinstance(data, dict):
            # Iterate over key/value pairs in a dictionary
            for key, value in data.items():
                if isinstance(value, dict):
                    self.replaceDefaultProtocolText(value, resolverFn)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            self.replaceDefaultProtocolText(item, resolverFn)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    self.replaceDefaultProtocolText(item, resolverFn)

    def _getProtocolClassForTreeLabel(self, protClassName: str):
        try:
            if self.currentProject is not None:
                domain = self.currentProject.getDomain()
                protocolClass = domain.getProtocols().get(protClassName, None)
                if protocolClass is not None:
                    return protocolClass
        except Exception:
            pass

        try:
            return Config.getDomain().getProtocols().get(protClassName, None)
        except Exception:
            logger.warning(
                "Protocol className '%s' not found while resolving protocol tree label.",
                protClassName,
            )
            return None

    def getProtocolName(self, node):
        text = node.get('text')
        if text:
            value = node.get('value') if node.get('value') is not None else text
            protClassName = value.split('.')[-1]
            prot = self._getProtocolClassForTreeLabel(protClassName)

            if node.get('tag') == 'protocol' and text == 'default':
                if prot is None:
                    logger.warning("Protocol className '%s' not found!!!. \n"
                                   "Fix your config/protocols.conf configuration."
                                   % protClassName)
                    return

                text = prot.getClassLabel()
                return text

        return 'default'

    def _resolvePostgresqlProjectPathForFilesystem(
            self,
            mapper,
            projectId: int,
    ) -> Optional[str]:
        if mapper is None or not hasattr(mapper, "db"):
            return None

        try:
            row = mapper.db.fetchOne(
                """
                SELECT name
                  FROM projects
                 WHERE id = %s
                """,
                (projectId,),
            )
        except Exception:
            logger.debug(
                "Could not resolve project path from PostgreSQL. projectId=%s",
                projectId,
                exc_info=True,
            )
            return None

        if not row:
            return None

        rawPath = row.get("name") if isinstance(row, dict) else row[0]
        if not rawPath:
            return None

        try:
            path = self._normalizeProjectPath(str(rawPath))
        except Exception:
            path = str(rawPath)

        if not os.path.isabs(path):
            try:
                path = self.manager.getProjectPath(path)
            except Exception:
                pass

        return os.path.realpath(path)

    def _resolvePostgresqlProtocolRunPath(
            self,
            mapper,
            projectId: int,
            scipionProtocolId: Union[int, str],
    ) -> Optional[str]:
        projectPath = self._resolvePostgresqlProjectPathForFilesystem(
            mapper=mapper,
            projectId=projectId,
        )
        if not projectPath:
            return None

        runsPath = os.path.join(projectPath, "Runs")
        if not os.path.isdir(runsPath):
            return None

        runtimeIdText = str(scipionProtocolId).strip()
        runtimeIdInt = None
        try:
            runtimeIdInt = int(runtimeIdText)
        except Exception:
            pass

        matches: List[str] = []

        try:
            for entry in os.scandir(runsPath):
                if not entry.is_dir():
                    continue

                name = entry.name

                if name.startswith("%s_" % runtimeIdText):
                    matches.append(entry.path)
                    continue

                if runtimeIdInt is not None:
                    match = re.match(r"^0*(\d+)_", name)
                    if match and int(match.group(1)) == runtimeIdInt:
                        matches.append(entry.path)
                        continue
        except Exception:
            logger.debug(
                "Could not scan Runs folder for protocol logs. runsPath=%s",
                runsPath,
                exc_info=True,
            )
            return None

        if not matches:
            return None

        return sorted(matches)[0]

    @staticmethod
    def _firstExistingLogPath(
            protocolPath: str,
            candidates: List[str],
    ) -> Optional[str]:
        for candidate in candidates:
            path = os.path.join(protocolPath, candidate)
            if os.path.exists(path):
                return path

        return None

    def _resolvePostgresqlProtocolLogPaths(
            self,
            mapper,
            projectId: int,
            protocolId: int,
    ) -> Optional[Dict[str, Any]]:
        if mapper is None:
            return None

        try:
            scipionProtocolId = self._resolveScipionProtocolId(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
        except Exception:
            logger.debug(
                "Could not resolve PostgreSQL protocol id for logs. projectId=%s protocolId=%s",
                projectId,
                protocolId,
                exc_info=True,
            )
            return None

        protocolPath = self._resolvePostgresqlProtocolRunPath(
            mapper=mapper,
            projectId=projectId,
            scipionProtocolId=scipionProtocolId,
        )
        if not protocolPath:
            return None

        logCandidates = {
            "stdout": [
                "logs/run.stdout",
                "logs/stdout.log",
                "logs/stdout.txt",
                "run.stdout",
                "stdout.log",
                "stdout.txt",
            ],
            "stderr": [
                "logs/run.stderr",
                "logs/stderr.log",
                "logs/stderr.txt",
                "run.stderr",
                "stderr.log",
                "stderr.txt",
            ],
            "schedule": [
                "logs/schedule.log",
                "logs/schedule.txt",
                "logs/run.schedule",
                "schedule.log",
                "schedule.txt",
                "run.schedule",
            ],
        }

        paths = {
            channelId: self._firstExistingLogPath(protocolPath, candidates)
            for channelId, candidates in logCandidates.items()
        }

        # If we cannot find any known log file, do not guess. Let runtime fallback
        # resolve the exact Scipion log paths.
        if not any(paths.values()):
            return None

        return {
            "protocolId": scipionProtocolId,
            "protocolPath": protocolPath,
            "paths": paths,
        }

    def _ensureRuntimeProjectForLogs(
            self,
            mapper,
            projectId: int,
            currentUser: Optional[dict],
    ) -> None:
        if getattr(self, "currentProject", None) is not None:
            return

        if currentUser is None:
            return

        self.getProjectById(
            mapper,
            projectId,
            currentUser,
            refresh=False,
            checkPid=False,
        )

    @staticmethod
    def _buildProtocolLogChannel(
            channelId: str,
            label: str,
            order: int,
            filePath: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "id": channelId,
            "label": label,
            "order": order,
        }

    def _buildProtocolLogChannelsPayload(
            self,
            projectId: int,
            protocolId: Union[int, str],
            logPaths: Dict[str, Optional[str]],
    ) -> Dict[str, Any]:
        return {
            "projectId": projectId,
            "protocolId": int(protocolId),
            "channels": [
                self._buildProtocolLogChannel("stdout", "Output", 1, logPaths.get("stdout")),
                self._buildProtocolLogChannel("stderr", "Errors", 2, logPaths.get("stderr")),
                self._buildProtocolLogChannel("schedule", "Schedule", 3, logPaths.get("schedule")),
            ],
        }

    @staticmethod
    def _normalizeProtocolLogOffsets(rawOffsets: Dict[str, int]) -> Dict[str, int]:
        if not isinstance(rawOffsets, dict):
            return {"stdout": 0, "stderr": 0, "schedule": 0}

        keyMap = {
            "stdout": "stdout",
            "stdoutLog": "stdout",
            "out": "stdout",
            "stderr": "stderr",
            "stderrLog": "stderr",
            "err": "stderr",
            "schedule": "schedule",
            "scheduleLog": "schedule",
        }

        normalized = {"stdout": 0, "stderr": 0, "schedule": 0}
        for key, value in rawOffsets.items():
            canonical = keyMap.get(str(key), None)
            if canonical is None:
                continue

            try:
                normalized[canonical] = max(0, int(value))
            except Exception:
                normalized[canonical] = 0

        return normalized

    @staticmethod
    def _readProtocolLogChunk(
            filePath: Optional[str],
            startOffset: int,
            maxBytes: Optional[int] = 65536,
            maxLines: Optional[int] = 2000,
    ) -> Dict[str, Any]:
        if not filePath or not os.path.exists(filePath):
            return {
                "content": "",
                "offset": int(startOffset or 0),
            }

        try:
            sizeBytes = int(os.path.getsize(filePath))
        except Exception:
            sizeBytes = 0

        safeOffset = int(startOffset or 0)
        if safeOffset < 0:
            safeOffset = 0

        if safeOffset > sizeBytes:
            safeOffset = 0

        bytesCap = None if maxBytes is None else max(1, int(maxBytes))
        linesCap = None if maxLines is None else max(1, int(maxLines))

        contentParts: List[str] = []
        bytesRead = 0
        linesRead = 0

        try:
            with open(filePath, "rb") as handle:
                handle.seek(safeOffset)

                while True:
                    if linesCap is not None and linesRead >= linesCap:
                        break
                    if bytesCap is not None and bytesRead >= bytesCap:
                        break

                    posBefore = handle.tell()
                    lineBytes = handle.readline()
                    if not lineBytes:
                        break

                    if bytesCap is not None and (bytesRead + len(lineBytes)) > bytesCap:
                        handle.seek(posBefore)
                        break

                    contentParts.append(lineBytes.decode("utf-8", errors="ignore"))
                    bytesRead += len(lineBytes)
                    linesRead += 1

                newOffset = handle.tell()

        except Exception as e:
            return {
                "content": "",
                "offset": safeOffset,
                "error": str(e),
            }

        return {
            "content": "".join(contentParts),
            "offset": int(newOffset),
        }

    def _pollProtocolLogPaths(
            self,
            projectId: int,
            protocolId: Union[int, str],
            logPaths: Dict[str, Optional[str]],
            offsets: Dict[str, int],
            maxBytes: Optional[int] = 65536,
            maxLines: Optional[int] = 2000,
    ) -> Dict[str, Any]:
        normalizedOffsets = self._normalizeProtocolLogOffsets(offsets or {})

        return {
            "projectId": projectId,
            "protocolId": int(protocolId),
            "channels": {
                "stdout": self._readProtocolLogChunk(
                    logPaths.get("stdout"),
                    normalizedOffsets.get("stdout", 0),
                    maxBytes=maxBytes,
                    maxLines=maxLines,
                ),
                "stderr": self._readProtocolLogChunk(
                    logPaths.get("stderr"),
                    normalizedOffsets.get("stderr", 0),
                    maxBytes=maxBytes,
                    maxLines=maxLines,
                ),
                "schedule": self._readProtocolLogChunk(
                    logPaths.get("schedule"),
                    normalizedOffsets.get("schedule", 0),
                    maxBytes=maxBytes,
                    maxLines=maxLines,
                ),
            },
        }

    def listProtocolLogChannelsService(
            self,
            projectId: int,
            protocolId: int,
            mapper=None,
            currentUser: Optional[dict] = None,
    ):
        """
        Return available log channels for a protocol, including paths and basic file stats.
        """
        pgLogs = self._resolvePostgresqlProtocolLogPaths(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )
        if pgLogs is not None:
            return self._buildProtocolLogChannelsPayload(
                projectId=projectId,
                protocolId=pgLogs["protocolId"],
                logPaths=pgLogs["paths"],
            )

        self._ensureRuntimeProjectForLogs(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
        )

        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = self._getScipionProtocolByRuntimeId(scipionProtocolId)

        # Resolve log paths from Scipion protocol object
        stdoutPath = protocol.getStdoutLog() if hasattr(protocol, "getStdoutLog") else None
        stderrPath = protocol.getStderrLog() if hasattr(protocol, "getStderrLog") else None
        schedulePath = protocol.getScheduleLog() if hasattr(protocol, "getScheduleLog") else None

        def buildChannel(channelId: str, label: str, order, filePath: Optional[str]) -> Dict[str, Any]:
            # Build a stable channel descriptor
            exists = bool(filePath) and os.path.exists(filePath)
            sizeBytes = 0
            mtimeUtc = None

            if exists:
                try:
                    sizeBytes = int(os.path.getsize(filePath))
                except Exception:
                    sizeBytes = 0
                try:
                    ts = os.path.getmtime(filePath)
                    mtimeUtc = datetime.utcfromtimestamp(ts).isoformat() + "Z"
                except Exception:
                    mtimeUtc = None

            return {
                "id": channelId,
                "label": label,
                "order": order,
                # "path": filePath or "",
                # "exists": exists,
                # "sizeBytes": sizeBytes,
                # "mtimeUtc": mtimeUtc,
            }

        channels = [
            buildChannel("stdout", "Output", 1, stdoutPath),
            buildChannel("stderr", "Errors", 2, stderrPath),
            buildChannel("schedule", "Schedule", 3, schedulePath),
        ]

        # Keep a consistent list but allow UI to filter by exists==True
        return {
            "projectId": projectId,
            "protocolId": int(scipionProtocolId),
            "channels": channels,
        }

    def pollProtocolLogsService(
            self,
            projectId: int,
            protocolId: int,
            offsets: Dict[str, int],
            maxBytes: Optional[int] = 65536,
            maxLines: Optional[int] = 2000,
            mapper=None,
            currentUser: Optional[dict] = None,
    ):
        """
        Incrementally read protocol logs from the given offsets, applying maxBytes and maxLines limits.
        """
        pgLogs = self._resolvePostgresqlProtocolLogPaths(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )
        if pgLogs is not None:
            return self._pollProtocolLogPaths(
                projectId=projectId,
                protocolId=pgLogs["protocolId"],
                logPaths=pgLogs["paths"],
                offsets=offsets,
                maxBytes=maxBytes,
                maxLines=maxLines,
            )

        self._ensureRuntimeProjectForLogs(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
        )

        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = self._getScipionProtocolByRuntimeId(scipionProtocolId)

        stdoutPath = protocol.getStdoutLog() if hasattr(protocol, "getStdoutLog") else None
        stderrPath = protocol.getStderrLog() if hasattr(protocol, "getStderrLog") else None
        schedulePath = protocol.getScheduleLog() if hasattr(protocol, "getScheduleLog") else None

        # Normalize incoming offsets keys to canonical channels
        def normalizeOffsets(rawOffsets: Dict[str, int]) -> Dict[str, int]:
            if not isinstance(rawOffsets, dict):
                return {"stdout": 0, "stderr": 0, "schedule": 0}

            keyMap = {
                "stdout": "stdout",
                "stdoutLog": "stdout",
                "out": "stdout",
                "stderr": "stderr",
                "stderrLog": "stderr",
                "err": "stderr",
                "schedule": "schedule",
                "scheduleLog": "schedule",
            }

            normalized = {"stdout": 0, "stderr": 0, "schedule": 0}
            for k, v in rawOffsets.items():
                canonical = keyMap.get(str(k), None)
                if canonical is None:
                    continue
                try:
                    normalized[canonical] = max(0, int(v))
                except Exception:
                    normalized[canonical] = 0
            return normalized

        normalizedOffsets = normalizeOffsets(offsets or {})

        def readChunk(filePath: Optional[str], startOffset: int) -> Dict[str, Any]:
            # Read a chunk with byte and line caps, keeping offset consistent (no partial lines)
            if not filePath:
                return {
                    # "exists": False,
                    # "path": "",
                    "content": "",
                    "offset": int(startOffset or 0),
                    # "resetOffset": False,
                    # "truncated": False,
                    # "bytesRead": 0,
                    # "linesRead": 0,
                    # "sizeBytes": 0,
                }

            if not os.path.exists(filePath):
                return {
                    # "exists": False,
                    # "path": filePath,
                    "content": "",
                    "offset": int(startOffset or 0),
                    # "resetOffset": False,
                    # "truncated": False,
                    # "bytesRead": 0,
                    # "linesRead": 0,
                    # "sizeBytes": 0,
                }

            try:
                sizeBytes = int(os.path.getsize(filePath))
            except Exception:
                sizeBytes = 0

            resetOffset = False
            safeOffset = int(startOffset or 0)
            if safeOffset < 0:
                safeOffset = 0

            # resetOffsetIfTruncated: if file was rotated/truncated, restart from 0
            if safeOffset > sizeBytes:
                safeOffset = 0
                resetOffset = True

            bytesCap = None if maxBytes is None else max(1, int(maxBytes))
            linesCap = None if maxLines is None else max(1, int(maxLines))

            contentParts: List[str] = []
            bytesRead = 0
            linesRead = 0

            try:
                with open(filePath, "rb") as f:
                    f.seek(safeOffset)

                    while True:
                        if linesCap is not None and linesRead >= linesCap:
                            break
                        if bytesCap is not None and bytesRead >= bytesCap:
                            break

                        posBefore = f.tell()
                        lineBytes = f.readline()
                        if not lineBytes:
                            break

                        # enforceByteCapWithoutPartialLine: do not return partial lines
                        if bytesCap is not None and (bytesRead + len(lineBytes)) > bytesCap:
                            f.seek(posBefore)
                            break

                        contentParts.append(lineBytes.decode("utf-8", errors="ignore"))
                        bytesRead += len(lineBytes)
                        linesRead += 1

                    newOffset = f.tell()

            except Exception as e:
                # ioReadError: surface error but keep a stable response shape
                return {
                    # "exists": True,
                    # "path": filePath,
                    "content": "",
                    "offset": safeOffset,
                    # "resetOffset": resetOffset,
                    # "truncated": False,
                    # "bytesRead": 0,
                    # "linesRead": 0,
                    # "sizeBytes": sizeBytes,
                    "error": str(e),
                }

            # truncatedMeansMoreDataAvailable: caller can poll again with returned offset
            truncated = False
            try:
                truncated = newOffset < int(os.path.getsize(filePath))
            except Exception:
                truncated = False

            return {
                # "exists": True,
                # "path": filePath,
                "content": "".join(contentParts),
                "offset": int(newOffset),
                # "resetOffset": resetOffset,
                # "truncated": bool(truncated),
                # "bytesRead": int(bytesRead),
                # "linesRead": int(linesRead),
                # "sizeBytes": int(sizeBytes),
            }

        stdoutRes = readChunk(stdoutPath, normalizedOffsets.get("stdout", 0))
        stderrRes = readChunk(stderrPath, normalizedOffsets.get("stderr", 0))
        scheduleRes = readChunk(schedulePath, normalizedOffsets.get("schedule", 0))

        return {
            "projectId": projectId,
            "protocolId": int(scipionProtocolId),
            "channels": {
                "stdout": stdoutRes,
                "stderr": stderrRes,
                "schedule": scheduleRes,
            },
        }

    def getProtocolLogs(
            self,
            projectId: int,
            protocolId: int,
            offset: int = 0,
            errOffset: int = 0,
            scheduleOffset: int = 0,
            mapper=None,
    ):
        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = self._getScipionProtocolByRuntimeId(scipionProtocolId)
        logPath = protocol.getStdoutLog()
        errLogPath = protocol.getStderrLog()
        scheduleLogPath = protocol.getScheduleLog()

        def normalizeOffset(value, filePath):
            safeOffset = max(0, int(value or 0))

            if filePath and os.path.exists(filePath):
                try:
                    fileSize = os.path.getsize(filePath)
                    if safeOffset > fileSize:
                        return 0
                except Exception:
                    pass

            return safeOffset

        offset = normalizeOffset(offset, logPath)
        errOffset = normalizeOffset(errOffset, errLogPath)
        scheduleOffset = normalizeOffset(scheduleOffset, scheduleLogPath)

        stdoutContent, stderrContent, scheduleContent = "", "", ""
        newOffsetOut, newOffsetErr, newOffsetSchedule = offset, errOffset, scheduleOffset

        # Handle stdout log
        if logPath and os.path.exists(logPath):
            with open(logPath, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(offset)
                stdoutContent = f.read()
                newOffsetOut = f.tell()

        # Handle stderr log
        if errLogPath and os.path.exists(errLogPath):
            with open(errLogPath, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(errOffset)
                stderrContent = f.read()
                newOffsetErr = f.tell()

        if scheduleLogPath and os.path.exists(scheduleLogPath):
            with open(scheduleLogPath, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(scheduleOffset)
                scheduleContent = f.read()
                newOffsetSchedule = f.tell()

        if not stdoutContent and not stderrContent and not scheduleContent and not (
                logPath and os.path.exists(logPath)
        ) and not (errLogPath and os.path.exists(errLogPath)) and not (scheduleLogPath and os.path.exists(scheduleLogPath)):
            raise HTTPException(status_code=404, detail="No logs found")

        return {
            "stdoutLog": stdoutContent,
            "stderrLog": stderrContent,
            "stdoutOffset": newOffsetOut,
            "stderrOffset": newOffsetErr,
            "scheduleLog": scheduleContent,
            "scheduleOffset": newOffsetSchedule,
        }

    @staticmethod
    def _buildProtocolMutationResult(message: str, **extra) -> Dict[str, Any]:
        errors = extra.get("errors", [])
        duplicated = extra.get("duplicated", {})
        result = dict(extra or {})

        result.update({
            "status": 1 if errors else 0,
            "errors": errors,
            "message": message,
            "duplicated": duplicated,
        })

        return result

    def renameProtocol(
            self,
            mapper,
            projectId: int,
            protocolId,
            newName,
            newComment,
    ):
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )
        if protocol is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol not found: {protocolId}",
            )

        try:
            protocol.runName.set(newName)
            protocol._objComment = newComment
            # protocol.setObjLabel(newName)
            self.currentProject._storeProtocol(protocol)
        except Exception as e:
            logger.exception(
                "Failed to rename protocol. protocolId=%s newName=%s",
                protocolId,
                newName,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to rename protocol: {e}",
            )

        return self._buildProtocolMutationResult("Protocol renamed successfully")

    def duplicateProtocol(self, mapper, projectId, protocols):
        protocolList = []
        sourceIds = []
        duplicated = []
        errors = []
        for item in protocols or []:
            protocolId = getattr(item, "id", None)
            if protocolId is None:
                continue
            sourceIds.append(protocolId)
            protocol = self._getScipionProtocolForRuntime(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

            protocolList.append(protocol)

        if not protocolList:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No valid protocols to duplicate",
            )

        try:
            protListResult = self.currentProject.copyProtocol(protocolList)
            for index, prot in enumerate(protListResult):
                protId = str(prot.getObjId())
                duplicated.append({"sourceId": sourceIds[index], "newId": protId})


        except Exception as e:
            protocolIds = [
                getattr(p, "getObjId", lambda: None)()
                for p in protocolList
            ]
            logger.exception("Failed to duplicate protocols. projectId=%s protocolIds=%s",
                             projectId, protocolIds,)

            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail=f"Failed to duplicate protocols: {e}",)

        try:
            syncResult = self.syncProjectProtocolsAndDependencies(
                mapper,
                projectId,
                refresh=True,
                checkPid=True,
            )
        except HTTPException:
            raise
        except Exception as e:
            errors.append("Failed to sync protocol graph after duplication. projectId=%s" %projectId)
            logger.exception(
                "Failed to sync protocol graph after duplication. projectId=%s",
                projectId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Protocols were duplicated in Scipion but graph sync to PostgreSQL failed: {e}",
            )

        return self._buildProtocolMutationResult(
            "Protocol was duplicated successfully",
            protocolsCount=int(syncResult.get("protocols", 0)),
            dependenciesCount=int(syncResult.get("dependencies", 0)),
            duplicated=duplicated,
            errors=errors,
        )

    def deleteProtocol(self, mapper, projectId, protocols: Any):
        try:
            protList = []

            for protocolId in protocols or []:
                protocol = self._getScipionProtocolForRuntime(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )
                protList.append(protocol)

            if not protList:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="No valid protocols to delete",
                )

            self.currentProject.deleteProtocol(*protList)
            mapper.deleteProtocol(projectId, protList)

            syncInfo = self.syncProjectProtocolsAndDependencies(
                mapper,
                projectId,
                refresh=True,
                checkPid=True,
            )

            return {
                "status": 0,
                "message": "Protocol deleted successfully",
                "protocolsCount": syncInfo.get("protocols"),
                "dependenciesCount": syncInfo.get("dependencies"),
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def restartProtocolAll(self, mapper, projectId: int, protocolId):
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        try:
            workflowProtocolList, _activeProtocolList = self.currentProject._getSubworkflow(protocol)
        except Exception as e:
            logger.exception(
                "Failed to resolve subworkflow for restart-all. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to resolve protocol subworkflow: {e}",
            )

        cleanupInfo = self._deletePersistedProtocolOutputsForRuntimeProtocolsFromPostgresql(
            mapper=mapper,
            projectId=projectId,
            protocols=workflowProtocolList,
        )
        logger.info(
            "Deleted persisted protocol outputs before restart-all. projectId=%s protocolId=%s cleanup=%s",
            projectId,
            protocolId,
            cleanupInfo,
        )

        errorList = []
        try:
            self.currentProject._restartWorkflow(errorList, workflowProtocolList)
        except Exception as e:
            logger.exception(
                "Failed to restart workflow subtree. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restart protocol subtree: {e}",
            )

        if errorList:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[str(e) for e in errorList],
            )

        return self._buildProtocolMutationResult(
            "Protocol subtree restarted successfully",
            postgresqlCleanup=cleanupInfo,
        )

    def continueProtocolAll(self, mapper, projectId, protocolId, currentUser):
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        try:
            workflowProtocolList, activeProtocolList = self.currentProject._getSubworkflow(protocol)
        except Exception as e:
            logger.exception(
                "Failed to resolve subworkflow for continue-all. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to resolve protocol subworkflow: {e}",
            )

        protocolsToResume = activeProtocolList or workflowProtocolList or []
        if not protocolsToResume:
            return self._buildProtocolMutationResult("No protocols to continue")

        for item in protocolsToResume:
            protocolToLaunch = item

            if not hasattr(protocolToLaunch, "runMode"):
                protocolToLaunch = self._getScipionProtocolForRuntime(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=item,
                )

            try:
                protocolToLaunch.runMode.set(MODE_RESUME)
            except Exception:
                logger.debug(
                    "Could not set MODE_RESUME before continue-all. projectId=%s protocolId=%s item=%s",
                    projectId,
                    protocolId,
                    getattr(protocolToLaunch, "getObjId", lambda: item)(),
                    exc_info=True,
                )

            try:
                self.currentProject.launchProtocol(protocolToLaunch)
            except Exception as e:
                logger.exception(
                    "Failed to continue protocol. projectId=%s protocolId=%s item=%s",
                    projectId,
                    protocolId,
                    getattr(protocolToLaunch, "getObjId", lambda: item)(),
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to continue protocol: {e}",
                )

        return self._buildProtocolMutationResult("Protocol subtree continued successfully")

    def resetProtocolFrom(self, mapper, projectId: int, protocolId):
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        try:
            workflowProtocolList, _activeProtocolList = self.currentProject._getSubworkflow(protocol)
        except Exception as e:
            logger.exception(
                "Failed to resolve subworkflow for reset-from. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to resolve protocol subworkflow: {e}",
            )

        cleanupInfo = self._deletePersistedProtocolOutputsForRuntimeProtocolsFromPostgresql(
            mapper=mapper,
            projectId=projectId,
            protocols=workflowProtocolList,
        )
        logger.info(
            "Deleted persisted protocol outputs before reset-from. projectId=%s protocolId=%s cleanup=%s",
            projectId,
            protocolId,
            cleanupInfo,
        )

        try:
            resetErrors = self.currentProject.resetWorkFlow(workflowProtocolList) or []
        except Exception as e:
            logger.exception(
                "Failed to reset workflow subtree. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to reset protocol subtree: {e}",
            )

        if resetErrors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[str(e) for e in resetErrors],
            )

        return self._buildProtocolMutationResult(
            "Protocol subtree reset successfully",
            postgresqlCleanup=cleanupInfo,
        )

    def stopProtocol(self, mapper, projectId: int, protocolIds):
        resolvedProtocols = []

        for protocolId in protocolIds or []:
            protocol = self._getScipionProtocolForRuntime(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
            resolvedProtocols.append(protocol)

        if not resolvedProtocols:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No valid protocols to stop",
            )

        try:
            for protocol in resolvedProtocols:
                self.currentProject.stopProtocol(protocol)
        except Exception as e:
            logger.exception(
                "Failed to stop protocols. projectId=%s protocolIds=%s",
                projectId,
                protocolIds,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to stop protocols: {e}",
            )

        return self._buildProtocolMutationResult("Protocol stopped successfully")

    def _isGlobalFsBrowserMode(self, protocolId: Union[int, str]) -> bool:
        return str(protocolId).strip() == "-1"

    def _getGlobalFsBrowserRoot(self) -> Path:
        raw = os.environ.get("SCIPION_IMPORT_BROWSER_ROOT", "/home")
        return Path(raw).expanduser().resolve()

    def _extractWorkflowJsonText(self, text: str) -> str:
        # extractWorkflowJsonText
        raw = str(text or "").strip()
        if not raw:
            return raw

        if raw.startswith("[") or raw.startswith("{"):
            return raw

        lines = raw.splitlines()

        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("[") or stripped.startswith("{"):
                return "\n".join(lines[index:]).strip()

        return raw

    def _sanitizeWorkflowHeaderValue(self, value: Any) -> str:
        # sanitizeWorkflowHeaderValue
        return (
            str(value or "")
            .replace("\r", " ")
            .replace("\n", " ")
            .replace("|", "/")
            .replace(";", " ")
            .strip()
        )

    def _buildWorkflowTemplateHeader(self, protocolList: List[Any]) -> str:
        # buildWorkflowTemplateHeader
        metadata = self._buildWorkflowPluginMetadata(protocolList)

        requiredPluginNames = [
            self._sanitizeWorkflowHeaderValue(name)
            for name in metadata.get("requiredPluginNames", [])
            if self._sanitizeWorkflowHeaderValue(name)
        ]

        lines = [
            "ScipionWeb metadata format: scipionweb.workflow.metadata",
            "ScipionWeb metadata version: 1",
            "ScipionWeb exported at UTC: %s" % self._sanitizeWorkflowHeaderValue(
                metadata.get("exportedAt", "")
            ),
            "Scipion required plugins: %s" % ", ".join(requiredPluginNames),
        ]

        return "\n".join(lines).rstrip() + "\n\n"

    def _extractRequiredPluginNamesFromWorkflowText(self, text: str) -> List[str]:
        # extractRequiredPluginNamesFromWorkflowText
        for line in str(text or "").splitlines():
            cleanLine = line.strip()

            if not cleanLine:
                continue

            if cleanLine.startswith("[") or cleanLine.startswith("{"):
                break

            match = re.match(
                r"^Scipion required plugins:\s*(.*)$",
                cleanLine,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            rawNames = match.group(1).strip()
            if not rawNames:
                return []

            names: List[str] = []
            seen: TypingSet[str] = set()

            for rawName in rawNames.split(","):
                name = rawName.strip()
                if not name or name in seen:
                    continue

                seen.add(name)
                names.append(name)

            return names

        return []

    def _decodeExportJsonPayload(self, rawExport: Any) -> Any:
        if isinstance(rawExport, str):
            text = rawExport.strip()
            if not text:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Scipion export returned empty content",
                )

            try:
                return json.loads(text)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Scipion export returned invalid JSON text: {e}",
                )

        if isinstance(rawExport, (list, dict)):
            return rawExport

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unsupported export payload returned by Scipion",
        )

    def _getProtocolPluginNameForExport(self, protocol: Any) -> str:
        try:
            plugin = protocol.getPlugin()
        except Exception:
            plugin = None

        if plugin is not None:
            try:
                name = plugin.getName()
                if name:
                    return str(name).strip()
            except Exception:
                pass

            try:
                moduleName = getattr(plugin, "__name__", None)
                if moduleName:
                    return str(moduleName).strip()
            except Exception:
                pass

        try:
            moduleName = protocol.__class__.__module__
            if moduleName:
                return str(moduleName).split(".")[0].strip()
        except Exception:
            pass

        return ""

    def _getProtocolClassNameForExport(self, protocol: Any) -> str:
        try:
            className = protocol.getClassName()
            if className:
                return str(className).strip()
        except Exception:
            pass

        try:
            return protocol.__class__.__name__
        except Exception:
            return ""

    def _getProtocolObjIdForExport(self, protocol: Any) -> str:
        try:
            objId = protocol.getObjId()
            if objId is not None:
                return str(objId).strip()
        except Exception:
            pass

        return ""

    def _buildWorkflowPluginMetadata(self, protocolList: List[Any]) -> Dict[str, Any]:
        protocolPlugins: List[Dict[str, str]] = []
        requiredPluginNames: List[str] = []
        seenPluginNames: TypingSet[str] = set()

        for protocol in protocolList or []:
            protocolId = self._getProtocolObjIdForExport(protocol)
            className = self._getProtocolClassNameForExport(protocol)
            pluginName = self._getProtocolPluginNameForExport(protocol)

            if pluginName and pluginName not in seenPluginNames:
                seenPluginNames.add(pluginName)
                requiredPluginNames.append(pluginName)

            protocolPlugins.append(
                {
                    "protocolId": protocolId,
                    "className": className,
                    "pluginName": pluginName,
                }
            )

        requiredPluginNames.sort()

        return {
            "format": "scipionweb.workflow.export",
            "version": 1,
            "requiredPluginNames": requiredPluginNames,
            "protocolPlugins": protocolPlugins,
            "exportedAt": datetime.utcnow().isoformat() + "Z",
        }

    def _buildWorkflowExportJsonContent(
            self,
            rawExport: Any,
            protocolList: List[Any],
    ) -> str:
        # buildWorkflowExportJsonContent
        jsonContent = self._normalizeExportJsonContent(rawExport)
        header = self._buildWorkflowTemplateHeader(protocolList)

        return header + jsonContent

    def _readWorkflowTemplateJsonPayload(self, workflowFile: Any) -> Optional[Any]:
        # readWorkflowTemplateJsonPayload
        try:
            path = Path(str(workflowFile)).expanduser().resolve()
        except Exception:
            return None

        if not path.exists() or not path.is_file():
            return None

        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            return None

        if not text:
            return None

        try:
            return json.loads(text)
        except Exception:
            return None

    def _isScipionWebWorkflowExportPayload(self, payload: Any) -> bool:
        # isScipionWebWorkflowExportPayload
        if not isinstance(payload, dict):
            return False

        metadata = payload.get("scipionWeb")
        if not isinstance(metadata, dict):
            return False

        return metadata.get("format") == "scipionweb.workflow.export" and "content" in payload

    def _getRequiredPluginNamesFromWorkflowPayload(self, payload: Dict[str, Any]) -> List[str]:
        # getRequiredPluginNamesFromWorkflowPayload
        metadata = payload.get("scipionWeb") or {}
        rawNames = metadata.get("requiredPluginNames") or []

        names: List[str] = []
        seen: TypingSet[str] = set()

        for rawName in rawNames:
            name = str(rawName or "").strip()
            if not name or name in seen:
                continue

            seen.add(name)
            names.append(name)

        return names

    def _getInstalledPluginNamesForWorkflowImport(self) -> TypingSet[str]:
        # getInstalledPluginNamesForWorkflowImport
        installedNames: TypingSet[str] = set()

        try:
            from app.backend.api.services.plugin_service import PluginService

            plugins = PluginService().getPlugins(forceRefresh=False)
            for plugin in plugins or []:
                if not isinstance(plugin, dict):
                    continue

                if not plugin.get("installed"):
                    continue

                for key in ("name", "pipName", "pluginName", "moduleName", "packageName"):
                    value = plugin.get(key)
                    if value:
                        installedNames.add(str(value).strip())
        except Exception:
            logger.debug("Could not load installed plugin names from PluginService", exc_info=True)

        try:
            domain = self.currentProject.getDomain()
            rawPlugins = getattr(domain, "getPlugins", lambda: {})() or {}

            if isinstance(rawPlugins, dict):
                for key, plugin in rawPlugins.items():
                    if key:
                        installedNames.add(str(key).strip())

                    try:
                        pluginName = plugin.getName()
                        if pluginName:
                            installedNames.add(str(pluginName).strip())
                    except Exception:
                        pass
        except Exception:
            logger.debug("Could not load installed plugin names from Scipion domain", exc_info=True)

        return {name for name in installedNames if name}

    def _isWorkflowPluginAvailable(
            self,
            pluginName: str,
            availabilityCache: Optional[Dict[str, bool]] = None,
    ) -> bool:
        # isWorkflowPluginAvailable
        name = str(pluginName or "").strip()
        if not name:
            return True

        if availabilityCache is not None and name in availabilityCache:
            return availabilityCache[name]

        available = False

        try:
            import importlib.util
            available = importlib.util.find_spec(name) is not None
        except Exception:
            available = False

        if not available:
            try:
                __import__(name)
                available = True
            except Exception:
                available = False

        if availabilityCache is not None:
            availabilityCache[name] = available

        return available

    def _getMissingWorkflowPluginNames(
            self,
            requiredPluginNames: List[str],
            availabilityCache: Optional[Dict[str, bool]] = None,
    ) -> List[str]:
        # getMissingWorkflowPluginNames
        missing: List[str] = []
        seen: TypingSet[str] = set()

        for rawPluginName in requiredPluginNames or []:
            pluginName = str(rawPluginName or "").strip()
            if not pluginName or pluginName in seen:
                continue

            seen.add(pluginName)

            if not self._isWorkflowPluginAvailable(
                    pluginName,
                    availabilityCache=availabilityCache,
            ):
                missing.append(pluginName)

        return missing

    def _validateWorkflowRequiredPlugins(
            self,
            requiredPluginNames: List[str],
            availabilityCache: Optional[Dict[str, bool]] = None,
    ) -> None:
        # validateWorkflowRequiredPlugins
        missing = self._getMissingWorkflowPluginNames(
            requiredPluginNames,
            availabilityCache=availabilityCache,
        )

        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Missing required plugins for workflow import: %s" % ", ".join(missing),
            )

    def _prepareWorkflowFileForImport(self, workflowFile: Any) -> Dict[str, Any]:
        # prepareWorkflowFileForImport
        payload = self._readWorkflowTemplateJsonPayload(workflowFile)

        # Backward compatibility with previous ScipionWeb wrapper exports.
        if self._isScipionWebWorkflowExportPayload(payload):
            assert isinstance(payload, dict)

            requiredPluginNames = self._getRequiredPluginNamesFromWorkflowPayload(payload)
            self._validateWorkflowRequiredPlugins(requiredPluginNames)

            content = payload.get("content")
            if not isinstance(content, (list, dict)):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid ScipionWeb workflow export: content must be a JSON list or object.",
                )

            sourcePath = Path(str(workflowFile)).expanduser().resolve()
            tempPath = sourcePath.parent / (
                ".scipionweb-import-%s.json" % uuid4().hex
            )

            try:
                tempPath.write_text(
                    json.dumps(content, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to prepare workflow import file: %s" % e,
                )

            return {
                "workflowFile": str(tempPath),
                "cleanupFile": str(tempPath),
                "wrapped": True,
                "hasScipionWebMetadata": True,
                "requiredPluginNames": requiredPluginNames,
            }

        requiredPluginNames: List[str] = []
        resolvedPath: Optional[Path] = None

        try:
            resolvedPath = Path(str(workflowFile)).expanduser().resolve()
        except Exception:
            resolvedPath = None

        if resolvedPath is not None and resolvedPath.exists() and resolvedPath.is_file():
            try:
                text = resolvedPath.read_text(encoding="utf-8")
                requiredPluginNames = self._extractRequiredPluginNamesFromWorkflowText(text)
            except Exception:
                requiredPluginNames = []

        self._validateWorkflowRequiredPlugins(requiredPluginNames)

        return {
            "workflowFile": str(resolvedPath) if resolvedPath is not None else workflowFile,
            "cleanupFile": None,
            "wrapped": False,
            "hasScipionWebMetadata": bool(requiredPluginNames),
            "requiredPluginNames": requiredPluginNames,
        }

    def _normalizeExportJsonContent(self, rawExport: Any) -> str:
        if isinstance(rawExport, str):
            text = rawExport.strip()
            if not text:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Scipion export returned empty content",
                )

            text = self._extractWorkflowJsonText(text)

            try:
                json.loads(text)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Scipion export returned invalid JSON text: {e}",
                )

            return text

        if isinstance(rawExport, (list, dict)):
            try:
                return json.dumps(rawExport, indent=2, ensure_ascii=False)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to serialize export payload: {e}",
                )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unsupported export payload returned by Scipion",
        )

    def _normalizeProtocolIdsForExport(
            self,
            protocolIds: Optional[List[Union[int, str]]],
    ) -> List[str]:
        out: List[str] = []
        seen: TypingSet[str] = set()

        for raw in protocolIds or []:
            value = str(raw).strip()
            if not value or value.upper() == "PROJECT":
                continue
            if value in seen:
                continue
            seen.add(value)
            out.append(value)

        return out

    def _resolveRuntimeProtocolsForExport(
            self,
            mapper,
            projectId: int,
            protocolIds: List[Union[int, str]],
    ) -> List[Any]:
        protocolList = []
        missing = []

        for protocolId in protocolIds or []:
            try:
                protocol = self._getScipionProtocolForRuntime(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )
            except HTTPException as e:
                if e.status_code == status.HTTP_404_NOT_FOUND:
                    missing.append(str(protocolId))
                    continue
                raise

            protocolList.append(protocol)

        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol(s) not found: {', '.join(missing)}",
            )

        if not protocolList:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No valid protocols to export",
            )

        return protocolList

    def _sanitizeExportFilename(self, rawFilename: str) -> str:
        filename = str(rawFilename or "").strip()
        filename = filename.replace("\\", "/").split("/")[-1].strip()

        if not filename or filename in (".", ".."):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid filename",
            )

        filename = filename.rstrip(". ").strip()
        if not filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid filename",
            )

        if not filename.lower().endswith(".json"):
            filename += ".json"

        return filename

    def _resolveFsRootForWrite(
            self,
            protocolId: Union[int, str],
            mapper=None,
            projectId: Optional[int] = None,
    ) -> Path:
        pathInfo = self.getProtocolPath(
            protocolId=protocolId,
            mapper=mapper,
            projectId=projectId,
        )
        rootAbs = str((pathInfo or {}).get("rootAbs") or "").strip()
        if not rootAbs:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not resolve browser root",
            )
        return Path(rootAbs).expanduser().resolve()

    def _guardFsPathWithinRootForWrite(
            self,
            rootPath: Path,
            requestedPath: str,
    ) -> Path:
        rawPath = str(requestedPath or "").strip()
        if not rawPath:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing path",
            )

        candidate = Path(rawPath).expanduser()
        if not candidate.is_absolute():
            candidate = rootPath / candidate

        candidate = candidate.resolve()

        try:
            candidate.relative_to(rootPath)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Path escapes browser root",
            )

        return candidate

    def getProtocolPath(
            self,
            protocolId,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        if self._isGlobalFsBrowserMode(protocolId):
            root = self._getGlobalFsBrowserRoot()
            return {
                "rootAbs": str(root),
                "startPath": "",
            }

        fakeProtocolId = 'fake-protocol-id-for-browser-paths-resolution'

        if protocolId != fakeProtocolId:
            protocol = self._getScipionProtocolForRuntime(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
            protocolAbsPath = os.path.abspath(protocol.getPath())
            rootAbsPath = self._inferProjectRootAbs(protocolAbsPath)
        else:
            projectPath = self.currentProject.getPath()
            protocolAbsPath = os.path.abspath(projectPath)
            rootAbsPath = self._inferProjectRootAbs(protocolAbsPath)

        rootAbsPath = os.path.abspath(rootAbsPath) if rootAbsPath else "/home"

        startRelPath = os.path.relpath(protocolAbsPath, rootAbsPath)
        if startRelPath == ".":
            startRelPath = ""

        if startRelPath.startswith(".."):
            rootAbsPath = "/home"
            startRelPath = ""

        return {
            "rootAbs": rootAbsPath,
            "startPath": startRelPath,
            "protocolRoot": startRelPath,
        }

    def _inferProjectRootAbs(self, protocolAbsPath: str) -> str:
        # Try to infer project folder from a protocol path like: <project>/Runs/<protId>/...
        normPath = os.path.abspath(protocolAbsPath)
        runsMarker = f"{os.sep}Runs{os.sep}"
        if runsMarker in normPath:
            return normPath.split(runsMarker)[0] or ""

        runsSuffix = f"{os.sep}Runs"
        if normPath.endswith(runsSuffix):
            return normPath[: -len(runsSuffix)] or ""

        # Fallback: use project path if available
        projectPath = ""
        if hasattr(self.currentProject, "getPath"):
            try:
                projectPath = self.currentProject.getPath() or ""
            except Exception:
                projectPath = ""
        elif hasattr(self.currentProject, "path"):
            projectPath = getattr(self.currentProject, "path") or ""

        return os.path.abspath(projectPath) if projectPath else ""

    def _protocolRoot(
            self,
            protocolId: Union[int, str],
            mapper=None,
            projectId: Optional[int] = None,
    ) -> FsPath:
        """
        Resolve the absolute root folder for a protocol, using your service.
        """
        pathInfo = self.getProtocolPath(
            protocolId=str(protocolId),
            mapper=mapper,
            projectId=projectId,
        )

        rootAbs = str((pathInfo or {}).get("rootAbs") or "").strip()
        if not rootAbs:
            raise HTTPException(status_code=404, detail="Protocol path not found")

        return FsPath(rootAbs).resolve()

    @staticmethod
    def _guardJoin(root: FsPath, relPath: str) -> FsPath:
        """
        Join root + relPath, resolve, and ensure it stays inside root.
        """
        rel = (relPath or "").strip().lstrip("/\\")
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except Exception:
            if not target.exists():
                raise HTTPException(status_code=400, detail="Invalid path")
        return target

    @staticmethod
    def _guessMime(p: FsPath) -> str:
        mt, _ = mimetypes.guess_type(str(p))
        return mt or "application/octet-stream"

    def _resolveRuntimeProtocolIdForFs(
            self,
            protocolId: Union[int, str],
            mapper=None,
            projectId: Optional[int] = None,
    ) -> str:
        if self._isGlobalFsBrowserMode(protocolId):
            return str(protocolId)

        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        return str(scipionProtocolId)

    def listProtocolDir(
            self,
            protocolId: str,
            path: str,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        """Return the directory file list."""
        fileHandlers = FileHandlers(self.currentProject)

        if self._isGlobalFsBrowserMode(protocolId):
            root = self._getGlobalFsBrowserRoot()
            return fileHandlers.listRemoteDirectoryUnderRoot(root, path)

        runtimeProtocolId = self._resolveRuntimeProtocolIdForFs(
            protocolId=protocolId,
            mapper=mapper,
            projectId=projectId,
        )

        return fileHandlers.listProtocolDir(runtimeProtocolId, path)

    def previewProtocolTextFile(
            self,
            protocolId: str,
            path: str,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        """
        Return a lightweight preview for a file inside a protocol workspace.
        """
        fileHandlers = FileHandlers(self.currentProject)

        if self._isGlobalFsBrowserMode(protocolId):
            root = self._getGlobalFsBrowserRoot()
            return fileHandlers.previewTextFileUnderRoot(root, path)

        runtimeProtocolId = self._resolveRuntimeProtocolIdForFs(
            protocolId=protocolId,
            mapper=mapper,
            projectId=projectId,
        )

        return fileHandlers.previewProtocolTextFile(runtimeProtocolId, path)

    def previewRemoteEntry(
            self,
            protocolId: str,
            path: str,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        """
        Return a preview.
        """
        fileHandlers = FileHandlers(self.currentProject)

        if self._isGlobalFsBrowserMode(protocolId):
            root = self._getGlobalFsBrowserRoot()
            return fileHandlers.previewRemoteEntryUnderRoot(
                root,
                path,
                databaseInspector=self._inspectScipionSqliteDatabase,
            )

        runtimeProtocolId = self._resolveRuntimeProtocolIdForFs(
            protocolId=protocolId,
            mapper=mapper,
            projectId=projectId,
        )

        return fileHandlers.previewProtocolRemoteEntry(
            runtimeProtocolId,
            path,
            databaseInspector=self._inspectScipionSqliteDatabase,
        )

    def previewProtocolImageFile(
            self,
            protocolId,
            path,
            inline: bool,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        """
        inline == False:
            - attachment download (binary as-is)
        inline == True:
            - preview mode:
              * if MRC/volume -> PNG slice + X-Preview-* headers
              * if normal image -> raw image + X-Preview-* headers
              * else -> raw bytes + minimal headers
        """
        fileHandlers = FileHandlers(self.currentProject)

        if self._isGlobalFsBrowserMode(protocolId):
            root = self._getGlobalFsBrowserRoot()
            return fileHandlers.previewImageFileUnderRoot(root, path, inline)

        runtimeProtocolId = self._resolveRuntimeProtocolIdForFs(
            protocolId=protocolId,
            mapper=mapper,
            projectId=projectId,
        )

        return fileHandlers.previewProtocolImageFile(runtimeProtocolId, path, inline)

    def outputPreview(
            self,
            protocolId: Union[int, str],
            outputName: str,
            requestHeaders: Optional[Dict[str, Any]] = None,
            colormap: Optional[str] = None,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        return self._outputPreviewRuntime(
            protocolId=protocolId,
            outputName=outputName,
            requestHeaders=requestHeaders,
            colormap=colormap,
            mapper=mapper,
            projectId=projectId,
        )

    def _outputPreviewRuntime(
            self,
            protocolId: Union[int, str],
            outputName: str,
            requestHeaders: Optional[Dict[str, Any]] = None,
            colormap: Optional[str] = None,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if self.currentProject is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No current project loaded",
            )

        try:
            protocol = self.currentProject.getProtocol(int(scipionProtocolId))
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol {scipionProtocolId} not found: {e}",
            )

        output = getattr(protocol, outputName, None)
        if output is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Output '{outputName}' not found in protocol {scipionProtocolId}",
            )

        outputPath = None
        getFileName = getattr(output, "getFileName", None)
        if callable(getFileName):
            try:
                outputPath = getFileName()
            except Exception:
                outputPath = None

        if not outputPath:
            outputPath = str(output)

        objMgr = self._createObjectManager()

        return OutputsPreview(
            self.currentProject,
            protocol,
            output,
            requestHeaders=requestHeaders,
            colormapOverride=colormap,
        ).preview(
            int(scipionProtocolId),
            outputPath,
            objMgr,
        )

    def buildProtocolThumbnail(
            self,
            protocolId: Union[int, str],
            force: bool = False,
            size: int = 320,
            outputName: Optional[str] = None,
            mapper=None,
            projectId: Optional[int] = None,
    ) -> Dict[str, Any]:
        scipionProtocolId = self._resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        thumbnailService = ThumbnailService(self.currentProject)
        return thumbnailService.buildProtocolThumbnail(
            protocolId=scipionProtocolId,
            force=force,
            size=size,
            outputName=outputName,
        )

    def buildProjectThumbnail(
        self,
        force: bool = False,
        size: int = 640,
        maxProtocols: int = 6,
    ) -> Dict[str, Any]:
        # buildProjectThumbnail
        service = ThumbnailService(self.currentProject)
        return service.buildProjectThumbnail(
            force=force,
            size=size,
            maxProtocols=maxProtocols,
        )

    def exportProtocolsService(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
            payload: Any,
    ) -> Dict[str, Any]:
        protocolIds = self._normalizeProtocolIdsForExport(
            getattr(payload, "protocolIds", None),
        )
        if not protocolIds:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Missing protocolIds",
            )

        directoryPath = str(getattr(payload, "directoryPath", "") or "").strip()
        if not directoryPath:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Missing directoryPath",
            )

        filename = self._sanitizeExportFilename(
            getattr(payload, "filename", ""),
        )

        try:
            protocolList = self._resolveRuntimeProtocolsForExport(
                mapper=mapper,
                projectId=projectId,
                protocolIds=protocolIds,
            )

            rawExport = self.currentProject.getProtocolsJson(protocolList)
            content = self._buildWorkflowExportJsonContent(rawExport, protocolList)

            rootPath = self._resolveFsRootForWrite(
                "-1",
                mapper=mapper,
                projectId=projectId,
            )
            targetDir = self._guardFsPathWithinRootForWrite(rootPath, directoryPath)

            if targetDir.exists() and not targetDir.is_dir():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Destination path is not a directory",
                )

            targetDir.mkdir(parents=True, exist_ok=True)

            targetPath = (targetDir / filename).resolve()
            try:
                targetPath.relative_to(rootPath)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Path escapes browser root",
                )

            if targetPath.exists() and targetPath.is_dir():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Destination path points to a directory",
                )

            targetPath.write_text(content, encoding="utf-8")

            return {
                "success": True,
                "path": str(targetPath),
                "filename": filename,
                "size": targetPath.stat().st_size if targetPath.exists() else 0,
                "mimeType": "application/json",
                "protocolIds": protocolIds,
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Scipion export failed: {e}",
            )

    def _getCurrentWorkflowProtocolIds(self) -> TypingSet[str]:
        try:
            runs = self.currentProject.getRunsGraph(refresh=True, checkPids=False)
            nodesDict = getattr(runs, "_nodesDict", {}) or {}
        except Exception:
            return set()

        return {
            str(nodeId)
            for nodeId in nodesDict.keys()
            if str(nodeId) != "PROJECT"
        }

    @staticmethod
    def _sortProtocolIds(protocolIds: TypingSet[str]) -> List[str]:
        def sortKey(value: str):
            try:
                return (0, int(value))
            except Exception:
                return (1, str(value))

        return sorted(protocolIds, key=sortKey)

    def _normalizeWorkflowImportErrors(self, result: Any) -> List[str]:
        if result is None:
            return []

        if isinstance(result, dict):
            rawErrors = result.get("errors") or result.get("error") or result.get("detail")
            if rawErrors is None:
                return []
            if isinstance(rawErrors, list):
                return [str(item) for item in rawErrors if str(item).strip()]
            return [str(rawErrors)] if str(rawErrors).strip() else []

        if isinstance(result, (list, tuple, set)):
            return [str(item) for item in result if str(item).strip()]

        text = str(result).strip()
        return [text] if text else []

    def _getWorkflowImportSourceProjectId(self, payload: Any, workflowPayload: Any) -> Optional[str]:
        sourceProjectId = getattr(payload, "sourceProjectId", None)

        if sourceProjectId is None and isinstance(workflowPayload, dict):
            sourceProjectId = workflowPayload.get("sourceProjectId")

            metadata = workflowPayload.get("scipionWeb")
            if sourceProjectId is None and isinstance(metadata, dict):
                sourceProjectId = metadata.get("sourceProjectId")

        if sourceProjectId is None:
            return None

        sourceProjectIdText = str(sourceProjectId).strip()
        return sourceProjectIdText or None

    def _getWorkflowProtocolItems(self, workflowContent: Any) -> List[Dict[str, Any]]:
        if isinstance(workflowContent, list):
            return [item for item in workflowContent if isinstance(item, dict)]

        if isinstance(workflowContent, dict):
            for key in ("workflow", "content", "protocols"):
                value = workflowContent.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]

        return []

    def _getWorkflowProtocolId(self, protocolItem: Dict[str, Any], fallbackIndex: int) -> str:
        protocolId = (
            protocolItem.get("object.id")
            or protocolItem.get("id")
            or protocolItem.get("_objId")
            or fallbackIndex
        )

        return str(protocolId).strip()

    def _collectWorkflowProtocolIds(self, workflowContent: Any) -> TypingSet[str]:
        protocolIds: TypingSet[str] = set()

        for index, protocolItem in enumerate(self._getWorkflowProtocolItems(workflowContent)):
            protocolId = self._getWorkflowProtocolId(protocolItem, index)
            if protocolId:
                protocolIds.add(protocolId)

        return protocolIds

    def _sanitizeWorkflowExternalReferences(self, workflowContent: Any) -> Any:
        copiedProtocolIds = self._collectWorkflowProtocolIds(workflowContent)
        if not copiedProtocolIds:
            return workflowContent

        dropValue = object()
        pointerPattern = re.compile(r"^\s*(\d+)\.([A-Za-z_][A-Za-z0-9_\.]*)\s*$")

        def sanitizeValue(value: Any) -> Any:
            if isinstance(value, str):
                match = pointerPattern.match(value)
                if match and match.group(1) not in copiedProtocolIds:
                    return dropValue
                return value

            if isinstance(value, list):
                nextList = []
                for item in value:
                    nextItem = sanitizeValue(item)
                    if nextItem is not dropValue:
                        nextList.append(nextItem)
                return nextList

            if isinstance(value, dict):
                nextDict = {}
                for key, item in value.items():
                    nextItem = sanitizeValue(item)
                    if nextItem is not dropValue:
                        nextDict[key] = nextItem
                return nextDict

            return value

        return sanitizeValue(workflowContent)

    def _unwrapWorkflowImportPayload(self, workflowPayload: Any) -> Any:
        if workflowPayload is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Missing workflow",
            )

        if isinstance(workflowPayload, dict):
            metadata = workflowPayload.get("scipionWeb")
            if isinstance(metadata, dict):
                requiredPluginNames = [
                    str(name).strip()
                    for name in metadata.get("requiredPluginNames", []) or []
                    if str(name).strip()
                ]
                self._validateWorkflowRequiredPlugins(requiredPluginNames)

            if "workflow" in workflowPayload:
                return workflowPayload.get("workflow")

            if "content" in workflowPayload:
                return workflowPayload.get("content")

        return workflowPayload

    def exportWorkflowProtocolsService(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
            payload: Any,
    ) -> Dict[str, Any]:
        if bool(getattr(payload, "includeUpstream", False)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="includeUpstream is not supported yet",
            )

        protocolIds = self._normalizeProtocolIdsForExport(
            getattr(payload, "protocolIds", None),
        )
        if not protocolIds:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Missing protocolIds",
            )

        protocolList = self._resolveRuntimeProtocolsForExport(
            mapper=mapper,
            projectId=projectId,
            protocolIds=protocolIds,
        )

        rawExport = self.currentProject.getProtocolsJson(protocolList)
        workflow = self._decodeExportJsonPayload(rawExport)
        metadata = self._buildWorkflowPluginMetadata(protocolList)
        metadata["sourceProjectId"] = projectId
        metadata["sourceProtocolIds"] = protocolIds

        return {
            "sourceProjectId": projectId,
            "protocolIds": protocolIds,
            "workflow": workflow,
            "scipionWeb": metadata,
        }

    def importWorkflowProtocolsService(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
            payload: Any,
    ) -> Dict[str, Any]:
        mode = str(getattr(payload, "mode", "append") or "append").strip().lower()
        if mode != "append":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported import mode: {mode}",
            )

        rawWorkflowPayload = getattr(payload, "workflow", None)
        sourceProjectId = self._getWorkflowImportSourceProjectId(payload, rawWorkflowPayload)

        workflowContent = self._unwrapWorkflowImportPayload(rawWorkflowPayload)

        if isinstance(workflowContent, str):
            workflowText = self._extractWorkflowJsonText(workflowContent)
            try:
                workflowContent = json.loads(workflowText)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid workflow JSON: {e}",
                )

        if not isinstance(workflowContent, (list, dict)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Workflow must be a JSON list or object",
            )

        isSameProjectImport = (
            sourceProjectId is not None
            and str(sourceProjectId).strip() == str(projectId).strip()
        )

        if not isSameProjectImport:
            workflowContent = self._sanitizeWorkflowExternalReferences(workflowContent)

        beforeIds = self._getCurrentWorkflowProtocolIds()
        workflowJson = json.dumps(workflowContent, ensure_ascii=False)

        try:
            loadResult = self.currentProject.loadProtocols(jsonStr=workflowJson)
        except Exception as e:
            logger.exception("Failed to import workflow protocols. projectId=%s", projectId)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to import workflow protocols: {e}",
            )

        errors = self._normalizeWorkflowImportErrors(loadResult)

        syncInfo = self.syncProjectProtocolsAndDependencies(
            mapper,
            projectId,
            refresh=True,
            checkPid=True,
        )

        afterIds = self._getCurrentWorkflowProtocolIds()
        createdIds = self._sortProtocolIds(afterIds - beforeIds)

        return {
            "status": 1 if errors else 0,
            "errors": errors,
            "workflow": [],
            "created": [{"newId": protocolId} for protocolId in createdIds],
            "protocolsCount": int(syncInfo.get("protocols", 0)),
            "dependenciesCount": int(syncInfo.get("dependencies", 0)),
        }

    def writeRemoteFileService(
            self,
            protocolId: Union[int, str],
            payload: Any,
            mapper=None,
            projectId: Optional[int] = None,
    ) -> Dict[str, Any]:
        rootPath = self._resolveFsRootForWrite(
            protocolId=protocolId,
            mapper=mapper,
            projectId=projectId,
        )
        targetPath = self._guardFsPathWithinRootForWrite(
            rootPath,
            getattr(payload, "path", ""),
        )

        if targetPath.exists() and targetPath.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Destination path points to a directory",
            )

        rawContent = getattr(payload, "content", "")
        content = "" if rawContent is None else str(rawContent)
        mimeType = getattr(payload, "mimeType", None) or "application/json"

        targetPath.parent.mkdir(parents=True, exist_ok=True)
        targetPath.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "path": str(targetPath),
            "size": targetPath.stat().st_size if targetPath.exists() else 0,
            "mimeType": mimeType,
        }

    # ----------------------------------------------------------------------
    # Internal helpers for TiltSeries (SetOfTiltSeries)
    # ----------------------------------------------------------------------

    def _resolveOutputForTiltSeries(
            self,
            protocolId: int,
            outputName: str,
            projectId: Optional[int] = None,
            mapper=None,
    ):
        """
        Resolve protocol + SetOfTiltSeries-like output for tilt series operations.

        protocolId can be either the PostgreSQL protocols.id or the Scipion protocolId.
        """
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if not hasattr(protocol, outputName):
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' not found in protocol",
            )

        output = getattr(protocol, outputName)
        if output is None:
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' is None",
            )

        return protocol, output

    def _getPostgresqlTiltSeriesReaderIfAvailable(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            outputName: str,
    ):
        if mapper is None:
            return None

        try:
            from app.backend.viewers.postgresql_tiltseries_reader import PostgresqlTiltSeriesReader

            readerProtocolId = self._resolvePostgresqlReaderProtocolId(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

            reader = PostgresqlTiltSeriesReader(
                db=mapper.db,
                projectId=projectId,
                protocolId=readerProtocolId,
                outputName=outputName,
            )

            if reader.hasOutput():
                return reader

        except Exception:
            logger.exception(
                "Failed to initialize PostgreSQL TiltSeries reader. projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
            )

        return None

    def _parseTiltSeriesFramePath(
            self,
            framePath: Any,
            fallbackIndex: int,
    ) -> Tuple[str, int]:
        pathText = str(framePath or "").strip()
        if not pathText:
            raise HTTPException(
                status_code=404,
                detail="Tilt image path not found in PostgreSQL metadata",
            )

        imageIndex = int(fallbackIndex)
        imagePath = pathText

        if "@" in pathText:
            indexText, imagePath = pathText.split("@", 1)
            try:
                imageIndex = int(float(indexText))
            except Exception:
                imageIndex = int(fallbackIndex)

        # Do not os.path.abspath() here.
        # PostgreSQL paths can be project-relative:
        # Runs/000084_Prot.../extra/...
        # They must be resolved against the project path, not against cwd/scipion_home.
        return str(Path(str(imagePath)).expanduser()), imageIndex

    # ======================================================================
    # Analyze Results: Resolve viewer
    # ======================================================================
    def resolveAnalyzeViewerDecision(
            self,
            projectId: int,
            protocolId: int,
            ctx: Dict[str, Any],
            mapper=None,
    ) -> Dict[str, Any]:
        # This resolver is reserved for external developer-provided viewers.
        # Built-in React viewers are selected on the frontend side.
        return {"handled": False}

    # ======================================================================
    # Analyze Results: CTF Tomography (CTFTomoSeries)
    # ======================================================================
    def _resolveOutputForCtftomoSeries(
            self,
            protocolId: int,
            outputName: str,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        """
        Resolve protocol + CTFTomoSeries-like output for CTF tomography operations.

        protocolId can be either the PostgreSQL protocols.id or the Scipion protocolId.
        """
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if not hasattr(protocol, outputName):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Output '{outputName}' not found in protocol",
            )

        output = getattr(protocol, outputName)
        if output is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Output '{outputName}' is None",
            )

        return protocol, output

    def _buildCtftomoSeriesSummary(self, ctfSeries) -> Dict[str, Any]:
        """
        Build a JSON-friendly summary for one CTFTomoSeries object.
        """

        tsId = ctfSeries.getTsId()
        label = ctfSeries.getObjLabel()
        tiltSeries = ctfSeries.getTiltSeries()
        dims = list(tiltSeries.getDim())
        pixelSize = tiltSeries.getSamplingRate()
        nViews = tiltSeries.getSize()

        item: Dict[str, Any] = {
            "tiltSeriesId": tsId,
            "label": str(label) if label is not None else "",
        }
        if nViews is not None:
            item["nViews"] = nViews
        if dims is not None:
            item["dims"] = dims
        if pixelSize is not None:
            item["pixelSize"] = pixelSize
        return item

    def _buildCtftomoMeasurementRow(self, ctfObj, tiltSeries=None) -> Dict[str, Any]:
        """
        Build a JSON-friendly row with CTF parameters for a single tilt image.
        """

        defocusU = ctfObj.getDefocusU()
        defocusV = ctfObj.getDefocusV()
        defocusAngle = ctfObj.getDefocusAngle()
        resolution = ctfObj.getResolution()
        phaseShift = ctfObj.getPhaseShift()
        acqOrder = ctfObj.getAcquisitionOrder()
        psdFile = ctfObj.getPsdFile()
        astigmatism = defocusU - defocusV
        tiltAngle = None
        enabled = ctfObj.isEnabled()
        dose = None

        if tiltSeries is not None:
            try:
                view = tiltSeries.getItem('_acqOrder', acqOrder)
            except Exception:
                view = None

            if view is not None:
                try:
                    tiltAngle = view.getTiltAngle()
                except Exception:
                    tiltAngle = None

                try:
                    acq = view.getAcquisition()
                    dose = acq.getAccumDose()
                except Exception:
                    dose = None

        row: Dict[str, Any] = {}
        row["index"] = ctfObj.getObjId()
        row["viewIndex"] = ctfObj.getObjId()
        if tiltAngle is not None:
            row["tiltAngle"] = tiltAngle
        if dose is not None:
            row["dose"] = dose
        if defocusU is not None:
            row["defocusU"] = defocusU
        if defocusV is not None:
            row["defocusV"] = defocusV
        row['astigmatism'] = astigmatism
        if defocusAngle is not None:
            row["defocusAngle"] = defocusAngle
        if resolution is not None:
            row["resolution"] = resolution
        if phaseShift is not None:
            row["phaseShift"] = phaseShift
        if acqOrder is not None:
            row["order"] = acqOrder
        if psdFile:
            row['psdFile'] = psdFile

        row['excluded'] = not enabled

        return row

    def listOutputCtftomoSeriesService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            mapper=None,
    ):
        """
        List all CTFTomoSeries in a CTFTomo output.

        Shape:
        [
          {
            "tiltSeriesId": "...",
            "label": "...",
            "nViews"?: number,
            "dims"?: [...],
            "pixelSize"?: number,
            "tiltAxisAngle"?: number,
          },
          ...
        ]
        """
        pgReader = self._getPostgresqlCtftomoReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            return pgReader.listCtftomoSeries()

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="CTFTomo",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason="reader_not_available",
            )

        protocol, output = self._resolveOutputForCtftomoSeries(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )

        seriesList: List[Dict[str, Any]] = []

        for index, ctfSeries in enumerate(output.iterItems(iterate=False)):
            try:
                summary = self._buildCtftomoSeriesSummary(ctfSeries)
                summary["index"] = index
                seriesList.append(summary)
            except Exception as e:
                logger.warning("Failed to summarize CTFTomoSeries #%s: %s", index, e)

        return seriesList

    def getCtftomoSeriesViewsService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tiltSeriesId: Union[int, str],
            mapper=None,
    ):
        """
        Return all CTF measurements for one tilt series inside a CTFTomo output.

        Shape:
        {
          "tiltSeriesId": "...",
          "label": "...",
          "nViews": number,
          "dims"?: [...],
          "pixelSize"?: number,
          "tiltAxisAngle"?: number,
          "isDefocusUInRange"?: bool,
          "isDefocusVInRange"?: bool,
          "frames": [
             {
               "index": 0-based index,
               "viewIndex": 1-based index,
               "tiltAngle"?: number,
               "dose"?: number,
               "defocusU"?: number,
               "defocusV"?: number,
               "defocusAngle"?: number,
               "resolution"?: number,
               "phaseShift"?: number,
               "cutOnFreq"?: number,
               "defocusUDeviation"?: number,
               "defocusVDeviation"?: number,
             },
             ...
          ]
        }
        """
        pgReader = self._getPostgresqlCtftomoReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.getCtftomoSeriesViews(tiltSeriesId)
            if payload is not None:
                return payload

            self._raisePostgresqlViewerUnavailable(
                viewerName="CTFTomo views",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) or "views_not_available",
                tiltSeriesId=tiltSeriesId,
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="CTFTomo views",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason="views_not_available" if pgReader is not None else "reader_not_available",
                tiltSeriesId=tiltSeriesId,
            )

        protocol, output = self._resolveOutputForCtftomoSeries(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )

        targetKey = str(tiltSeriesId)
        setOfTiltSeries = output.getSetOfTiltSeries()
        ctfSerie = output.getItem('_tsId', targetKey)
        associatedTS = setOfTiltSeries.getItem('_tsId', targetKey)
        frames: List[Dict[str, Any]] = []

        for idx, ctfTomo in enumerate(ctfSerie.iterItems(iterate=False)):
            try:
                row = self._buildCtftomoMeasurementRow(ctfTomo, tiltSeries=associatedTS)
                if "index" not in row:
                    row["index"] = idx
                frames.append(row)
            except Exception as e:
                logger.warning(
                    "Failed to build CTFTomo measurement for tiltSeries '%s' (item #%s): %s",
                    tiltSeriesId,
                    idx,
                    e,
                )

        summary = self._buildCtftomoSeriesSummary(ctfSerie)
        summary["frames"] = frames
        summary["tiltSeriesId"] = summary.get("tiltSeriesId") or tiltSeriesId
        summary["nViews"] = len(frames)

        return summary

    def renderCtfTomoPsdImageService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            psdPath: str,
            size: int = 1024,
            fmt: str = "png",
            inline: bool = True,
            index: int = 0,
            quality: int = 75,
            applyTransform: bool = False,
            rot=None,
            shifts=None,
            mapper=None,
    ) -> Response:
        """
            Render a single CTFtomo PSD image using the OutputsPreview pipeline.

            - psdPath can be relative to the protocol root or an absolute path.
            - size sets the max side in pixels for the thumbnail (square).
            - fmt controls the output format: png | jpg | webp.
            - index is used when the PSD is stored in a stack file.
            - applyTransform/rot/shifts are optional alignment parameters.
            """
        if mapper is not None and psdPath:
            try:
                splitPath = str(psdPath).split("@")
                imageIndex = int(index)

                if len(splitPath) > 1:
                    try:
                        imageIndex = int(float(splitPath[0]))
                    except Exception:
                        imageIndex = int(index)

                candidatePath = Path(splitPath[-1]).expanduser()

                if candidatePath.is_absolute():
                    absPath = candidatePath.resolve()

                    if absPath.exists() and absPath.is_file():
                        preview = OutputsPreview(
                            currentProject=self.currentProject,
                            protocol=None,
                            output=None,
                        )

                        return preview.renderImageFromFilePath(
                            filePath=str(absPath),
                            size=size,
                            fmt=fmt,
                            index=imageIndex,
                            inline=inline,
                            quality=quality,
                            applyTransform=applyTransform and rot is not None and shifts is not None,
                            rot=rot,
                            shifts=shifts,
                        )

            except Exception:
                logger.exception(
                    "Failed to render CTFTomo PSD from PostgreSQL metadata. projectId=%s protocolId=%s outputName=%s psdPath=%s",
                    projectId,
                    protocolId,
                    outputName,
                    psdPath,
                )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="CTFTomo PSD",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason="psd_file_not_available",
                psdPath=psdPath,
            )

        protocol, output = self._resolveOutputForCtftomoSeries(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )
        if protocol is None:
            raise HTTPException(
                status_code=404,
                detail=f"Protocol '{protocolId}' not found in project '{projectId}'",
            )

        if not psdPath:
            raise HTTPException(
                status_code=400,
                detail="Missing PSD image path",
            )

        protRoot = Path(protocol.getPath()).resolve()
        splitPath = psdPath.split('@')
        if len(splitPath) > 1:
            index = int(splitPath[0])
        candidatePath = Path(splitPath[-1])

        # Allow both relative (to protocol root) and absolute paths
        if not candidatePath.is_absolute():
            absPath = (protRoot / candidatePath).resolve()
        else:
            absPath = candidatePath.resolve()

        if not absPath.exists() or not absPath.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"PSD image file not found: {absPath}",
            )

        # We do not need a real output object for this helper
        preview = OutputsPreview(
            currentProject=self.currentProject,
            protocol=protocol,
            output=None,
        )

        return preview.renderImageFromFilePath(
            filePath=str(absPath),
            size=size,
            fmt=fmt,
            index=index,
            inline=inline,
            quality=quality,
            applyTransform=applyTransform and rot is not None and shifts is not None,
            rot=rot,
            shifts=shifts,
        )

    def _buildTiltSeriesSummary(self, ts) -> Dict[str, Any]:
        """
        Build a JSON-friendly summary for one tilt series.
        """
        tsId = ts.getTsId()
        label = f"TiltSeries {tsId}"
        nViews = ts.getSize()
        dims = ts.getDim()
        pixelSize = ts.getSamplingRate()
        tiltAxisAngle = ts.getAcquisition().getTiltAxisAngle()
        item: Dict[str, Any] = {
            "tiltSeriesId": tsId,
            "label": str(label),
        }
        if nViews is not None:
            item["nViews"] = nViews
        if dims is not None:
            item["dims"] = dims
        if pixelSize is not None:
            item["pixelSize"] = pixelSize
        if tiltAxisAngle is not None:
            item["tiltAxisAngle"] = tiltAxisAngle

        return item

    def _getPostgresqlCtftomoReaderIfAvailable(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            outputName: str,
    ):
        if mapper is None:
            return None

        try:
            from app.backend.viewers.postgresql_ctftomo_reader import PostgresqlCtftomoReader

            readerProtocolId = self._resolvePostgresqlReaderProtocolId(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

            reader = PostgresqlCtftomoReader(
                db=mapper.db,
                projectId=projectId,
                protocolId=readerProtocolId,
                outputName=outputName,
            )

            if reader.hasOutput():
                return reader

        except Exception:
            logger.exception(
                "Failed to initialize PostgreSQL CTFTomo reader. projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
            )

        return None

    # ======================================================================
    # Analyze Results: Volumes (Volume / VolumeMask / SetOfVolumes)
    # ======================================================================

    def _resolveOutputForVolumes(
            self,
            protocolId: int,
            outputName: str,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        # Try exact + common alternates (singular/plural/alias)
        candidates = [outputName]
        alias = {
            "outputVolumes": "outputVolume",
            "outputVolume": "outputVolumes",
            "outputMasks": "outputMask",
            "outputMask": "outputMasks",
        }
        if outputName in alias:
            candidates.append(alias[outputName])
        if outputName.endswith("s"):
            candidates.append(outputName[:-1])
        else:
            candidates.append(outputName + "s")

        for name in candidates:
            if hasattr(protocol, name):
                out = getattr(protocol, name)
                if out is not None:
                    return protocol, out

        raise HTTPException(status_code=404, detail=f"Output '{outputName}' not found in protocol (tried {candidates})")

    def _getPostgresqlVolumeReaderIfAvailable(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            outputName: str,
    ):
        if mapper is None:
            return None

        readerProtocolId = self._resolvePostgresqlReaderProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        try:
            from app.backend.viewers.postgresql_coords3d_tomogram_volume_reader import \
                PostgresqlCoords3dTomogramVolumeReader

            reader = PostgresqlCoords3dTomogramVolumeReader(
                db=mapper.db,
                projectId=projectId,
                protocolId=readerProtocolId,
                outputName=outputName,
            )

            if reader.hasOutput():
                return reader

        except Exception:
            logger.debug(
                "PostgreSQL Coords3D-derived tomogram volume reader is not available. projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
                exc_info=True,
            )

        try:
            from app.backend.viewers.postgresql_volume_reader import PostgresqlVolumeReader

            reader = PostgresqlVolumeReader(
                db=mapper.db,
                projectId=projectId,
                protocolId=readerProtocolId,
                outputName=outputName,
            )

            if reader.hasOutput():
                return reader

        except Exception:
            logger.exception(
                "Failed to initialize PostgreSQL volume reader. projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
            )

        return None

    def listOutputVolumesService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            mapper=None,
    ):
        pgReader = self._getPostgresqlVolumeReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.listVolumes()
            if payload is not None:
                return payload

            logger.info(
                "Skipping PostgreSQL volume list reader. projectId=%s protocolId=%s outputName=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Volume",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
            )

        protocol, output = self._resolveOutputForVolumes(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )
        op = OutputsPreview(self.currentProject, protocol, output)
        return op.listOutputVolumes()

    def getVolumeInfoService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            volumeId: Union[int, str],
            mapper=None,
    ):
        pgReader = self._getPostgresqlVolumeReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.getVolumeInfo(volumeId)
            if payload is not None:
                return payload

            logger.info(
                "Skipping PostgreSQL volume info reader. projectId=%s protocolId=%s outputName=%s volumeId=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                volumeId,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Volume",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
                volumeId=volumeId,
            )

        protocol, output = self._resolveOutputForVolumes(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )
        op = OutputsPreview(self.currentProject, protocol, output)
        return op.getVolumeInfo(volumeId)

    def getVolumeHistogramService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            volumeId: Union[int, str],
            bins: int = 128,
            mapper=None,
    ):
        pgReader = self._getPostgresqlVolumeReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.getHistogram(volumeId=volumeId, bins=bins)
            if payload is not None:
                return {
                    "binEdges": payload.get("binEdges") or [],
                    "counts": payload.get("counts") or [],
                }

            logger.info(
                "Skipping PostgreSQL volume histogram reader. projectId=%s protocolId=%s outputName=%s volumeId=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                volumeId,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Volume histogram",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
                volumeId=volumeId,
            )

        protocol, output = self._resolveOutputForVolumes(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )
        op = OutputsPreview(self.currentProject, protocol, output)

        if isinstance(output, SetOfVolumes):
            output = output.getItem('_objId', int(volumeId) + 1)

        raw = op.getVolumeHistogram(volumePath=output.getFileName(), bins=bins)
        if not raw:
            return {"binEdges": [], "counts": []}

        binEdges = raw.get("binEdges") or raw.get("bin_edges") or []
        counts = raw.get("counts") or raw.get("values") or []

        try:
            binEdges = list(binEdges)
        except Exception:
            binEdges = []

        try:
            counts = list(counts)
        except Exception:
            counts = []

        return {
            "binEdges": binEdges,
            "counts": counts,
        }

    def _buildVolumeSliceCacheKey(
            self,
            *,
            volumePath: str,
            tomogramId: Union[int, str],
            sliceIndex: int,
            axis: str,
            colormap: Optional[str],
            normalize: Optional[str],
            scale: float,
            fmt: str,
            thumb: Optional[int],
            fast: bool,
            quality: int,
    ):
        try:
            stat = os.stat(volumePath)
            mtimeNs = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
            sizeBytes = int(stat.st_size)
        except Exception:
            mtimeNs = None
            sizeBytes = None

        return (
            os.path.abspath(str(volumePath)),
            mtimeNs,
            sizeBytes,
            str(tomogramId),
            int(sliceIndex),
            str(axis or "z").lower(),
            str(colormap or ""),
            str(normalize or "minmax").lower(),
            float(scale or 1.0),
            str(fmt or "webp").lower(),
            int(thumb or 0),
            bool(fast),
            int(quality or 75),
        )

    def _getCachedVolumeSliceResponse(self, cacheKey) -> Optional[Response]:
        with _VOLUME_SLICE_CACHE_LOCK:
            cached = _VOLUME_SLICE_CACHE.get(cacheKey)
            if cached is None:
                return None

            _VOLUME_SLICE_CACHE.move_to_end(cacheKey)

        headers = dict(cached.get("headers") or {})
        headers.pop("content-length", None)
        headers.pop("Content-Length", None)

        headers["X-Preview-Cache"] = "hit"
        self._exposeHeader(headers, "X-Preview-Cache")

        return Response(
            content=cached["body"],
            media_type=cached.get("mediaType") or "image/webp",
            headers=headers,
        )

    def _storeCachedVolumeSliceResponse(self, cacheKey, response: Response) -> Response:
        body = getattr(response, "body", None)
        if body is None:
            return response

        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("Content-Length", None)

        mediaType = getattr(response, "media_type", None) or headers.get("content-type")

        with _VOLUME_SLICE_CACHE_LOCK:
            _VOLUME_SLICE_CACHE[cacheKey] = {
                "body": bytes(body),
                "headers": headers,
                "mediaType": mediaType,
            }
            _VOLUME_SLICE_CACHE.move_to_end(cacheKey)

            while len(_VOLUME_SLICE_CACHE) > _VOLUME_SLICE_CACHE_MAX_ITEMS:
                _VOLUME_SLICE_CACHE.popitem(last=False)

        response.headers["X-Preview-Cache"] = "miss"
        self._exposeHeader(response.headers, "X-Preview-Cache")

        return response

    def _exposeHeader(self, headers, headerName: str) -> None:
        exposeKey = "Access-Control-Expose-Headers"
        current = headers.get(exposeKey, "")
        parts = [h.strip() for h in str(current).split(",") if h.strip()]

        if headerName not in parts:
            parts.append(headerName)

        headers[exposeKey] = ", ".join(parts)

    def renderVolumeSliceService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            volumeId: Union[int, str],
            sliceIndex: int,
            axis: str,
            colormap: Optional[str],
            normalize: Optional[str],
            scale: float,
            inline: bool,
            fmt: str = "webp",
            thumb: Optional[int] = None,
            fast: bool = True,
            quality: int = 75,
            mapper=None,
    ) -> Response:
        pgReader = self._getPostgresqlVolumeReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            info = pgReader.getVolumeFile(volumeId)
            if info is not None:
                volumePath = info.get("fileName") or info.get("path")
                if volumePath and os.path.exists(str(volumePath)):
                    cacheKey = self._buildVolumeSliceCacheKey(
                        volumePath=str(volumePath),
                        tomogramId=volumeId,
                        sliceIndex=sliceIndex,
                        axis=axis,
                        colormap=colormap,
                        normalize=normalize or "minmax",
                        scale=scale,
                        fmt=fmt,
                        thumb=thumb,
                        fast=fast,
                        quality=quality,
                    )

                    cachedResponse = self._getCachedVolumeSliceResponse(cacheKey)
                    if cachedResponse is not None:
                        return cachedResponse

                    response = self._renderTomogramSliceFromPath(
                        volumePath=str(volumePath),
                        tomogramId=volumeId,
                        sliceIndex=sliceIndex,
                        axis=axis,
                        colormap=colormap,
                        normalize=normalize or "minmax",
                        scale=scale,
                        inline=inline,
                        fmt=fmt,
                        thumb=thumb,
                        fast=fast,
                        quality=quality,
                    )

                    return self._storeCachedVolumeSliceResponse(cacheKey, response)

            logger.info(
                "Skipping PostgreSQL volume slice reader. projectId=%s protocolId=%s outputName=%s volumeId=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                volumeId,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Volume slice",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
                volumeId=volumeId,
            )

        protocol, output = self._resolveOutputForVolumes(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )
        op = OutputsPreview(self.currentProject, protocol, output)
        return op.renderVolumeSlice(
            volumeId=volumeId,
            sliceIndex=sliceIndex,
            axis=axis,
            colormap=colormap,
            normalize=normalize,
            scale=scale,
            inline=inline,
            fmt=fmt,
            thumb=thumb,
            fast=fast,
            quality=quality,
        )

    def getVolumeData3dService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            volumeId: Union[int, str],
            maxDim: int = 160,
            method: str = "binning",
            mapper=None,
    ):
        pgReader = self._getPostgresqlVolumeReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            result = pgReader.getVolumeArray(volumeId)
            if result is not None:
                volume, _props, _info = result

                if (method or "").lower() == "none":
                    volumeSmall = np.asarray(volume, dtype=np.float32)
                else:
                    volumeSmall = self._downsampleVolumePreview(
                        np.asarray(volume, dtype=np.float32),
                        maxDim=maxDim,
                        method=method,
                    )

                z, y, x = volumeSmall.shape
                return {
                    "dims": [int(z), int(y), int(x)],
                    "values": volumeSmall.ravel(order="C").astype(np.float32).tolist(),
                }

            logger.info(
                "Skipping PostgreSQL volume data3d reader. projectId=%s protocolId=%s outputName=%s volumeId=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                volumeId,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Volume 3D data",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
                volumeId=volumeId,
            )

        protocol, output = self._resolveOutputForVolumes(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )
        volumePath = self._getVolumePathFromOutput(output, volumeId)

        try:
            vol, _props = readVolumeArray3d(volumePath)
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Volume file not found on disk")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Cannot read volume file: {e}")

        if (method or "").lower() == "none":
            volSmall = np.asarray(vol, dtype=np.float32)
        else:
            volSmall = self._downsampleVolumePreview(vol, maxDim=maxDim, method=method)

        z, y, x = volSmall.shape
        return {
            "dims": [int(z), int(y), int(x)],
            "values": volSmall.ravel(order="C").astype(np.float32).tolist(),
        }

    def _getVolumePathFromOutput(self, output, volumeId: Union[int, str]) -> str:
        """Resolve a concrete volume path from an output (Volume / SetOfVolumes / VolumeMask)."""
        if isinstance(output, SetOfVolumes):
            try:
                vid = int(volumeId)
            except Exception:
                raise HTTPException(status_code=400, detail="volumeId must be an integer")

            item = output.getItem('_objId', vid + 1)
            if item is None:
                raise HTTPException(status_code=404, detail="Volume not found in SetOfVolumes")
            volumePath = item.getFileName()
        else:
            getFileNameFn = getattr(output, "getFileName", None)
            if not callable(getFileNameFn):
                raise HTTPException(status_code=404, detail="Output has no getFileName()")
            volumePath = getFileNameFn()

        if not volumePath or not os.path.exists(volumePath):
            raise HTTPException(status_code=404, detail="Volume file not found on disk")

        return volumePath

    def _readVolumeAsNumpy(self, volumePath: str) -> np.ndarray:
        """
        Read a volume file into a numpy array (Z,Y,X).
        Tries Scipion/pwem readers first, falls back to mrcfile/numpy when possible.
        """
        ext = os.path.splitext(volumePath)[1].lower()

        # Numpy formats
        if ext in (".npy",):
            arr = np.load(volumePath)
            return np.asarray(arr, dtype=np.float32)

        if ext in (".npz",):
            zf = np.load(volumePath)
            for k in ("data", "volume", "arr_0"):
                if k in zf:
                    return np.asarray(zf[k], dtype=np.float32)
            firstKey = list(zf.keys())[0]
            return np.asarray(zf[firstKey], dtype=np.float32)

        # Try Scipion image readers registry
        try:
            reader = ImageReadersRegistry.getReader(volumePath)
            if reader is not None:
                data = reader.read(volumePath)
                return np.asarray(data, dtype=np.float32)
        except Exception:
            pass

        # Try pwem ImageHandler
        try:
            from pwem.emlib.image import ImageHandler
            ih = ImageHandler()
            ih.read(volumePath)
            data = ih.getData()
            return np.asarray(data, dtype=np.float32)
        except Exception:
            pass

        # Last resort: mrcfile if available
        try:
            import mrcfile
            with mrcfile.open(volumePath, permissive=True) as m:
                data = m.data
            return np.asarray(data, dtype=np.float32)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Cannot read volume file '{volumePath}': {e}",
            )

    def _downsampleVolumePreview(
            self,
            vol: np.ndarray,
            maxDim: int,
            method: str = "binning",
    ) -> np.ndarray:
        """
        Downsample a volume to a preview size suitable for web 3D rendering.
        - binning: real-space average pooling with integer factor
        - linear: scipy.ndimage.zoom (if available), else binning
        - fourier: Fourier crop + inverse FFT
        """
        if vol is None or vol.ndim != 3:
            raise HTTPException(status_code=500, detail="Invalid volume data")

        z, y, x = vol.shape
        m = max(z, y, x)

        if m <= maxDim:
            return vol.astype(np.float32)

        methodLower = (method or "binning").lower()

        if methodLower == "fourier":
            return self._resizeVolumeFourier(vol, maxDim)

        if methodLower == "linear":
            try:
                from scipy.ndimage import zoom
                scale = maxDim / float(m)
                small = zoom(vol, zoom=scale, order=1, prefilter=False)
                return np.asarray(small, dtype=np.float32)
            except Exception:
                pass

        factor = int(np.ceil(m / float(maxDim)))
        return self._binVolume(vol, factor)

    def _binVolume(self, vol: np.ndarray, factor: int) -> np.ndarray:
        """Real-space average binning by an integer factor."""
        if factor <= 1:
            return vol.astype(np.float32)

        z, y, x = vol.shape
        z2 = (z // factor) * factor
        y2 = (y // factor) * factor
        x2 = (x // factor) * factor

        volC = vol[:z2, :y2, :x2]

        binned = volC.reshape(
            z2 // factor, factor,
            y2 // factor, factor,
            x2 // factor, factor
        ).mean(axis=(1, 3, 5))

        return np.asarray(binned, dtype=np.float32)

    def _resizeVolumeFourier(self, vol: np.ndarray, maxDim: int) -> np.ndarray:
        """Fourier crop downsample (low-pass) preserving global structure."""
        z, y, x = vol.shape
        m = max(z, y, x)
        if m <= maxDim:
            return vol.astype(np.float32)

        scale = maxDim / float(m)
        tz = max(8, int(z * scale))
        ty = max(8, int(y * scale))
        tx = max(8, int(x * scale))

        f = np.fft.fftn(vol)
        fshift = np.fft.fftshift(f)

        cropped = self._centerCrop3d(fshift, (tz, ty, tx))

        out = np.fft.ifftn(np.fft.ifftshift(cropped)).real
        out *= (z * y * x) / float(tz * ty * tx)

        return np.asarray(out, dtype=np.float32)

    def _strideDownsampleVolume(self, volume: np.ndarray,
                                maxDim: int) -> np.ndarray:
        z, y, x = volume.shape
        largestDim = max(z, y, x)
        if largestDim <= maxDim:
            return volume.astype(np.float32, copy=False)

        step = max(1, int(np.ceil(largestDim / float(maxDim))))
        return volume[::step, ::step, ::step].astype(np.float32, copy=False)

    def _downsampleVolumeForSurface(
            self,
            volume: np.ndarray,
            *,
            maxDim: int,
            method: str,
    ) -> np.ndarray:
        methodLower = (method or "stride").lower()

        if methodLower == "none":
            return volume.astype(np.float32, copy=False)

        if methodLower == "stride":
            return self._strideDownsampleVolume(volume,
                                                maxDim=maxDim)

        return self._downsampleVolumePreview(volume,
                                             maxDim=maxDim,
                                             method=methodLower)

    def getVolumeSurfaceMesh(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            volumeId: Union[int, str],
            level,
            maxDim,
            method,
            maxTriangles,
            currentUser,
            mapper=None,
    ):
        pgReader = self._getPostgresqlVolumeReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            result = pgReader.getVolumeArray(volumeId)
            if result is not None:
                volume, _props, _info = result
                volumeSmall = self._downsampleVolumeForSurface(
                    np.asarray(volume, dtype=np.float32),
                    maxDim=maxDim,
                    method=method,
                )

                mesh = buildVolumeSurfaceMesh(
                    volumeSmall,
                    level=level,
                    maxTriangles=maxTriangles,
                )

                mesh["sourceDims"] = [int(volume.shape[0]), int(volume.shape[1]), int(volume.shape[2])]
                mesh["maxDim"] = int(maxDim)
                mesh["method"] = method
                mesh["volumeId"] = str(volumeId)
                mesh["outputName"] = outputName

                response = JSONResponse(mesh)
                response.headers["X-Debug-Auth"] = "ok"
                response.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
                response.headers["Vary"] = "Authorization"
                return response

            logger.info(
                "Skipping PostgreSQL volume surface reader. projectId=%s protocolId=%s outputName=%s volumeId=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                volumeId,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Volume surface mesh",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
                volumeId=volumeId,
            )

        protocol, output = self._resolveOutputForVolumes(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )
        volumePath = self._getVolumePathFromOutput(output, volumeId)

        volume, _props = readVolumeArray3d(volumePath)
        volumeSmall = self._downsampleVolumeForSurface(
            volume,
            maxDim=maxDim,
            method=method,
        )

        mesh = buildVolumeSurfaceMesh(
            volumeSmall,
            level=level,
            maxTriangles=maxTriangles,
        )

        mesh["sourceDims"] = [int(volume.shape[0]), int(volume.shape[1]), int(volume.shape[2])]
        mesh["maxDim"] = int(maxDim)
        mesh["method"] = method
        mesh["volumeId"] = str(volumeId)
        mesh["outputName"] = outputName

        response = JSONResponse(mesh)
        response.headers["X-Debug-Auth"] = "ok"
        response.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
        response.headers["Vary"] = "Authorization"
        return response

    def _centerCrop3d(self, fshift: np.ndarray, targetShape: Tuple[int, int, int]) -> np.ndarray:
        """Crop a centered 3D Fourier volume to targetShape (tz, ty, tx)."""
        tz, ty, tx = targetShape
        z, y, x = fshift.shape

        z0 = max(0, (z - tz) // 2)
        y0 = max(0, (y - ty) // 2)
        x0 = max(0, (x - tx) // 2)

        return fshift[z0:z0 + tz, y0:y0 + ty, x0:x0 + tx]

    def listOutputTiltSeriesService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            mapper=None,
    ):
        """
        List all tilt series in a SetOfTiltSeries-like output.

        Shape:
        [
          {
            "tiltSeriesId": "...",
            "label": "...",
            "nViews"?: number,
            "dims"?: [w, h, ...],
            "pixelSize"?: number,
            "tiltAxisAngle"?: number,
          },
          ...
        ]
        """
        pgReader = self._getPostgresqlTiltSeriesReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            return pgReader.listTiltSeries()

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="TiltSeries",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason="reader_not_available",
            )

        _, setOfTiltSeries = self._resolveOutputForTiltSeries(
            protocolId=protocolId,
            outputName=outputName,
            projectId=projectId,
            mapper=mapper,
        )

        seriesList: List[Dict[str, Any]] = []
        for idx, ts in enumerate(setOfTiltSeries.iterItems(iterate=False)):
            try:
                summary = self._buildTiltSeriesSummary(ts)
                seriesList.append(summary)
            except Exception as e:
                logger.warning("Failed to summarize TiltSeries #%s: %s", idx, e)

        return seriesList

    def getTiltSeriesFramesService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tiltSeriesId: Union[int, str],
            mapper=None,
    ):
        """
        Return metadata for all tilt images in a given tilt series.

        Shape:
        {
          "tiltSeriesId": ...,
          "label": "...",
          "tiltAxisAngle"?: number,
          "frames": [
            {
              "viewId": ...,
              "index": 0-based index,
              "order"?: number,
              "tiltAngle"?: number,
              "excluded"?: bool,
              "dose"?: number,
              "path"?: str,
              "rot"?: number,
              "shiftX"?: number,
              "shiftY"?: number,
            },
            ...
          ]
        }
        """
        pgReader = self._getPostgresqlTiltSeriesReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.getTiltSeriesFrames(tiltSeriesId)
            if payload is not None:
                return payload

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="TiltSeries frames",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason="frames_not_available" if pgReader is not None else "reader_not_available",
                tiltSeriesId=tiltSeriesId,
            )

        protocol, setOfTiltSeries = self._resolveOutputForTiltSeries(
            protocolId=protocolId,
            outputName=outputName,
            projectId=projectId,
            mapper=mapper,
        )
        targetKey = str(tiltSeriesId)
        selectedSummary: Optional[Dict[str, Any]] = None
        selectedSeries = setOfTiltSeries.getItem('_tsId', targetKey)
        if selectedSeries is None:
            raise HTTPException(
                status_code=404,
                detail=f"TiltSeries '{tiltSeriesId}' not found in output '{outputName}'",
            )

        frames: List[Dict[str, Any]] = []

        for idx, view in enumerate(selectedSeries.iterItems(iterate=False)):
            frame: Dict[str, Any] = {}
            # viewId
            frame["viewId"] = view.getObjId()
            frame["index"] = view.getIndex()
            frame["order"] = view.getAcquisitionOrder()
            frame["tiltAngle"] = view.getTiltAngle()

            # excluded flag
            excluded = False
            if hasattr(view, "isExcluded"):
                try:
                    excluded = bool(view.isExcluded())
                except Exception:
                    pass
            elif hasattr(view, "getIsExcluded"):
                try:
                    excluded = bool(view.getIsExcluded())
                except Exception:
                    pass
            elif hasattr(view, "isEnabled"):
                try:
                    enabled = bool(view.isEnabled())
                    excluded = not enabled
                except Exception:
                    pass
            elif hasattr(view, "getEnabled"):
                try:
                    enabled = bool(view.getEnabled())
                    excluded = not enabled
                except Exception:
                    pass
            else:
                for attrName in ("excluded", "_excluded", "skip", "_skip"):
                    try:
                        v = getattr(view, attrName, None)
                        if v is not None:
                            excluded = bool(v)
                            break
                    except Exception:
                        continue
            frame["excluded"] = excluded

            # dose
            dose = view.getAcquisition().getAccumDose()
            if dose is not None:
                frame["dose"] = dose

            # path
            path = view.getFileName()
            if path is not None:
                frame["path"] = str(view.getIndex()) + '@' + path

            # rotation and shifts
            rot = None
            shifts = None

            if view.hasTransform():
                transf = view.getTransform()
                _, _, rot = transf.getEulerAngles()
                rot = np.rad2deg(-rot)
                list = transf.getMatrixAsList()
                shifts = list[2], list[5]

            if rot is not None:
                frame["rot"] = rot

            # shifts
            if shifts is not None:
                frame["shiftX"] = shifts[0]
                frame["shiftY"] = shifts[1]

            frames.append(frame)

        payload: Dict[str, Any] = {
            "tiltSeriesId": selectedSummary.get("tiltSeriesId") if selectedSummary else tiltSeriesId,
            "label": selectedSummary.get("label") if selectedSummary else str(tiltSeriesId),
            "frames": frames,
        }

        if selectedSummary and "tiltAxisAngle" in selectedSummary:
            payload["tiltAxisAngle"] = selectedSummary["tiltAxisAngle"]

        return payload

    def createNewSetOfCtftomoSeriesService(
        self,
        projectId: int,
        protocolId: int,
        outputName: str,
        exclusions: Dict[str, Any],
        restack: bool,
        mapper=None,
    ) -> Dict[str, Any]:
        """
        Create a new SetOfCTFTomoSeries applying per-series and per-tilt exclusions.

        Exclusions schema:

        {
          "<tsId>": {
            "excluded": bool,           # exclude entire tilt series
            "tiltimages": [1, 5, 12],   # per-tilt indices (1-based)
          },
          ...
        }
        """
        protocol, inputSet = self._resolveOutputForCtftomoSeries(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )

        # Normalize exclusions keys to strings
        normalizedExclusions: Dict[str, Dict[str, Any]] = {}
        for key, value in (exclusions or {}).items():
            normalizedExclusions[str(key)] = value or {}

        # New output name and set object
        newOutputName = protocol.getNextOutputName("CTFTomoSeries")
        outputSet = inputSet.createCopy(protocol._getPath(), prefix=newOutputName, copyInfo=True)
        createdCount = 0
        for seriesIndex, ctfSeries in enumerate(inputSet.iterItems(iterate=False)):
            tsId = ctfSeries.getTsId()
            tsKey = str(tsId)
            tsExcl = normalizedExclusions.get(tsKey, {})
            seriesExcluded = bool(tsExcl.get("excluded", False))
            rawTiltIndices = tsExcl.get("tiltimages") or []
            newSeries = ctfSeries.clone()
            newSeries.setEnabled(True)

            if seriesExcluded:
                continue

            outputSet.append(newSeries)
            createdCount += 1
            outputSet.setSetOfTiltSeries(inputSet.getSetOfTiltSeries())
            for ctfObj in ctfSeries.iterItems(iterate=False):
                ctfEstItem = ctfObj.clone()
                ctfEstItem.setEnabled(ctfObj.getIndex() not in rawTiltIndices)
                newSeries.append(ctfEstItem)
            try:
                newSeries.write()
                outputSet.update(newSeries)
                outputSet.write()
            except Exception:
                logger.exception("Error storing Ctftomo series %s in new set %s", tsId, newOutputName,)
                continue

        if outputSet.isEmpty():
            logger.info("No Ctftomo series were generated in new set '%s'", newOutputName)
            return {
                "status": "empty",
                "outputName": newOutputName,
                "createdSeries": 0,
                "restack": bool(restack),
                "message": "No output was generated because it cannot be empty",
            }
        postgresqlSync = None
        postgresqlError = None

        try:
            protocol._defineOutputs(**{newOutputName: outputSet})
            protocol._store()

            postgresqlStore = self._storeGeneratedSetInPostgresql(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                outputName=newOutputName,
                scipionSet=outputSet,
                contextLabel="CTFTomo",
            )
            postgresqlSync = postgresqlStore["postgresqlSync"]
            postgresqlError = postgresqlStore["postgresqlError"]

        except Exception:
            logger.exception("Error attaching Ctftomo filtered set '%s' to protocol", newOutputName)

        logger.info(
            "The new Ctftomo set (%s) has been created successfully with %d series",
            newOutputName,
            createdCount,
        )

        return {
            "status": 0,
            "outputName": newOutputName,
            "createdSeries": createdCount,
            "restack": bool(restack),
            "postgresqlSync": postgresqlSync,
            "postgresqlError": postgresqlError,
        }

    def _buildTiltSeriesPreviewCacheKey(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tiltSeriesId: Union[int, str],
            index: int,
            size: int,
            fmt: str,
            applyTransform: bool,
            inline: bool,
            imagePath: str,
    ) -> Tuple[Any, ...]:
        # buildTiltSeriesPreviewCacheKey
        absPath = os.path.abspath(str(imagePath))

        try:
            stat = os.stat(absPath)
            fileMtimeNs = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
            fileSize = int(stat.st_size)
        except Exception:
            fileMtimeNs = 0
            fileSize = 0

        return (
            int(projectId),
            int(protocolId),
            str(outputName),
            str(tiltSeriesId),
            int(index),
            int(size),
            str(fmt or "png").lower(),
            bool(applyTransform),
            bool(inline),
            absPath,
            fileMtimeNs,
            fileSize,
        )

    def _ensureTiltSeriesPreviewCacheHeader(
            self,
            headers: Dict[str, str],
            cacheState: str,
    ) -> Dict[str, str]:
        # ensureTiltSeriesPreviewCacheHeader
        nextHeaders = dict(headers or {})
        nextHeaders["X-Preview-Cache"] = cacheState

        exposeRaw = nextHeaders.get("Access-Control-Expose-Headers", "")
        exposeItems = [h.strip() for h in exposeRaw.split(",") if h.strip()]
        if "X-Preview-Cache" not in exposeItems:
            exposeItems.append("X-Preview-Cache")
        nextHeaders["Access-Control-Expose-Headers"] = ", ".join(exposeItems)

        return nextHeaders

    def _getTiltSeriesPreviewFromCache(self, cacheKey: Tuple[Any, ...]) -> Optional[Response]:
        # getTiltSeriesPreviewFromCache
        with _tiltSeriesPreviewCacheLock:
            cached = _tiltSeriesPreviewCache.get(cacheKey)
            if not cached:
                return None

            _tiltSeriesPreviewCache.move_to_end(cacheKey)

            headers = self._ensureTiltSeriesPreviewCacheHeader(
                cached.get("headers") or {},
                "HIT",
            )

            return Response(
                content=cached.get("body") or b"",
                media_type=cached.get("mediaType") or "image/png",
                headers=headers,
            )

    def _storeTiltSeriesPreviewInCache(
            self,
            cacheKey: Tuple[Any, ...],
            response: Any,
    ) -> Any:
        # storeTiltSeriesPreviewInCache
        headersObj = getattr(response, "headers", None)
        if headersObj is None or not hasattr(headersObj, "update"):
            return response

        body = getattr(response, "body", None)

        if body is None:
            response.headers.update(
                self._ensureTiltSeriesPreviewCacheHeader(
                    dict(response.headers),
                    "SKIP",
                )
            )
            return response

        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("Content-Length", None)

        mediaType = getattr(response, "media_type", None) or headers.get("content-type") or "image/png"

        with _tiltSeriesPreviewCacheLock:
            _tiltSeriesPreviewCache[cacheKey] = {
                "body": bytes(body),
                "headers": headers,
                "mediaType": mediaType,
            }
            _tiltSeriesPreviewCache.move_to_end(cacheKey)

            while len(_tiltSeriesPreviewCache) > _TILT_SERIES_PREVIEW_CACHE_LIMIT:
                _tiltSeriesPreviewCache.popitem(last=False)

        response.headers.update(
            self._ensureTiltSeriesPreviewCacheHeader(
                dict(response.headers),
                "MISS",
            )
        )

        return response

    def renderTiltSeriesImageService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tiltSeriesId: Union[int, str],
            index: int = 0,
            size: int = 1024,
            fmt: str = "png",
            applyTransform: bool = True,
            inline: bool = True,
            requestHeaders: Optional[Dict[str, str]] = None,
            mapper=None,
    ):

        pgReader = self._getPostgresqlTiltSeriesReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            frame = pgReader.getTiltImageFrame(tiltSeriesId, index)
            if frame is not None:
                try:
                    imagePath, imageIndex = self._parseTiltSeriesFramePath(
                        frame.get("path"),
                        fallbackIndex=int(index),
                    )

                    if mapper is not None and getattr(mapper, "db", None) is not None:
                        from app.backend.viewers.postgresql_path_resolver import (
                            PostgresqlProjectPathResolver,
                        )

                        resolvedImagePath = PostgresqlProjectPathResolver(
                            db=mapper.db,
                            projectId=projectId,
                        ).resolveExistingPath(imagePath)

                        if resolvedImagePath:
                            imagePath = resolvedImagePath

                    cacheKey = self._buildTiltSeriesPreviewCacheKey(
                        projectId=projectId,
                        protocolId=protocolId,
                        outputName=outputName,
                        tiltSeriesId=tiltSeriesId,
                        index=imageIndex,
                        size=size,
                        fmt=fmt,
                        applyTransform=applyTransform,
                        inline=inline,
                        imagePath=imagePath,
                    )

                    cachedResponse = self._getTiltSeriesPreviewFromCache(cacheKey)
                    if cachedResponse is not None:
                        return cachedResponse

                    rot = None
                    shifts = None

                    if applyTransform:
                        rot = frame.get("rot")
                        shiftX = frame.get("shiftX")
                        shiftY = frame.get("shiftY")
                        if shiftX is not None and shiftY is not None:
                            shifts = (shiftX, shiftY)

                    preview = OutputsPreview(
                        currentProject=self.currentProject,
                        protocol=None,
                        output=None,
                        requestHeaders=requestHeaders,
                    )

                    response = preview.renderImageFromFilePath(
                        imagePath,
                        size=size,
                        fmt=fmt,
                        index=imageIndex,
                        applyTransform=applyTransform,
                        inline=inline,
                        rot=rot,
                        shifts=shifts,
                    )

                    return self._storeTiltSeriesPreviewInCache(cacheKey, response)


                except HTTPException:
                    logger.exception(
                        "Failed to render TiltSeries image from PostgreSQL. projectId=%s protocolId=%s outputName=%s tiltSeriesId=%s index=%s",
                        projectId,
                        protocolId,
                        outputName,
                        tiltSeriesId,
                        index,
                    )
                    raise

                except Exception as e:
                    logger.exception(
                        "Failed to render TiltSeries image from PostgreSQL. projectId=%s protocolId=%s outputName=%s tiltSeriesId=%s index=%s",
                        projectId,
                        protocolId,
                        outputName,
                        tiltSeriesId,
                        index,
                    )

                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to render TiltSeries image from PostgreSQL metadata: {e}",

                    )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="TiltSeries image",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
                tiltSeriesId=tiltSeriesId,
                index=index,
            )

        protocol, setOfTiltSeries = self._resolveOutputForTiltSeries(
            protocolId=protocolId,
            outputName=outputName,
            projectId=projectId,
            mapper=mapper,
        )
        ts = setOfTiltSeries.getItem('_tsId', tiltSeriesId)

        if ts is None:
            raise HTTPException(
                status_code=404,
                detail=f"TiltSeries '{tiltSeriesId}' not found in output '{outputName}'",
            )

        ti = ts.getItem('_index', index)

        if ti is None:
            raise HTTPException(
                status_code=404,
                detail=f"Tilt image index '{index}' not found in tiltSeries '{tiltSeriesId}'",
            )

        imagePath = os.path.abspath(ti.getFileName())

        cacheKey = self._buildTiltSeriesPreviewCacheKey(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            tiltSeriesId=tiltSeriesId,
            index=index,
            size=size,
            fmt=fmt,
            applyTransform=applyTransform,
            inline=inline,
            imagePath=imagePath,
        )

        cachedResponse = self._getTiltSeriesPreviewFromCache(cacheKey)
        if cachedResponse is not None:
            return cachedResponse

        rot = shifts = None
        if applyTransform and ti.hasTransform():
            transf = ti.getTransform()
            _, _, rot = transf.getEulerAngles()
            rot = np.rad2deg(-rot)
            matrixValues = transf.getMatrixAsList()
            shifts = matrixValues[2], matrixValues[5]

        preview = OutputsPreview(
            currentProject=self.currentProject,
            protocol=protocol,
            output=ts,
            requestHeaders=requestHeaders,
        )

        response = preview.renderImageFromFilePath(
            imagePath,
            size=size,
            fmt=fmt,
            index=index,
            applyTransform=applyTransform,
            inline=inline,
            rot=rot,
            shifts=shifts,
        )

        return self._storeTiltSeriesPreviewInCache(cacheKey, response)

    def renderTiltSeriesImagesBatchService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tiltSeriesId: Union[int, str],
            indices: Sequence[int],
            size: int = 512,
            fmt: str = "webp",
            applyTransform: bool = True,
            inline: bool = True,
            requestHeaders: Optional[Dict[str, str]] = None,
            mapper=None,
    ) -> Dict[str, Any]:
        # renderTiltSeriesImagesBatchService
        cleanIndices: List[int] = []
        seenIndices: TypingSet[int] = set()

        for rawIndex in indices or []:
            try:
                index = int(rawIndex)
            except (TypeError, ValueError):
                continue

            if index < 0 or index in seenIndices:
                continue

            cleanIndices.append(index)
            seenIndices.add(index)

            if len(cleanIndices) >= 24:
                break

        items: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for index in cleanIndices:
            try:
                response = self.renderTiltSeriesImageService(
                    projectId=projectId,
                    protocolId=protocolId,
                    outputName=outputName,
                    tiltSeriesId=tiltSeriesId,
                    index=index,
                    size=size,
                    fmt=fmt,
                    applyTransform=applyTransform,
                    inline=inline,
                    requestHeaders=requestHeaders,
                    mapper=mapper,
                )

                body = getattr(response, "body", None) or b""
                mediaType = (
                        getattr(response, "media_type", None)
                        or response.headers.get("content-type")
                        or "image/png"
                )

                dataUrl = "data:%s;base64,%s" % (
                    mediaType,
                    base64.b64encode(body).decode("ascii"),
                )

                items.append({
                    "index": index,
                    "contentType": mediaType,
                    "dataUrl": dataUrl,
                    "cache": response.headers.get("X-Preview-Cache"),
                })

            except HTTPException as exc:
                errors.append({
                    "index": index,
                    "error": str(exc.detail),
                })
            except Exception as exc:
                errors.append({
                    "index": index,
                    "error": str(exc),
                })

        return {
            "tiltSeriesId": str(tiltSeriesId),
            "size": int(size),
            "fmt": str(fmt or "webp").lower(),
            "applyTransform": bool(applyTransform),
            "items": items,
            "errors": errors,
        }

    def createNewSetOfTiltSeriesService(
        self,
        projectId: int,
        protocolId: int,
        outputName: str,
        exclusions: Dict[str, Any],
        restack: bool,
        mapper=None
    ) -> Dict[str, Any]:
        """
        Create a new SetOfTiltSeries applying per-tilt-series and per-tilt exclusions.

        The `exclusions` dict is expected to have the shape:
        {
            "<tsId>": {
                "excluded": bool,
                "tiltimages": [index1, index2, ...]  # tilt indices (1-based)
            },
            ...
        }

        Returns a JSON-serializable payload for the web UI with basic metadata.
        """
        # Resolve protocol and input set for the given output
        protocol, inputSet = self._resolveOutputForTiltSeries(
            protocolId=protocolId,
            outputName=outputName,
            projectId=projectId,
            mapper=mapper,
        )
        hasOddEven = inputSet.hasOddEven()

        # Normalize exclusions keys to strings (tsId can be int/str on the backend)
        normalizedExclusions: Dict[str, Dict[str, Any]] = {}
        for key, value in (exclusions or {}).items():
            normalizedExclusions[str(key)] = value or {}

        # New output name and path for the created SetOfTiltSeries
        newOutputName = protocol.getNextOutputName("TiltSeries_")
        outputPath = os.path.join(protocol._getExtraPath(), newOutputName)

        # Create the output set with copied info
        outputSet = SetOfTiltSeries.create(
            protocol.getPath(),
            suffix=str(protocol.getOutputsSize()),
        )
        outputSet.copyInfo(inputSet)
        outputSet.setDim(inputSet.getDim())

        if restack and not os.path.exists(outputPath):
            os.mkdir(outputPath)

        totalInputSeries = inputSet.getSize() if hasattr(inputSet, "getSize") else None

        for tsIndex, ts in enumerate(inputSet.iterItems(iterate=False)):
            tsId = ts.getTsId()
            tsKey = str(tsId)

            # Per-tilt-series exclusion info
            tsExcl = normalizedExclusions.get(tsKey, {})
            seriesExcluded = bool(tsExcl.get("excluded", False))

            # Per-tilt-image exclusions: indices (1-based)
            rawTiltIndices = tsExcl.get("tiltimages") or []
            excludedTiltIndices: TypingSet[int] = set()

            for v in rawTiltIndices:
                try:
                    excludedTiltIndices.add(int(v))
                except (TypeError, ValueError):
                    continue

            try:
                # Skip the whole tilt series if marked as excluded
                if seriesExcluded:
                    continue

                newTs = TiltSeries()
                newTs.copyInfo(ts)
                outputSet.append(newTs)

                newBinaryName = os.path.join(outputPath, f"{tsId}.mrcs")
                if hasOddEven:
                    oddFileName = ts.getOddFileName()
                    evenFileName = ts.getEvenFileName()
                    newOddBinaryName = os.path.join(outputPath, f"{tsId}_odd.mrcs")
                    newEvenBinaryName = os.path.join(outputPath, f"{tsId}_even.mrcs")

                # Create new stacks if restacking is enabled
                properties = {"sr": ts.getSamplingRate()}
                stack = ImageStack(properties)
                oddStack = ImageStack(properties)
                evenStack = ImageStack(properties)

                index = 1  # new index when restacking
                validImages = 0
                errorsCount = 0

                for ti in ts.iterItems(iterate=False):
                    try:
                        # In the web workflow, exclusions use tilt index (1-based)
                        tiIndex = getattr(ti, "getIndex", lambda: None)()
                        if tiIndex is None:
                            included = True
                        else:
                            included = int(tiIndex) not in excludedTiltIndices

                        if not restack or (included and restack):
                            newTi = self._cloneTiltImage(ti, included)

                            if restack:
                                oldIndex = str(ti.getIndex())
                                stack.append(
                                    ImageReadersRegistry.open(
                                        f"{oldIndex}@{ti.getFileName()}"
                                    )
                                )
                                newTi.setLocation((index, newBinaryName))

                                if hasOddEven:
                                    oddStack.append(
                                        ImageReadersRegistry.open(
                                            f"{oldIndex}@{oddFileName}"
                                        )
                                    )
                                    evenStack.append(
                                        ImageReadersRegistry.open(
                                            f"{oldIndex}@{evenFileName}"
                                        )
                                    )
                                    newTi.setOddEven(
                                        [newOddBinaryName, newEvenBinaryName]
                                    )

                                index += 1

                            newTs.append(newTi)
                            validImages += 1

                    except Exception:
                        errorsCount += 1
                        logger.exception(
                            "Error processing tilt image in tilt series %s (tilt index %s)",
                            tsId,
                            getattr(ti, "getIndex", lambda: "unknown")(),
                        )
                        continue

                # If no image was processed successfully and at least one failed,
                # skip this tilt series completely (do not write or add it to the output set).
                if validImages == 0 and errorsCount > 0:
                    logger.warning(
                        "Skipping tilt series %s (%d/%s): all tilt images failed. "
                        "Check log for details.",
                        tsId,
                        tsIndex + 1,
                        totalInputSeries if totalInputSeries is not None else "?",
                    )
                    # Remove empty newTs from the output set if it was added
                    try:
                        outputSet.remove(newTs)
                    except Exception:
                        pass
                    continue

                if restack:
                    ImageReadersRegistry.write(stack, newBinaryName, isStack=True)
                    if hasOddEven:
                        ImageReadersRegistry.write(
                            oddStack, newOddBinaryName, isStack=True
                        )
                        ImageReadersRegistry.write(
                            evenStack, newEvenBinaryName, isStack=True
                        )

                # If all tilts are excluded, disable this tilt series
                if excludedTiltIndices and len(excludedTiltIndices) == ts.getSize():
                    newTs.setEnabled(False)

                newTs.setDim(ts.getDim())
                newTs.setAnglesCount(newTs.getSize())
                newTs.write()
                outputSet.update(newTs)

            except Exception:
                logger.exception(
                    "Error processing tilt series %s (%d/%s)",
                    tsId or "unknown",
                    tsIndex + 1,
                    totalInputSeries if totalInputSeries is not None else "?",
                )
                # Do not propagate; continue with next tilt series
                continue

        createdCount = outputSet.getSize()
        if not createdCount:
            logger.info("No output was generated because it cannot be empty")
            return {
                "status": "empty",
                "outputName": newOutputName,
                "createdTiltSeries": 0,
                "hasOddEven": bool(hasOddEven),
                "restack": bool(restack),
                "message": "No output was generated because it cannot be empty",
            }

        outputSet.write()
        protocol._defineOutputs(**{newOutputName: outputSet})
        protocol._store()

        postgresqlStore = self._storeGeneratedSetInPostgresql(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=newOutputName,
            scipionSet=outputSet,
            contextLabel="TiltSeries",
        )
        postgresqlSync = postgresqlStore["postgresqlSync"]
        postgresqlError = postgresqlStore["postgresqlError"]

        logger.info("The new set (%s) has been created successfully", newOutputName)

        return {
            "status": 0,
            "outputName": newOutputName,
            "createdTiltSeries": createdCount,
            "hasOddEven": bool(hasOddEven),
            "restack": bool(restack),
            "postgresqlSync": postgresqlSync,
            "postgresqlError": postgresqlError,
        }

    def _cloneTiltImage(self, ti, included):
        newTi = ti.clone()
        newTi.copyInfo(ti, copyId=False)
        newTi.setObjId(None)
        newTi.setAcquisition(ti.getAcquisition())
        newTi.setEnabled(included)
        return newTi

    # ----------------------------------------------------------------------
    # Analyze Results: Coordinates3D
    # ----------------------------------------------------------------------
    def _getPostgresqlCoords3dReaderIfAvailable(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            outputName: str,
    ):
        if mapper is None:
            return None

        try:
            from app.backend.viewers.postgresql_coords3d_reader import PostgresqlCoords3dReader

            readerProtocolId = self._resolvePostgresqlReaderProtocolId(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

            reader = PostgresqlCoords3dReader(
                db=mapper.db,
                projectId=projectId,
                protocolId=readerProtocolId,
                outputName=outputName,
            )

            if reader.hasOutput():
                return reader

        except Exception:
            logger.exception(
                "Failed to initialize PostgreSQL Coordinates3D reader. projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
            )

        return None

    def _resolveOutputForCoordinates3d(
            self,
            protocolId: int,
            outputName: str,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        output = getattr(protocol, outputName, None)
        if output is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Output '{outputName}' not found in protocol",
            )

        return protocol, output

    def listCoordinates3dTomogramsService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            mapper=None,
    ):
        """
        Return a list of tomograms referenced by the SetOfCoordinates3D output.

        Normalized shape:
        [
          { "id": <tomoId>, "name": "<label>" },
          ...
        ]
        """
        pgReader = self._getPostgresqlCoords3dReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.listTomograms()
            if payload is not None:
                self.tomoList = {}
                return payload

            logger.info(
                "Skipping PostgreSQL Coordinates3D tomograms reader. projectId=%s protocolId=%s outputName=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            raise HTTPException(
                status_code=404,
                detail="Coordinates3D output is not available in PostgreSQL metadata",
            )

        protocol, setOfCoordinates3D = self._resolveOutputForCoordinates3d(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )
        self.tomoList = {}
        tomogramList: List[Dict[str, Any]] = []
        tomosIter = None

        for attrName in ("iterTomograms", "iterVolumes"):
            func = getattr(setOfCoordinates3D, attrName, None)
            if callable(func):
                try:
                    tomosIter = func()
                    break
                except Exception:
                    tomosIter = None

        if tomosIter is None:
            getTomos = getattr(setOfCoordinates3D, "getTomograms", None)
            if callable(getTomos):
                try:
                    tomos = getTomos()
                    tomosIter = (
                        tomos.iterItems() if hasattr(tomos, "iterItems") else iter(tomos)
                    )
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to iterate tomograms: {e}",
                    )

        if tomosIter is None:
            raise HTTPException(
                status_code=500,
                detail="SetOfCoordinates3D does not expose tomograms iterator",
            )

        if hasattr(tomosIter, "iterItems"):
            iterator = tomosIter.iterItems()
        else:
            iterator = iter(tomosIter)

        for index, tomo in enumerate(iterator):
            tomoId = None
            for fnName in ("getTsId", "getObjId"):
                fn = getattr(tomo, fnName, None)
                if callable(fn):
                    try:
                        tomoId = fn()
                        if tomoId is not None:
                            break
                    except Exception:
                        continue
            if tomoId is None:
                tomoId = index
            self.tomoList[tomoId] = tomo
            label = None
            for fnName in ("getObjLabel", "getNameId", "getFileName"):
                fn = getattr(tomo, fnName, None)
                if callable(fn):
                    try:
                        label = fn()
                        if label:
                            break
                    except Exception:
                        continue

            if not label:
                label = str(tomoId)

            sr = tomo.getSamplingRate()

            tomogramList.append(
                {
                    "id": tomoId,
                    "name": str(label),
                    "label": tomoId,
                    "dims": list(tomo.getDim()),
                    "voxelSize": [sr, sr, sr],
                }
            )

        return tomogramList

    def getCoordinates3dPointsService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tomogramId: Union[int, str],
            mapper=None,
    ):
        """
        Return a flat list of 3D points for one tomogram.
        Each point is {x, y, z, ...optional fields}.

        Returned shape:
        [
          {
            "x": number,
            "y": number,
            "z": number,
            "id"?: number | str,
            "classId"?: number,
            "label"?: string,
            "score"?: number,
            "weight"?: number,
            "radius"?: number,
            "tomoId"?: number | str,
            "matrix"?: list
          },
          ...
        ]
        """
        pgReader = self._getPostgresqlCoords3dReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.getPoints(tomogramId)
            if payload is not None:
                return payload

            logger.info(
                "Skipping PostgreSQL Coordinates3D points reader. projectId=%s protocolId=%s outputName=%s tomogramId=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                tomogramId,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Coordinates3D points",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
            )

        protocol, setOfCoordinates3D = self._resolveOutputForCoordinates3d(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )

        try:
            boxSize = float(setOfCoordinates3D.getBoxSize())
        except Exception:
            boxSize = None

        key: Union[int, str] = tomogramId
        if isinstance(tomogramId, str):
            try:
                key = int(tomogramId)
            except ValueError:
                key = tomogramId

        try:
            if self.tomoList:
                tomogram = self.tomoList[key]
            else:
                tomogram = setOfCoordinates3D._getTomogram(key)
        except Exception:
            tomogram = None

        if tomogram is None:
            raise HTTPException(
                status_code=404,
                detail=f"Tomogram '{tomogramId}' not found in SetOfCoordinates3D",
            )

        try:
            tomoId = tomogram.getTsId()
        except Exception:
            tomoId = getattr(tomogram, "getObjId", lambda: None)()

        points: List[Dict[str, Any]] = []

        try:
            coordsIter = setOfCoordinates3D.iterCoordinates(tomogram)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to iterate coordinates: {e}",
            )

        for coord in coordsIter:
            try:
                x = float(coord.getX(BOTTOM_LEFT_CORNER))
                y = float(coord.getY(BOTTOM_LEFT_CORNER))
                z = float(coord.getZ(BOTTOM_LEFT_CORNER))
            except Exception:
                continue

            p: Dict[str, Any] = {"x": x, "y": y, "z": z}

            getIdFn = getattr(coord, "getObjId", None)
            if callable(getIdFn):
                try:
                    objId = getIdFn()
                    if objId is not None:
                        p["id"] = objId
                except Exception:
                    pass

            getClassFn = getattr(coord, "getClassId", None)
            if callable(getClassFn):
                try:
                    classId = getClassFn()
                    if classId is not None:
                        p["classId"] = classId
                except Exception:
                    pass

            label = getattr(coord, "_objLabel", None)
            if not label and hasattr(coord, "getObjLabel"):
                try:
                    label = coord.getObjLabel()
                except Exception:
                    label = None
            if label not in (None, ""):
                p["label"] = str(label)

            score = getattr(coord, "_score", None)
            if score is None and hasattr(coord, "getScore"):
                try:
                    score = coord.getScore()
                except Exception:
                    score = None
            if score is not None:
                try:
                    p["score"] = float(score)
                except Exception:
                    pass

            getWeightFn = getattr(coord, "getWeight", None)
            if callable(getWeightFn):
                try:
                    w = getWeightFn()
                    if w is not None:
                        p["weight"] = float(w)
                except Exception:
                    pass

            if boxSize is not None:
                p["radius"] = float(boxSize)

            matrix = coord.getMatrix()
            p['matrix'] = matrix.tolist()

            p["tomoId"] = tomoId

            points.append(p)

        return points

    def _coords3dPilTo2dTile(self, imgStk, pilImg) -> Optional[np.ndarray]:
        """
        Convert a PIL tomogram slice into a small 2D float array.

        - Downsamples to <= maxThumbSize without upscaling.
        - Converts to grayscale if needed.
        - Applies highlightSlice/normalizeSlice at most once.
        - Returns float32 2D array; caller can decide final uint8/colormap.
        """
        try:
            width, height = pilImg.size
            scale = min(
                maxThumbSize / float(width),
                maxThumbSize / float(height),
                1.0,
            )
            thumbWidth = max(1, int(round(width * scale)))
            thumbHeight = max(1, int(round(height * scale)))

            if pilImg.mode not in ("L", "I;16", "F"):
                pilGray = pilImg.convert("L")
            else:
                pilGray = pilImg

            if thumbWidth < width or thumbHeight < height:
                pilGray = pilGray.copy()
                pilGray.thumbnail((thumbWidth, thumbHeight))

            arr = np.asarray(pilGray, dtype=np.float32)

            arr = np.squeeze(arr)
            if arr.ndim != 2 or arr.size == 0:
                return None

            try:
                arr = imgStk.highlightSlice(arr)
                arr = imgStk.normalizeSlice(arr)
            except Exception:
                pass

            return arr.astype(np.float32, copy=False)
        except Exception:
            return None

    def _normalize2dSlice(self, a: np.ndarray, mode: str = "minmax") -> np.ndarray:
        """
        Normalize a 2D slice into uint8 according to mode: 'minmax' | 'zscore' | 'none'.

        Safeguards:
        - Accepts any numeric dtype.
        - If already uint8 and mode in ('minmax', 'none'), returns a copy directly.
        - Handles NaNs and constant arrays without blowing up.
        """
        if a.ndim != 2:
            raise ValueError("Expected 2D slice")

        arr = np.asarray(a)

        if arr.dtype == np.uint8 and (mode or "minmax").lower() in ("minmax", "none"):
            return arr.copy()

        arr = arr.astype(np.float32, copy=False)
        mode = (mode or "minmax").lower()

        finiteMask = np.isfinite(arr)
        if not finiteMask.all():
            if finiteMask.any():
                fillVal = float(np.nanmedian(arr[finiteMask]))
            else:
                fillVal = 0.0
            arr = np.where(finiteMask, arr, fillVal)

        if mode == "zscore":
            mu = float(np.mean(arr))
            sd = float(np.std(arr))
            if sd == 0.0 or not np.isfinite(sd):
                return np.zeros_like(arr, dtype=np.uint8)
            arr = (arr - mu) / sd
            arr = np.clip(arr, -3.0, 3.0)
            amin, amax = float(arr.min()), float(arr.max())
            if amax <= amin:
                return np.zeros_like(arr, dtype=np.uint8)
            arr = (arr - amin) / (amax - amin + 1e-12)
            return (255.0 * arr).astype(np.uint8)

        amin, amax = float(arr.min()), float(arr.max())
        if (not np.isfinite(amin)) or (not np.isfinite(amax)) or amax <= amin:
            return np.zeros_like(arr, dtype=np.uint8)

        arr = (arr - amin) / (amax - amin + 1e-12)
        return (255.0 * arr).astype(np.uint8)

    def renderCoords3dTomogramSliceService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tomogramId: Union[int, str],
            sliceIndex: int,
            axis: str = "z",
            colormap: Optional[str] = None,
            normalize: Optional[str] = "minmax",
            scale: float = 1.0,
            inline: bool = True,
            fmt: str = "webp",
            thumb: Optional[int] = 128,
            fast: bool = True,
            quality: int = 75,
            mapper=None,
    ) -> Response:
        """
        Render a 2D slice from a tomogram referenced by a SetOfCoordinates3D.

        Fast path:
          - axis == 'z' and fast == True
          - Uses ImageReadersRegistry.open + getImage(pilImage=True)
          - Uses Scipion helpers to enhance contrast.

        Slow path:
          - Other axes or fast path failure
          - Uses cached readVolumeArray3d to avoid reloading on each request.
        """
        from PIL import Image as PILImage

        pgReader = self._getPostgresqlCoords3dReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            tomogramInfo = pgReader.getTomogramFile(tomogramId)
            if tomogramInfo is not None:
                volumePath = tomogramInfo.get("fileName")
                if volumePath and os.path.exists(volumePath):
                    return self._renderTomogramSliceFromPath(
                        volumePath=volumePath,
                        tomogramId=tomogramId,
                        sliceIndex=sliceIndex,
                        axis=axis,
                        colormap=colormap,
                        normalize=normalize,
                        scale=scale,
                        inline=inline,
                        fmt=fmt,
                        thumb=thumb,
                        fast=fast,
                        quality=quality,
                    )

            logger.info(
                "Skipping PostgreSQL Coordinates3D tomogram slice reader. projectId=%s protocolId=%s outputName=%s tomogramId=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                tomogramId,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Coordinates3D tomogram slice",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
            )

        protocol, setOfCoordinates3D = self._resolveOutputForCoordinates3d(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )

        try:
            if self.tomoList:
                tomogram = self.tomoList[tomogramId]
            else:
                tomogram = setOfCoordinates3D._getTomogram(tomogramId)
        except Exception:
            tomogram = None

        if tomogram is None:
            raise HTTPException(
                status_code=404,
                detail=f"Tomogram '{tomogramId}' not found in SetOfCoordinates3D",
            )

        getFileNameFn = getattr(tomogram, "getFileName", None)
        if not callable(getFileNameFn):
            raise HTTPException(
                status_code=404,
                detail="Tomogram object has no getFileName()",
            )

        volumePath = getFileNameFn()
        if not volumePath or not os.path.exists(volumePath):
            raise HTTPException(
                status_code=404,
                detail="Tomogram file not found on disk",
            )

        axis = (axis or "z").lower()
        if axis not in ("x", "y", "z"):
            axis = "z"

        fmtLower = (fmt or "png").lower()
        if fmtLower in ("jpg", "jpeg"):
            pilFormat = "JPEG"
            mediaType = "image/jpeg"
            saveKw = {"quality": int(quality or 75)}
        elif fmtLower == "webp":
            pilFormat = "WEBP"
            mediaType = "image/webp"
            saveKw = {"quality": int(quality or 75)}
        else:
            pilFormat = "PNG"
            mediaType = "image/png"
            saveKw = {}

        usedColormap = colormap
        gray: Optional[np.ndarray] = None
        depth = 1

        try:
            requestedIndex = int(sliceIndex or 0)
        except Exception:
            requestedIndex = 0
        requestedIndex = max(0, requestedIndex)

        sliceUsed = requestedIndex
        if axis == "z" and fast:
            try:
                reader = ImageReadersRegistry.open(volumePath)

                try:
                    images = reader.getImages()
                    if hasattr(images, "ndim") and images.ndim == 3:
                        zdim, ydim, xdim = int(images.shape[0]), int(images.shape[1]), int(images.shape[2])
                    elif hasattr(images, "ndim") and images.ndim == 2:
                        zdim, ydim, xdim = 1, int(images.shape[0]), int(images.shape[1])
                    else:
                        zdim, ydim, xdim = 1, 0, 0
                except Exception:
                    zdim, ydim, xdim = 1, 0, 0

                depth = max(zdim, 1)

                k = requestedIndex
                if zdim > 0:
                    k = max(0, min(k, zdim - 1))

                try:
                    pilImg = reader.getImage(index=k, pilImage=True)
                except Exception:
                    try:
                        pilImg = reader.getCentralImage(pilImage=True)
                        if zdim > 0:
                            k = max(0, min(zdim // 2, max(zdim - 1, 0)))
                        else:
                            k = 0
                    except Exception:
                        pilImg = reader.getImage(index=0, pilImage=True)
                        k = 0

                arr2d = self._coords3dPilTo2dTile(reader, pilImg)
                if arr2d is None:
                    arrRaw = np.asarray(pilImg)
                    if arrRaw.ndim == 3:
                        arr2d = arrRaw.mean(axis=-1)
                    else:
                        arr2d = arrRaw.astype(np.float32, copy=False)

                gray = self._normalize2dSlice(arr2d, mode=normalize)
                sliceUsed = k
            except Exception:
                gray = None

        if gray is None:
            try:
                vol3d, _props = readVolumeArray3d(str(volumePath))  # Z, Y, X
            except HTTPException:
                raise
            except FileNotFoundError:
                raise HTTPException(
                    status_code=404,
                    detail="Tomogram file not found on disk",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read tomogram volume: {e}",
                )

            if vol3d.ndim != 3:
                raise HTTPException(
                    status_code=500,
                    detail=f"Invalid tomogram volume shape {vol3d.shape}",
                )

            zdim, ydim, xdim = int(vol3d.shape[0]), int(vol3d.shape[1]), int(vol3d.shape[2])
            depth = max(zdim, 1)

            if axis == "z":
                dim = zdim
            elif axis == "y":
                dim = ydim
            else:
                dim = xdim

            if dim <= 0:
                raise HTTPException(status_code=500, detail="Empty tomogram volume")

            k = max(0, min(requestedIndex, dim - 1))

            if axis == "z":
                slice2d = vol3d[k, :, :]
            elif axis == "y":
                slice2d = vol3d[:, k, :]
            else:
                slice2d = vol3d[:, :, k]

            gray = self._normalize2dSlice(slice2d, mode=normalize)
            sliceUsed = k

        if thumb is not None and thumb > 0:
            pilTmp = PILImage.fromarray(gray.astype(np.uint8), mode="L")
            pilTmp.thumbnail((thumb, thumb))
            gray = np.asarray(pilTmp)

            if gray.dtype != np.uint8:
                gray = gray.astype(np.uint8, copy=False)

        imgArray = gray.astype(np.uint8, copy=False)
        pilMode = "L"

        if usedColormap:
            try:
                import matplotlib.cm as cm
                sliceNorm = imgArray.astype(np.float32) / 255.0
                cmapObj = cm.get_cmap(usedColormap)
                rgba = cmapObj(sliceNorm)
                rgb = (rgba[..., :3] * 255.0).clip(0, 255).astype(np.uint8)
                imgArray = rgb
                pilMode = "RGB"
            except Exception:
                usedColormap = None
                imgArray = gray.astype(np.uint8, copy=False)
                pilMode = "L"

        if scale is not None and scale != 1.0:
            try:
                pilScale = PILImage.fromarray(imgArray, mode=pilMode)
                newW = max(1, int(round(pilScale.width * float(scale))))
                newH = max(1, int(round(pilScale.height * float(scale))))
                pilScale = pilScale.resize((newW, newH), resample=PILImage.Resampling.BILINEAR)
                imgArray = np.asarray(pilScale, copy=False)
            except Exception:
                pass

        img = PILImage.fromarray(imgArray, mode=pilMode)

        buf = io.BytesIO()
        img.save(buf, format=pilFormat, **saveKw)

        disp = "inline" if inline else "attachment"
        filename = f"coords3d_{tomogramId}_axis-{axis}_slice-{sliceUsed}.{fmtLower}"

        headers = {
            "Content-Disposition": f'{disp}; filename="{filename}"',
            "Access-Control-Expose-Headers": (
                "Content-Disposition, "
                "X-Preview-Mime, "
                "X-Preview-Width, "
                "X-Preview-Height, "
                "X-Preview-Depth, "
                "X-Preview-Colormap, "
                "X-Preview-Format, "
                "X-Preview-TomogramId"
            ),
            "X-Preview-Mime": mediaType,
            "X-Preview-Width": str(img.width),
            "X-Preview-Height": str(img.height),
            "X-Preview-Depth": str(depth),
            "X-Preview-Colormap": usedColormap or "",
            "X-Preview-Format": pilFormat,
            "X-Preview-TomogramId": str(tomogramId),
        }

        return Response(content=buf.getvalue(), media_type=mediaType, headers=headers)

    def _renderTomogramSliceFromPath(
            self,
            volumePath: str,
            tomogramId: Union[int, str],
            sliceIndex: int,
            axis: str = "z",
            colormap: Optional[str] = None,
            normalize: Optional[str] = "minmax",
            scale: float = 1.0,
            inline: bool = True,
            fmt: str = "webp",
            thumb: Optional[int] = 128,
            fast: bool = True,
            quality: int = 75,
    ) -> Response:

        from PIL import Image as PILImage

        axis = (axis or "z").lower()
        if axis not in ("x", "y", "z"):
            axis = "z"

        fmtLower = (fmt or "png").lower()
        if fmtLower in ("jpg", "jpeg"):
            pilFormat = "JPEG"
            mediaType = "image/jpeg"
            saveKw = {"quality": int(quality or 75)}
        elif fmtLower == "webp":
            pilFormat = "WEBP"
            mediaType = "image/webp"
            saveKw = {"quality": int(quality or 75)}
        else:
            pilFormat = "PNG"
            mediaType = "image/png"
            saveKw = {}

        usedColormap = colormap
        gray: Optional[np.ndarray] = None
        depth = 1

        try:
            requestedIndex = int(sliceIndex or 0)
        except Exception:
            requestedIndex = 0
        requestedIndex = max(0, requestedIndex)

        sliceUsed = requestedIndex
        if axis == "z" and fast:
            try:
                reader = ImageReadersRegistry.open(volumePath)

                try:
                    images = reader.getImages()
                    if hasattr(images, "ndim") and images.ndim == 3:
                        zdim, ydim, xdim = int(images.shape[0]), int(images.shape[1]), int(images.shape[2])
                    elif hasattr(images, "ndim") and images.ndim == 2:
                        zdim, ydim, xdim = 1, int(images.shape[0]), int(images.shape[1])
                    else:
                        zdim, ydim, xdim = 1, 0, 0
                except Exception:
                    zdim, ydim, xdim = 1, 0, 0

                depth = max(zdim, 1)

                k = requestedIndex
                if zdim > 0:
                    k = max(0, min(k, zdim - 1))

                try:
                    pilImg = reader.getImage(index=k, pilImage=True)
                except Exception:
                    try:
                        pilImg = reader.getCentralImage(pilImage=True)
                        if zdim > 0:
                            k = max(0, min(zdim // 2, max(zdim - 1, 0)))
                        else:
                            k = 0
                    except Exception:
                        pilImg = reader.getImage(index=0, pilImage=True)
                        k = 0

                arr2d = self._coords3dPilTo2dTile(reader, pilImg)
                if arr2d is None:
                    arrRaw = np.asarray(pilImg)
                    if arrRaw.ndim == 3:
                        arr2d = arrRaw.mean(axis=-1)
                    else:
                        arr2d = arrRaw.astype(np.float32, copy=False)

                gray = self._normalize2dSlice(arr2d, mode=normalize)
                sliceUsed = k
            except Exception:
                gray = None

        if gray is None:
            try:
                slice2d, _props, sliceMeta = readVolumeSlice2d(
                    str(volumePath),
                    sliceIndex=requestedIndex,
                    axis=axis,
                    maxSide=thumb,
                )
            except HTTPException:
                raise
            except FileNotFoundError:
                raise HTTPException(
                    status_code=404,
                    detail="Tomogram file not found on disk",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read tomogram slice: {e}",
                )

            zdim, ydim, xdim = sliceMeta.get("dims", (1, 1, 1))
            depth = max(int(zdim), 1)

            gray = self._normalize2dSlice(slice2d, mode=normalize)
            sliceUsed = int(sliceMeta.get("index", requestedIndex))

        if thumb is not None and thumb > 0:
            pilTmp = PILImage.fromarray(gray.astype(np.uint8), mode="L")
            pilTmp.thumbnail((thumb, thumb))
            gray = np.asarray(pilTmp)

            if gray.dtype != np.uint8:
                gray = gray.astype(np.uint8, copy=False)

        imgArray = gray.astype(np.uint8, copy=False)
        pilMode = "L"

        if usedColormap:
            try:
                import matplotlib.cm as cm
                sliceNorm = imgArray.astype(np.float32) / 255.0
                cmapObj = cm.get_cmap(usedColormap)
                rgba = cmapObj(sliceNorm)
                rgb = (rgba[..., :3] * 255.0).clip(0, 255).astype(np.uint8)
                imgArray = rgb
                pilMode = "RGB"
            except Exception:
                usedColormap = None
                imgArray = gray.astype(np.uint8, copy=False)
                pilMode = "L"

        if scale is not None and scale != 1.0:
            try:
                pilScale = PILImage.fromarray(imgArray, mode=pilMode)
                newW = max(1, int(round(pilScale.width * float(scale))))
                newH = max(1, int(round(pilScale.height * float(scale))))
                pilScale = pilScale.resize((newW, newH), resample=PILImage.Resampling.BILINEAR)
                imgArray = np.asarray(pilScale, copy=False)
            except Exception:
                pass

        img = PILImage.fromarray(imgArray, mode=pilMode)

        buf = io.BytesIO()
        img.save(buf, format=pilFormat, **saveKw)

        disp = "inline" if inline else "attachment"
        filename = f"coords3d_{tomogramId}_axis-{axis}_slice-{sliceUsed}.{fmtLower}"

        headers = {
            "Content-Disposition": f'{disp}; filename="{filename}"',
            "Access-Control-Expose-Headers": (
                "Content-Disposition, "
                "X-Preview-Mime, "
                "X-Preview-Width, "
                "X-Preview-Height, "
                "X-Preview-Depth, "
                "X-Preview-Colormap, "
                "X-Preview-Format, "
                "X-Preview-TomogramId"
            ),
            "X-Preview-Mime": mediaType,
            "X-Preview-Width": str(img.width),
            "X-Preview-Height": str(img.height),
            "X-Preview-Depth": str(depth),
            "X-Preview-Colormap": usedColormap or "",
            "X-Preview-Format": pilFormat,
            "X-Preview-TomogramId": str(tomogramId),
        }

        return Response(content=buf.getvalue(), media_type=mediaType, headers=headers)

    def createCoords3dOutputFromPointsService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            payload: Any,
            mapper=None
    ) -> Dict[str, Any]:

        tomograms = payload['tomograms']

        # ---------------------------------
        # 1. Obtaining protocol and origin
        # ---------------------------------
        protocol, srcSet = self._resolveOutputForCoordinates3d(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )

        runtimeProtocolId = getattr(protocol, "getObjId", lambda: protocolId)()

        # -------------------------------
        # 2. Ensure tomograms
        # -------------------------------
        if not self.tomoList:
            self.listCoordinates3dTomogramsService(
                projectId=projectId,
                protocolId=runtimeProtocolId,
                outputName=outputName,
                mapper=None,
            )

        # -----------------------------------
        # 3. Creating new SetOfCoordinates3D
        # -----------------------------------
        try:
            outName = protocol.getNextOutputName(outputName)
        except Exception:
            outName = f"{'SetOfCoordinates3D'}_{uuid4().hex[:6]}"

        try:
            dstSet = srcSet.createCopy(protocol._getPath(), prefix=outName, copyInfo=True)
        except TypeError:
            dstSet = srcSet.createCopy(protocol._getPath(), prefix=outName)

        if hasattr(srcSet, "getTomograms"):
            try:
                dstSet.setTomograms(srcSet.getTomograms())
            except Exception:
                pass

        # -------------------------------
        # 4. Build new coordinates
        # -------------------------------
        replaced = 0
        copied = 0

        for tomoKey, tomoObj in self.tomoList.items():
            for tomogram in tomograms:
                if tomogram['tomoId'] == tomoKey:
                    coords = tomogram['coords']
                    for coord in coords:
                        c = Coordinate3D()
                        c.setObjId(None)
                        c.setVolume(tomoObj)
                        c.setPosition(coord['x'], coord['y'], coord['z'], BOTTOM_LEFT_CORNER)
                        groupId = coord['groupId'] if 'groupId' in coord else 0
                        c.setGroupId(groupId)
                        c.setTomoId(coord['tomoId'])
                        c.setBoxSize(dstSet.getSamplingRate())
                        score = coord['score'] if 'score' in coord else 0
                        c.setScore(score)
                        transformMatrix = coord['matrix'] if 'matrix' in coord else None
                        if transformMatrix:
                            transformMatrix = np.array(transformMatrix)
                            c.setMatrix(transformMatrix)
                        dstSet.append(c)
                        replaced += 1
                    break
        # ------------------------------------
        # 5. Saving and registering the output
        # ------------------------------------
        try:
            dstSet.write()
        except Exception:
            pass
        try:
            protocol._defineOutputs(**{outName: dstSet})
            protocol._store()
        except Exception as e:
            raise HTTPException(500, f"Failed to attach new coords3d output: {e}")

        postgresqlStore = self._storeGeneratedSetInPostgresql(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outName,
            scipionSet=dstSet,
            contextLabel="Coordinates3D",
        )
        postgresqlError = postgresqlStore["postgresqlError"]
        postgresqlStored = mapper is not None and postgresqlError is None

        return {
            "success": True,
            "outputName": outName,
            "message": f"Created new coords3d output '{outName}'",
            "data": {
                "sourceOutputName": outputName,
                "replacedPoints": replaced,
                "copiedPoints": copied,
                "postgresqlStored": postgresqlStored,
                "postgresqlError": postgresqlError,
            },
        }

    # ======================================================================
    # Internal helpers for FSCs
    # ======================================================================
    def _getPostgresqlFscReaderIfAvailable(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            outputName: str,
    ):
        if mapper is None:
            return None

        try:
            from app.backend.viewers.postgresql_fsc_reader import PostgresqlFscReader

            readerProtocolId = self._resolvePostgresqlReaderProtocolId(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

            reader = PostgresqlFscReader(
                db=mapper.db,
                projectId=projectId,
                protocolId=readerProtocolId,
                outputName=outputName,
            )

            if reader.hasOutput():
                return reader

        except Exception:
            logger.exception(
                "Failed to initialize PostgreSQL FSC reader. projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
            )

        return None

    def _ensureRuntimeProjectForFscRows(
            self,
            mapper,
            projectId: int,
            currentUser: Optional[dict] = None,
    ) -> None:
        if getattr(self, "currentProject", None) is not None:
            return

        if mapper is None or currentUser is None:
            return

        self.getProjectById(
            mapper,
            projectId,
            currentUser,
            refresh=False,
            checkPid=False,
        )

    def getFscRowsService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            mapper=None,
            currentUser: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """
        Return FSC curves for a SetOfFSCs-like output.
        """
        pgReader = self._getPostgresqlFscReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.getFscRows()
            if payload is not None and payload.get("rows"):
                return payload

            logger.info(
                "Skipping PostgreSQL FSC reader. projectId=%s protocolId=%s outputName=%s reason=%s",
                projectId,
                protocolId,
                outputName,
                getattr(pgReader, "lastSkipReason", None),
            )

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="FSC",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason=getattr(pgReader, "lastSkipReason", None) if pgReader is not None else "reader_not_available",
            )

        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        output = getattr(protocol, outputName, None)
        if output is None:
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' not found in protocol",
            )

        threshold = 0.143

        def iterFscObjects():
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

            raise HTTPException(
                status_code=500,
                detail="Output does not expose iterable FSC objects",
            )

        def getXY(fsc):
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

        rows: List[Dict[str, Any]] = []

        for i, fsc in enumerate(iterFscObjects()):
            if fsc is None:
                continue

            clone = getattr(fsc, "clone", lambda: fsc)()

            label = getattr(clone, "getObjLabel", lambda: None)() or f"FSC {i + 1}"

            try:
                x, y = getXY(clone)
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

    # ======================================================================
    # Internal helpers for metadata tables (STAR / SQLITE / etc.)
    # ======================================================================

    def _resolveOutputForMetadata(
            self,
            protocolId: int,
            outputName: str,
            mapper=None,
            projectId: Optional[int] = None,
    ):
        """
        Resolve protocol and output object for metadata operations.

        It also normalizes the metadata file path:
        - If getFileName() returns a relative path, it is interpreted as
          project-relative.
        - Raises 404 if the final path does not exist on disk.
        """
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if not hasattr(protocol, outputName):
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' not found in protocol"
            )

        output = getattr(protocol, outputName)
        if output is None:
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' is None"
            )

        getFileNameFn = getattr(output, "getFileName", None)
        if not callable(getFileNameFn):
            raise HTTPException(
                status_code=404,
                detail="Output has no metadata file (getFileName not available)"
            )

        metaPath = getFileNameFn()

        if not metaPath:
            logger.warning(
                "[METADATA] Empty metaPath for project=%s protocolId=%s outputName=%s",
                getattr(self.currentProject, "getName", lambda: '<?>')(),
                protocolId,
                outputName,
            )
            raise HTTPException(
                status_code=404,
                detail="Metadata file not found for this output"
            )

        # If path is not absolute, interpret it as project-relative
        if not os.path.isabs(metaPath):
            projectPath = None
            try:
                projectPath = self.currentProject.getPath()
            except Exception:
                projectPath = None

            if projectPath:
                metaPath = os.path.join(projectPath, metaPath)

        if not os.path.exists(metaPath):
            logger.warning(
                "[METADATA] Metadata file does not exist on disk. "
                "project=%s protocolId=%s outputName=%s metaPath=%s",
                getattr(self.currentProject, "getName", lambda: '<?>')(),
                protocolId,
                outputName,
                metaPath,
            )
            raise HTTPException(
                status_code=404,
                detail="Metadata file not found for this output"
            )

        return protocol, output, metaPath

    def _getMetadataObjectManager(self, metaPath: str) -> ObjectManager:
        """
        Configure ObjectManager to work over the given metadata file.

        A fresh ObjectManager is created per call to avoid sharing
        SQLite connections between threads.
        """
        objMgr = self._createObjectManager()
        objMgr._fileName = FsPath(metaPath)
        objMgr._dao = None
        objMgr._tables = {}
        objMgr.selectDAO()
        objMgr.getTables()
        return objMgr

    def _getPostgresqlDAOIfAvailable(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            mapper=None,
    ):
        from app.backend.viewers.postgresql_dao import PostgresqlDAO

        if mapper is None:
            return None

        readerProtocolId = self._resolvePostgresqlReaderProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        dao = PostgresqlDAO(
            db=mapper.db,
            projectId=projectId,
            protocolId=readerProtocolId,
            outputName=outputName,
        )

        if dao.hasOutput():
            return dao

        return None

    def _getMetadataObjectManagerForOutput(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            mapper=None,
    ) -> ObjectManager:
        pgDao = self._getPostgresqlDAOIfAvailable(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
        )

        if pgDao is not None:
            objMgr = self._createObjectManager()
            objMgr._fileName = "postgresql://project/%s/protocol/%s/output/%s" % (
                projectId,
                protocolId,
                outputName,
            )
            objMgr._dao = pgDao
            objMgr._tables = {}
            objMgr.getTables()
            return objMgr

        if mapper is not None:
            self._raisePostgresqlViewerUnavailable(
                viewerName="Metadata",
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                reason="dao_not_available",
            )

        _, _, metaPath = self._resolveOutputForMetadata(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )
        return self._getMetadataObjectManager(metaPath)

    def _openMetadataTable(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tableName: str,
            mapper=None,
    ):
        """
        Resolve (ObjectManager, Table) for a given output + tableName.

        PostgreSQL persisted outputs and SQLite/STAR outputs are both exposed
        through ObjectManager.
        """
        objMgr = self._getMetadataObjectManagerForOutput(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
        )

        table = objMgr.getTable(tableName)
        if table is None:
            raise HTTPException(
                status_code=404,
                detail=f"Metadata table '{tableName}' not found",
            )

        return objMgr, table

    def _isPropertiesMetadataTable(self, table) -> bool:
        try:
            tableName = str(table.getName() or "").strip()
        except Exception:
            tableName = ""

        try:
            tableAlias = str(table.getAlias() or "").strip()
        except Exception:
            tableAlias = ""

        return tableName == "Properties" or tableAlias == "Properties"

    def _getMetadataTableActionNames(self, table) -> List[str]:
        if self._isPropertiesMetadataTable(table):
            return []

        try:
            tableActions = table.getActions() or []
        except Exception:
            return []

        actionNames: List[str] = []
        seen = set()

        for action in tableActions:
            try:
                actionName = str(action.getName() or "").strip()
            except Exception:
                actionName = ""

            if not actionName or actionName in seen:
                continue

            seen.add(actionName)
            actionNames.append(actionName)

        return actionNames

    def _rendererTypeFromInstance(self, renderer) -> str:
        """
        Map renderer class name to a simple type label for the API.
        """
        name = renderer.__class__.__name__
        mapping = {
            "IntRenderer": "int",
            "FloatRenderer": "float",
            "BoolRenderer": "bool",
            "MatrixRender": "matrix",
            "ImageRenderer": "image",
            "StrRenderer": "str",
        }
        return mapping.get(name, "str")

    def _convertCellForPage(self, renderer, rawValue, rowValues):
        """
        Convert a raw cell value + renderer into something JSON friendly for page API.
        - image  -> { kind: "image", path: "..." }
        - matrix -> { kind: "matrix", value: [[...], ...] }
        - others -> primitive (int/float/bool/str) when possible
        """
        clsName = renderer.__class__.__name__

        if clsName == "ImageRenderer":
            return {
                "kind": "image",
                "path": "" if rawValue is None else str(rawValue),
            }

        if clsName == "MatrixRender":
            try:
                rendered = renderer.render(rawValue, rowValues)
            except Exception:
                rendered = rawValue
            if isinstance(rendered, np.ndarray):
                renderedVal = rendered.tolist()
            else:
                renderedVal = rendered
            return {
                "kind": "matrix",
                "value": renderedVal,
            }

        try:
            rendered = renderer.render(rawValue, rowValues)
        except Exception:
            rendered = rawValue

        if isinstance(rendered, np.ndarray):
            rendered = rendered.tolist()
        if isinstance(rendered, np.generic):
            rendered = rendered.item()

        return rendered

    # ======================================================================
    # ANALYZE RESULTS: METADATA TABLES (.sqlite / .star / etc.)
    # ======================================================================

    def listOutputMetadataTablesService(self, projectId: int,
                                        protocolId: int,
                                        outputName: str,
                                        mapper=None):
        """
        List logical metadata tables associated with an output.
        """
        with _metadataLock:
            objMgr = self._getMetadataObjectManagerForOutput(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                mapper=mapper,
            )

            tables = objMgr.getTables() or {}
            items = []

            for name, table in tables.items():
                try:
                    rowCount = objMgr.getTableRowCount(name) or 0
                except Exception:
                    rowCount = 0

                hasColumnId = True
                try:
                    hasColumnId = table.hasColumnId()
                except Exception:
                    pass

                items.append({
                    "name": name,
                    "alias": table.getAlias(),
                    "rowCount": int(rowCount),
                    "hasColumnId": bool(hasColumnId),
                })

            return items

    def getMetadataTableSchemaService(self, projectId: int,
                                      protocolId: int,
                                      outputName: str,
                                      tableName: str,
                                      mapper=None):
        """
        Return logical schema for one metadata table: columns, renderers, flags.
        """
        with _metadataLock:
            objMgr, table = self._openMetadataTable(
                projectId,
                protocolId,
                outputName,
                tableName,
                mapper=mapper,
            )

            visibleLabels = []
            orderLabels = []
            renderLabels = []
            actions = self._getMetadataTableActionNames(table)

            try:
                hasColumnId = table.hasColumnId()
            except Exception:
                hasColumnId = True

            columns = list(table.getColumns())
            columnNames = {str(col.getName()) for col in columns}

            additionalInfoColumns = []
            try:
                dao = objMgr.getDAO()
                getAdditionalInfoFn = getattr(dao, "getTableWithAdditionalInfo", None)

                if callable(getAdditionalInfoFn):
                    additionalTable, additionalColumns = getAdditionalInfoFn()

                    if hasattr(additionalTable, "getName"):
                        additionalTableName = str(additionalTable.getName() or "")
                    else:
                        additionalTableName = "" if additionalTable is None else str(additionalTable)

                    currentTableNames = {
                        str(tableName or ""),
                        str(table.getName() or ""),
                        str(table.getAlias() or ""),
                    }

                    appliesToTable = not additionalTableName or additionalTableName in currentTableNames

                    if appliesToTable:
                        additionalInfoColumns = [
                            str(columnName)
                            for columnName in (additionalColumns or [])
                            if str(columnName) in columnNames
                        ]
            except Exception:
                additionalInfoColumns = []

            schema = {
                "name": tableName,
                "alias": table.getAlias(),
                "hasColumnId": bool(hasColumnId),
                "actions": actions,
                "additionalInfoColumns": additionalInfoColumns,
                # "renderLabels": renderLabels,
                # "orderLabels": orderLabels,
                "columns": [],
            }

            for idx, col in enumerate(columns):
                try:
                    col.setIndex(idx)
                except Exception:
                    pass

                renderer = col.getRenderer()
                rendererType = self._rendererTypeFromInstance(renderer)

                decimals = None
                if hasattr(renderer, "getDecimalsNumber"):
                    try:
                        decimals = renderer.getDecimalsNumber()
                    except Exception:
                        decimals = None

                hasTransformation = False
                if hasattr(renderer, "hasTransformation"):
                    try:
                        hasTransformation = bool(renderer.hasTransformation())
                    except Exception:
                        hasTransformation = False

                sortable = True
                if hasattr(col, "isSorteable"):
                    try:
                        sortable = bool(col.isSorteable())
                    except Exception:
                        sortable = True

                try:
                    visible = col.getName() in visibleLabels if visibleLabels else True
                except Exception:
                    visible = True

                schema["columns"].append({
                    "name": col.getName(),
                    "alias": col.getAlias() or col.getName(),
                    "index": idx,
                    "sortable": sortable,
                    "visible": visible,
                    "rendererType": rendererType,
                    "decimals": decimals,
                    "hasTransformation": hasTransformation,
                })

            return schema

    def _normalizeMetadataSelectionIds(self, ids: List[int]) -> List[int]:
        normalizedIds: List[int] = []

        for rowId in ids or []:
            try:
                normalizedIds.append(int(rowId))
            except Exception:
                continue

        if not normalizedIds:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Missing ids",
            )

        return normalizedIds

    def _writeMetadataSelectionFile(self, ids: List[int]) -> str:
        timeFormat = "%Y%m%d%H%M%S"
        timestamp = datetime.now().strftime(timeFormat)
        relativePath = "Logs/selection_%s.txt" % timestamp

        projectPath = None
        try:
            projectPath = self.currentProject.getPath()
        except Exception:
            projectPath = None

        if projectPath:
            absolutePath = os.path.join(projectPath, relativePath)
        else:
            absolutePath = relativePath

        directoryPath = os.path.dirname(absolutePath)
        if directoryPath:
            os.makedirs(directoryPath, exist_ok=True)

        try:
            with open(absolutePath, "w") as file:
                for rowId in ids:
                    file.write(str(rowId) + " ")

            logger.debug("Metadata selection file was created: %s", absolutePath)
        except Exception as e:
            logger.exception("Error creating metadata selection file: %s", absolutePath)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error creating selection file: {e}",
            )

        return relativePath

    def _buildMetadataSelectionArgument(self, selectionPath: str, tableName: str) -> str:
        selectionArg = selectionPath + ","

        if tableName != OBJECT_TABLE:
            selectionArg += tableName.split("_Objects")[0]

        return selectionArg

    def _getMetadataActionAliasForTable(self, dao, table) -> str:
        getActionAliasFn = getattr(dao, "_getActionAliasForTableName", None)
        if callable(getActionAliasFn):
            try:
                actionAlias = str(getActionAliasFn(table.getName()) or "").strip()
                if actionAlias:
                    return actionAlias
            except Exception:
                pass

        try:
            return str(table.getAlias() or "").strip()
        except Exception:
            return ""

    def _resolveMetadataActionOutputClassName(self, dao, table, action: str) -> str:
        actionName = str(action or "").strip()
        if not actionName:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Missing action",
            )

        validActions = self._getMetadataTableActionNames(table)
        if actionName not in validActions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported action '{actionName}' for table '{table.getName()}'",
            )

        actionAlias = self._getMetadataActionAliasForTable(dao, table)

        if actionAlias == "Class2D" and actionName == "Averages":
            return "SetOfAverages"

        if actionAlias == "Class3D" and actionName == "Volumes":
            return "SetOfVolumes"

        objectsType = getattr(dao, "_objectsType", {}) or {}

        if actionAlias == "Class2D":
            objectsType.setdefault("Averages", "SetOfAverages")

        if actionAlias == "Class3D":
            objectsType.setdefault("Volumes", "SetOfVolumes")

        outputClassName = objectsType.get(actionName)

        if outputClassName:
            return str(outputClassName)

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not resolve output class for action '{actionName}'",
        )

    def runMetadataTableActionService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tableName: str,
            action: str,
            subsetName: str,
            ids: List[int],
            currentUser: Any,
            mapper: Any,
    ) -> Any:
        selectionIds = self._normalizeMetadataSelectionIds(ids)

        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if not hasattr(protocol, outputName):
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' not found in protocol",
            )

        output = getattr(protocol, outputName)
        if output is None:
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' is None",
            )

        with _metadataLock:
            objMgr, table = self._openMetadataTable(
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
                tableName=tableName,
                mapper=mapper,
            )

            dao = objMgr.getDAO()
            outputClassName = self._resolveMetadataActionOutputClassName(
                dao=dao,
                table=table,
                action=action,
            )

        selectionPath = self._writeMetadataSelectionFile(selectionIds)
        selectionArg = self._buildMetadataSelectionArgument(
            selectionPath=selectionPath,
            tableName=tableName,
        )

        try:
            batchProt = self.currentProject.newProtocol(
                ProtUserSubSet,
                inputObject=output,
                sqliteFile=selectionArg,
                outputClassName=outputClassName,
                other="",
                label=subsetName,
            )

            self.currentProject.launchProtocol(batchProt)

            postgresqlSync = None
            try:
                postgresqlSync = self.syncProjectProtocolsAndDependencies(
                    mapper,
                    projectId,
                    refresh=True,
                    checkPid=True,
                )
            except Exception as syncError:
                logger.exception(
                    "Subset protocol was launched but PostgreSQL sync failed. projectId=%s protocolId=%s outputName=%s tableName=%s",
                    projectId,
                    protocolId,
                    outputName,
                    tableName,
                )
                return {
                    "success": True,
                    "message": "Subset protocol was launched successfully, but PostgreSQL sync failed",
                    "postgresqlSync": None,
                    "postgresqlError": str(syncError),
                }

            return {
                "success": True,
                "message": "Subset protocol was launched successfully",
                "postgresqlSync": postgresqlSync,
                "postgresqlError": None,
            }

        except Exception as e:
            logger.exception(
                "Failed to launch metadata table action. projectId=%s protocolId=%s outputName=%s tableName=%s action=%s",
                projectId,
                protocolId,
                outputName,
                tableName,
                action,
            )
            return {
                "success": False,
                "errors": [str(e)],
            }

    def getMetadataTablePageService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tableName: str,
            page: int,
            pageSize: int,
            sortBy: str,
            asc: bool,
            selectionOnly: bool,
            mapper=None,
    ):
        """
        Return one logical page of rows for a metadata table.
        Sorting is currently delegated to the underlying DAO default order.
        """
        with _metadataLock:
            objMgr, table = self._openMetadataTable(
                projectId,
                protocolId,
                outputName,
                tableName,
                mapper=mapper,
            )
            columns = list(table.getColumns())
            table.setSortingColumn(sortBy)
            table.setSortingAsc(asc)

            if selectionOnly:
                rows: list = []
                totalRows = 0
                try:
                    selection = table.getSelection()
                    if selection and not selection.isEmpty():
                        allIds = sorted(selection.getSelection().keys())
                        totalRows = len(allIds)
                        start = max(0, (page - 1) * pageSize)
                        end = start + pageSize
                        sliceIds = allIds[start:end]
                        for rid in sliceIds:
                            idx0 = max(0, int(rid) - 1)
                            chunk = objMgr.getRows(tableName, idx0, 1) or []
                            if chunk:
                                rows.append(chunk[0])
                    else:
                        totalRows = 0
                        rows = []
                except Exception:
                    totalRows = 0
                    rows = []
            else:
                try:
                    totalRows = objMgr.getTableRowCount(tableName) or 0
                except Exception:
                    totalRows = 0

                if totalRows <= 0:
                    rows = []
                else:
                    offset = max(0, (page - 1) * pageSize)
                    if offset >= totalRows:
                        rows = []
                    else:
                        rows = objMgr.getRows(tableName, offset, pageSize) or []

            resultRows = []
            for row in rows:
                try:
                    rowId = row.getId()
                except Exception:
                    rowId = None
                rowValues = row.getValues()

                valuesPayload = []
                for idx, rawVal in enumerate(rowValues):
                    if idx >= len(columns):
                        break
                    col = columns[idx]
                    renderer = col.getRenderer()
                    cell = self._convertCellForPage(renderer, rawVal, rowValues)
                    valuesPayload.append(cell)

                resultRows.append({
                    "id": rowId,
                    "values": valuesPayload,
                })

            return {
                "pageNumber": page,
                "pageSize": pageSize,
                "totalRows": int(totalRows),
                "rows": resultRows,
            }

    def exportMetadataTableService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tableName: str,
            fmt: str,
            selectionOnly: bool,
            ids: Optional[List[int]],
            mapper=None,
    ) -> Response:
        """
        Export metadata table as CSV or XLSX.

        - If ids is provided -> export those ids.
        - Else if selectionOnly -> try server-side selection.
        - Else -> export whole table.
        """
        import csv

        with _metadataLock:
            objMgr, table = self._openMetadataTable(
                projectId,
                protocolId,
                outputName,
                tableName,
                mapper=mapper,
            )
            columns = list(table.getColumns())
            colNames = [c.getName() for c in columns]

            rowIds: Optional[List[int]] = None

            if ids:
                rowIds = [int(x) for x in ids]
            elif selectionOnly:
                try:
                    selection = table.getSelection()
                    if selection and not selection.isEmpty():
                        rowIds = sorted(selection.getSelection().keys())
                    else:
                        rowIds = []
                except Exception:
                    rowIds = []
            else:
                rowIds = None

            rowsToExport = []
            if rowIds is not None:
                for rid in rowIds:
                    idx0 = max(0, int(rid) - 1)
                    chunk = objMgr.getRows(tableName, idx0, 1) or []
                    if chunk:
                        rowsToExport.append(chunk[0])
            else:
                try:
                    totalRows = objMgr.getTableRowCount(tableName) or 0
                except Exception:
                    totalRows = 0
                if totalRows > 0:
                    rowsToExport = objMgr.getRows(tableName, 0, totalRows) or []

            fmtLower = (fmt or "csv").lower()
            if fmtLower not in ("csv", "xlsx"):
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported export format. Use 'csv' or 'xlsx'.",
                )

            if fmtLower == "csv":
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(colNames)

                for row in rowsToExport:
                    rowValues = row.getValues()
                    outRow = []
                    for idx, colName in enumerate(colNames):
                        if idx >= len(rowValues):
                            outRow.append("")
                            continue
                        rawVal = rowValues[idx]
                        renderer = columns[idx].getRenderer()
                        try:
                            v = renderer.render(rawVal, rowValues)
                        except Exception:
                            v = rawVal
                        if isinstance(v, np.ndarray):
                            v = v.tolist()
                        if isinstance(v, np.generic):
                            v = v.item()
                        if not isinstance(v, (str, int, float, bool)):
                            v = str(v)
                        outRow.append(v)
                    writer.writerow(outRow)

                contentBytes = buf.getvalue().encode("utf-8")
                mediaType = "text/csv; charset=utf-8"
                ext = "csv"
            else:
                try:
                    from openpyxl import Workbook
                except ImportError:
                    raise HTTPException(
                        status_code=500,
                        detail="XLSX export requires 'openpyxl' to be installed.",
                    )

                wb = Workbook()
                ws = wb.active
                ws.append(colNames)

                for row in rowsToExport:
                    rowValues = row.getValues()
                    outRow = []
                    for idx, colName in enumerate(colNames):
                        if idx >= len(rowValues):
                            outRow.append(None)
                            continue
                        rawVal = rowValues[idx]
                        renderer = columns[idx].getRenderer()
                        try:
                            v = renderer.render(rawVal, rowValues)
                        except Exception:
                            v = rawVal
                        if isinstance(v, np.ndarray):
                            v = v.tolist()
                        if isinstance(v, np.generic):
                            v = v.item()
                        if not isinstance(v, (str, int, float, bool)):
                            v = str(v)
                        outRow.append(v)
                    ws.append(outRow)

                bio = io.BytesIO()
                wb.save(bio)
                contentBytes = bio.getvalue()
                mediaType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ext = "xlsx"

            headers = {
                "Content-Disposition": f'attachment; filename="{tableName}.{ext}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            }
            return Response(content=contentBytes, media_type=mediaType, headers=headers)


    def _renderMetadataPlaceholderImage(
            self,
            size: int,
            inline: bool,
            fmt: str,
            tableName: str,
            columnName: str,
            rowId: Optional[Union[int, str]],
            rowIndex: Optional[int],
    ) -> Response:
        """Return a small neutral placeholder image for broken metadata cells."""
        from PIL import Image as PILImage

        try:
            sizeInt = int(size)
        except Exception:
            sizeInt = 64
        sizeInt = max(8, sizeInt)

        img = PILImage.new("L", (sizeInt, sizeInt), 0)
        buf = io.BytesIO()

        fmtLower = (fmt or "png").lower()
        if fmtLower in ("jpg", "jpeg"):
            pilFormat = "JPEG"
            mediaType = "image/jpeg"
        elif fmtLower == "webp":
            pilFormat = "WEBP"
            mediaType = "image/webp"
        else:
            pilFormat = "PNG"
            mediaType = "image/png"

        img.save(buf, format=pilFormat)

        disp = "inline" if inline else "attachment"
        ident = rowId if rowId is not None else (rowIndex if rowIndex is not None else "placeholder")

        headers = {
            "Content-Disposition": f'{disp}; filename="{tableName}_{columnName}_{ident}.{fmtLower}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
            "X-Image-Placeholder": "1",
        }
        return Response(content=buf.getvalue(), media_type=mediaType, headers=headers)

    def _isVolumeLikeImageFile(self, filePath: Union[str, Path]) -> bool:
        try:
            reader = ImageReadersRegistry.open(str(filePath))
            data = reader.getImages()

            if isinstance(data, list):
                data = data[0]

            return getattr(data, "ndim", 0) == 3 and data.shape[0] > 1
        except Exception:
            return False


    def renderMetadataImageCellService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tableName: str,
            rowId: Union[int, str, None],
            columnName: str,
            size: int,
            applyTransform: bool,
            inline: bool,
            fmt: str,
            rowIndex: Optional[int] = None,
            mapper=None,
    ) -> Response:
        """
        Render one image cell from a metadata table using ImageRenderer.

        Behavior:
        - If everything is correct -> real thumbnail.
        - If the image file cannot be resolved or opened -> neutral placeholder.
        - Only true API misuse (bad column name, bad indices, etc.) returns 4xx.
        """
        from PIL import Image as PILImage
        from pathlib import Path as LocalPath
        from app.backend.viewers.postgresql_path_resolver import PostgresqlProjectPathResolver

        # Resolve metadata root path for relative image paths
        objMgr, table = self._openMetadataTable(
            projectId,
            protocolId,
            outputName,
            tableName,
            mapper=mapper,
        )
        columns = list(table.getColumns())

        pathResolver = None
        if mapper is not None and getattr(mapper, "db", None) is not None:
            pathResolver = PostgresqlProjectPathResolver(
                db=mapper.db,
                projectId=projectId,
            )

        metaDir = None
        objMgrFileName = str(getattr(objMgr, "_fileName", "") or "")

        if not objMgrFileName.startswith("postgresql://"):
            try:
                _protocol, _output, metaPath = self._resolveOutputForMetadata(protocolId, outputName)
                metaDir = LocalPath(metaPath).parent
            except Exception:
                metaDir = None

        # Resolve column index
        colIndex = table.getColumnIndexFromLabel(columnName)
        if colIndex < 0 or colIndex >= len(columns):
            raise HTTPException(
                status_code=404,
                detail=f"Column '{columnName}' not found in table '{tableName}'",
            )

        # Resolve row index (0-based)
        if rowIndex is not None:
            try:
                idx0 = int(rowIndex)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail="rowIndex must be an integer",
                )
            if idx0 < 0:
                raise HTTPException(
                    status_code=400,
                    detail="rowIndex must be >= 0",
                )
        else:
            if rowId is None:
                raise HTTPException(
                    status_code=400,
                    detail="Either rowIndex or rowId must be provided",
                )
            try:
                rowIdInt = int(rowId)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail="rowId must be an integer",
                )
            if rowIdInt <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="rowId must be >= 1",
                )
            idx0 = rowIdInt - 1

        rows = objMgr.getRows(tableName, idx0, 1) or []
        if not rows:
            logger.warning(
                "Row index %s not found in table '%s' (projectId=%s, protocolId=%s)",
                idx0,
                tableName,
                projectId,
                protocolId,
            )
            return self._renderMetadataPlaceholderImage(
                size=size,
                inline=inline,
                fmt=fmt,
                tableName=tableName,
                columnName=columnName,
                rowId=rowId,
                rowIndex=rowIndex,
            )

        row = rows[0]
        rowValues = row.getValues()
        if colIndex >= len(rowValues):
            logger.warning(
                "Column index %s out of range for rowIndex=%s in table '%s'",
                colIndex,
                idx0,
                tableName,
            )
            return self._renderMetadataPlaceholderImage(
                size=size,
                inline=inline,
                fmt=fmt,
                tableName=tableName,
                columnName=columnName,
                rowId=rowId,
                rowIndex=rowIndex,
            )

        rawValue = rowValues[colIndex]
        column = columns[colIndex]
        renderer = column.getRenderer()

        if hasattr(renderer, "setSize"):
            renderer.setSize(size)
        if hasattr(renderer, "setApplyTransformation"):
            renderer.setApplyTransformation(applyTransform)

        # Try to render using the metadata renderer
        try:
            img = renderer.render(rawValue, rowValues)
        except Exception as e:
            logger.error(
                "Cannot render image cell: table=%s, column=%s, rowIndex=%s, error=%s",
                tableName,
                columnName,
                idx0,
                e,
            )
            img = None

        # Normalize renderer outputs into a PIL image
        if img is None:
            pilImg = None
        else:
            # Sometimes renderers may return (img, extraInfo) or [img, ...]
            if isinstance(img, (list, tuple)) and len(img) > 0:
                img = img[0]

            # Numpy array -> to PIL
            if isinstance(img, np.ndarray):
                if img.ndim == 2:
                    mode = "L"
                elif img.ndim == 3 and img.shape[-1] == 3:
                    mode = "RGB"
                else:
                    mode = "L"
                pilImg = PILImage.fromarray(img, mode=mode)
            else:
                # PIL-like object
                if hasattr(img, "save"):
                    pilImg = img
                else:
                    # Path-like result: try to open image from disk
                    if isinstance(img, (str, os.PathLike)):
                        imageIndex = 0
                        imagePathText = str(img)

                        if "@" in imagePathText:
                            indexText, imagePathText = imagePathText.split("@", 1)
                            try:
                                imageIndex = int(float(indexText))
                            except Exception:
                                imageIndex = 0

                        imgPath = LocalPath(imagePathText)

                        # Build candidates for relative paths:
                        resolvedPath = None

                        # First, resolve PostgreSQL project-relative paths:
                        #   Runs/000002_ProtImportMicrographs/extra/016.mrc
                        # should become:
                        #   <projectPath>/Runs/000002_ProtImportMicrographs/extra/016.mrc
                        if pathResolver is not None:
                            resolvedText = pathResolver.resolveExistingPath(imagePathText)
                            if resolvedText:
                                resolvedPath = LocalPath(resolvedText)

                        # Keep the old runtime/metaDir fallback for legacy/non-PG cases.
                        if resolvedPath is None:
                            candidates = []

                            if imgPath.is_absolute():
                                candidates.append(imgPath)
                            else:
                                if metaDir is not None:
                                    candidates.append(metaDir / imgPath)

                                projPath = None
                                protPath = None
                                try:
                                    if self.currentProject is not None:
                                        projPath = LocalPath(self.currentProject.getPath())

                                        prot = self._getScipionProtocolForRuntime(
                                            mapper=mapper,
                                            projectId=projectId,
                                            protocolId=protocolId,
                                        )
                                        protPath = LocalPath(prot.getPath())
                                except Exception:
                                    protPath = None

                                if protPath is not None:
                                    candidates.append(protPath / imgPath)
                                if projPath is not None:
                                    candidates.append(projPath / imgPath)

                                candidates.append(imgPath)

                            for cand in candidates:
                                try:
                                    if cand.exists():
                                        resolvedPath = cand
                                        break
                                except Exception:
                                    continue

                        if resolvedPath is None:
                            logger.warning(
                                "Image file not found for metadata cell: raw='%s', table=%s, column=%s, rowIndex=%s",
                                str(img),
                                tableName,
                                columnName,
                                idx0,
                            )
                            pilImg = None
                        else:
                            try:
                                pilImg = PILImage.open(str(resolvedPath))
                            except Exception as e:
                                logger.warning(
                                    "Cannot open image file '%s' for metadata cell with PIL: %s",
                                    str(resolvedPath),
                                    e,
                                )
                                previewIndex = imageIndex
                                # PIL cannot read cryo-EM formats such as .mrc/.mrcs.
                                # Fall back to Scipion/pwem preview rendering.
                                if previewIndex in (None, 0) and self._isVolumeLikeImageFile(resolvedPath):
                                    previewIndex = None
                                try:
                                    preview = OutputsPreview(
                                        currentProject=self.currentProject,
                                        protocol=None,
                                        output=None,
                                    )

                                    return preview.renderImageFromFilePath(
                                        filePath=str(resolvedPath),
                                        size=size,
                                        fmt=fmt,
                                        index=previewIndex,
                                        applyTransform=False,
                                        inline=inline,
                                        rot=None,
                                        shifts=None,
                                    )
                                except Exception as previewError:
                                    logger.error(
                                        "Cannot render metadata image file '%s' with Scipion preview: %s",
                                        str(resolvedPath),
                                        previewError,
                                    )
                                    pilImg = None
                    else:
                        # Unsupported type: treat as no image for this cell
                        logger.warning(
                            "Renderer returned unsupported type %r for metadata image cell "
                            "(table=%s, column=%s, rowIndex=%s)",
                            type(img),
                            tableName,
                            columnName,
                            idx0,
                        )
                        pilImg = None

        # If we still have no image, return placeholder instead of 404
        if pilImg is None:
            return self._renderMetadataPlaceholderImage(
                size=size,
                inline=inline,
                fmt=fmt,
                tableName=tableName,
                columnName=columnName,
                rowId=rowId,
                rowIndex=rowIndex,
            )

        # Resize and normalize contrast a bit
        try:
            pilImg.thumbnail((size, size))
            arr = np.array(pilImg)

            if arr.ndim == 3 and arr.shape[-1] == 3:
                arrGray = arr.mean(axis=-1)
            else:
                arrGray = arr if arr.ndim == 2 else arr.mean(axis=-1)

            im255 = self._normalize2dSlice(arrGray, mode="zscore")
            pilImg = PILImage.fromarray(im255, mode="L")
        except Exception:
            # If any normalization fails, keep whatever pilImg we have
            pass

        buf = io.BytesIO()
        fmtLower = (fmt or "png").lower()
        if fmtLower in ("jpg", "jpeg"):
            pilFormat = "JPEG"
            mediaType = "image/jpeg"
        elif fmtLower == "webp":
            pilFormat = "WEBP"
            mediaType = "image/webp"
        else:
            pilFormat = "PNG"
            mediaType = "image/png"

        pilImg.save(buf, format=pilFormat)

        disp = "inline" if inline else "attachment"
        filenameId = rowId if rowId is not None else (rowIndex if rowIndex is not None else (idx0 + 1))
        headers = {
            "Content-Disposition": f'{disp}; filename="{tableName}_{columnName}_{filenameId}.{fmtLower}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        }

        return Response(content=buf.getvalue(), media_type=mediaType, headers=headers)

    def getMetadataTableWindowService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            tableName: str,
            offset: int,
            limit: int,
            selectionOnly: bool,
            sortBy: str,
            asc: bool,
            mapper=None,
    ):
        """
        Return a window of rows for a metadata table using offset + limit.

        IMPORTANT:
        - `offset` / `limit` are 0-based indices in the current table order.
        - Each returned row uses:
            - `id` / `index`: 0-based global index (stable for the viewer)
            - `rowId`: logical DAO id (which may be sparse)
        - `totalRows` is the total number of rows in the *current view*:
            - full table if selectionOnly == False
            - number of selected rows if selectionOnly == True
        """
        with _metadataLock:
            objMgr, table = self._openMetadataTable(
                projectId,
                protocolId,
                outputName,
                tableName,
                mapper=mapper,
            )
            columns = list(table.getColumns())
            table.setSortingColumn(sortBy)
            table.setSortingAsc(asc)

            # Sanitize window parameters
            offset = max(0, int(offset or 0))
            limit = max(1, int(limit or 1))

            # Get physical row count once
            try:
                totalPhysicalRows = objMgr.getTableRowCount(tableName) or 0
            except Exception:
                totalPhysicalRows = 0

            rows = []
            totalRows = totalPhysicalRows

            if totalPhysicalRows <= 0:
                rows = []
                totalRows = 0
            else:
                if selectionOnly:
                    # Window over server-side selection
                    try:
                        selection = table.getSelection()
                        if selection and not selection.isEmpty():
                            allIds = sorted(selection.getSelection().keys())
                            totalRows = len(allIds)

                            if offset < totalRows:
                                end = min(offset + limit, totalRows)
                                sliceIds = allIds[offset:end]
                                for rid in sliceIds:
                                    idx0 = max(0, int(rid) - 1)
                                    chunk = objMgr.getRows(tableName, idx0, 1) or []
                                    if chunk:
                                        rows.append(chunk[0])
                        else:
                            # No selection → empty view
                            rows = []
                            totalRows = 0
                    except Exception:
                        # On any selection error, expose empty view instead of inconsistent totals
                        rows = []
                        totalRows = 0
                else:
                    # Window over full table
                    totalRows = totalPhysicalRows
                    if offset < totalRows:
                        rows = objMgr.getRows(tableName, offset, limit) or []
                    else:
                        rows = []

            # Convert rows to JSON-friendly payload
            resultRows = []
            for localIndex, row in enumerate(rows):
                try:
                    logicalId = row.getId()
                except Exception:
                    logicalId = None

                rowValues = row.getValues()

                valuesPayload = []
                for idx, rawVal in enumerate(rowValues):
                    if idx >= len(columns):
                        break
                    col = columns[idx]
                    renderer = col.getRenderer()
                    cell = self._convertCellForPage(renderer, rawVal, rowValues)
                    valuesPayload.append(cell)

                globalIndex = offset + localIndex

                resultRows.append({
                    "id": globalIndex,
                    "index": globalIndex,
                    "rowId": logicalId,
                    "values": valuesPayload,
                })

            return {
                "offset": offset,
                "limit": limit,
                "totalRows": int(totalRows),
                "rows": resultRows,
            }

    # -----------------------------
    # External viewers methods
    # -----------------------------

    def _resolveExternalViewerCoords3dTomogram(
            self,
            outputObj: Any,
            objectId: Union[str, int],
    ) -> Any:
        targetId = str(objectId).strip()
        if not targetId:
            return None

        cached = getattr(self, "tomoList", {}).get(targetId)
        if cached is not None:
            return cached

        getTomogram = getattr(outputObj, "_getTomogram", None)
        if callable(getTomogram):
            try:
                tomo = getTomogram(targetId)
                if tomo is not None:
                    return tomo
            except Exception:
                pass

        iterTomograms = getattr(outputObj, "iterTomograms", None)
        if callable(iterTomograms):
            try:
                for tomo in iterTomograms():
                    tomoIds = self._getExternalViewerObjectIds(tomo)

                    getTsId = getattr(tomo, "getTsId", None)
                    if callable(getTsId):
                        try:
                            tomoIds.add(str(getTsId()))
                        except Exception:
                            pass

                    getObjLabel = getattr(tomo, "getObjLabel", None)
                    if callable(getObjLabel):
                        try:
                            tomoIds.add(str(getObjLabel()))
                        except Exception:
                            pass

                    if targetId in tomoIds:
                        if not hasattr(self, "tomoList") or self.tomoList is None:
                            self.tomoList = {}
                        self.tomoList[targetId] = tomo
                        return tomo
            except Exception:
                pass

        return None

    def _resolveExternalViewerCTFTomoSeries(
            self,
            outputObj: Any,
            objectId: Union[str, int],
    ) -> Any:
        targetId = str(objectId).strip()
        if not targetId:
            return None

        try:
            for item in outputObj:
                itemIds = self._getExternalViewerObjectIds(item)

                for methodName in (
                        "getTsId",
                        "getTomoId",
                        "getCTFTomoSeriesId",
                        "getObjId",
                        "getObjLabel",
                        "getName",
                ):
                    method = getattr(item, methodName, None)
                    if callable(method):
                        try:
                            value = method()
                            if value is not None:
                                itemIds.add(str(value))
                        except Exception:
                            pass

                if targetId in itemIds:
                    return item
        except Exception:
            pass

        return None

    def _isSingleExternalViewerObject(self, outputObj: Any) -> bool:
        if outputObj is None:
            return False

        getItem = getattr(outputObj, "getItem", None)
        if callable(getItem):
            return False

        iterItems = getattr(outputObj, "__iter__", None)
        if callable(iterItems):
            return False

        getFileName = getattr(outputObj, "getFileName", None)
        if callable(getFileName):
            return True

        return False

    def _findExternalViewerClasses(self, targetObj: Any) -> List[Any]:
        try:
            viewers = Config.getDomain().findViewers(targetObj, DESKTOP_TKINTER) or []
            return list(viewers)
        except BaseException as e:
            logger.exception(
                "Failed to find external viewers for object type %s: %s",
                type(targetObj).__name__,
                e,
            )
            return []

    def _normalizeExternalViewerId(self, viewerClass: Any) -> str:
        className = getattr(viewerClass, "__name__", "") or str(viewerClass)
        viewerId = className.strip()

        if viewerId.lower().endswith("viewer"):
            viewerId = viewerId[:-6]

        viewerId = re.sub(r"[^A-Za-z0-9]+", "-", viewerId).strip("-").lower()
        return viewerId or "viewer"

    def _buildExternalViewerDescriptor(self, viewerClass: Any) -> Dict[str, Any]:
        className = getattr(viewerClass, "__name__", "") or str(viewerClass)
        moduleName = getattr(viewerClass, "__module__", None)

        label = (
            getattr(viewerClass, "_label", None)
            or getattr(viewerClass, "label", None)
            or className
        )

        label = str(label).replace("Viewer", "").strip() or className

        return {
            "id": self._normalizeExternalViewerId(viewerClass),
            "label": label,
            "className": className,
            "moduleName": moduleName,
            "available": True,
            "reason": None,
        }

    def _unwrapScipionObject(self, obj: Any) -> Any:
        if obj is None:
            return None

        getter = getattr(obj, "get", None)
        if callable(getter):
            try:
                value = getter()
                if value is not None:
                    return value
            except Exception:
                pass

        return obj

    def _getProtocolOutputObject(
            self,
            protocolId: int,
            outputName: str,
            mapper=None,
            projectId: Optional[int] = None,
    ) -> Tuple[Any, Any]:
        protocol = self._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        outputObj = None

        if hasattr(protocol, outputName):
            outputObj = getattr(protocol, outputName)

        if outputObj is None:
            iterator = getattr(protocol, "iterOutputAttributes", None)
            if callable(iterator):
                try:
                    for attrName, attrObj in iterator():
                        if str(attrName) == str(outputName):
                            outputObj = attrObj
                            break
                except Exception:
                    pass

        outputObj = self._unwrapScipionObject(outputObj)

        if outputObj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Output not found: {outputName}",
            )

        return protocol, outputObj

    def _getExternalViewerObjectIds(self, obj: Any) -> TypingSet[str]:
        values: TypingSet[str] = set()

        def addValue(value: Any):
            if value is None:
                return

            getter = getattr(value, "get", None)
            if callable(getter):
                try:
                    value = getter()
                except Exception:
                    pass

            if value is None:
                return

            text = str(value).strip()
            if text:
                values.add(text)

        for methodName in (
            "getTsId",
            "getObjId",
            "getId",
            "getName",
            "getFileName",
        ):
            method = getattr(obj, methodName, None)
            if callable(method):
                try:
                    addValue(method())
                except Exception:
                    pass

        for attrName in (
            "tsId",
            "id",
            "objId",
            "_objId",
            "name",
            "label",
            "filename",
            "fileName",
        ):
            if hasattr(obj, attrName):
                try:
                    addValue(getattr(obj, attrName))
                except Exception:
                    pass

        return values

    def _resolveExternalViewerTargetObject(
            self,
            outputObj: Any,
            objectId: Optional[Union[str, int]] = None,
            objectKind: Optional[str] = None,
    ) -> Any:
        if objectId is None or str(objectId).strip() == "":
            return outputObj

        targetId = str(objectId).strip()
        objectKindText = str(objectKind or "").strip().lower()

        if objectKindText in {"volume", "tomogram"} and self._isSingleExternalViewerObject(outputObj):
            if targetId in {"0", "1"}:
                return outputObj

        if objectKindText in {"coords3dtomogram", "coords3d-tomogram", "coordinates3dtomogram"}:
            resolved = self._resolveExternalViewerCoords3dTomogram(
                outputObj=outputObj,
                objectId=objectId,
            )
            if resolved is not None:
                return resolved

        if objectKindText in {"ctftomoseries", "ctf-tomo-series", "ctfseries"}:
            resolved = self._resolveExternalViewerCTFTomoSeries(
                outputObj=outputObj,
                objectId=objectId,
            )
            if resolved is not None:
                return resolved

        if objectKindText in {"volume", "tomogram"}:
            resolved = self._resolveExternalViewerSetItemByPublicId(
                outputObj=outputObj,
                objectId=objectId,
            )
            if resolved is not None:
                return resolved

        try:
            for item in outputObj:
                itemIds = self._getExternalViewerObjectIds(item)
                if targetId in itemIds:
                    return item
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Object '{targetId}' not found inside output. "
                f"objectKind={objectKind or 'unknown'}"
            ),
        )

    def _resolveExternalViewerSetItemByPublicId(
            self,
            outputObj: Any,
            objectId: Union[str, int],
    ) -> Any:
        try:
            publicId = int(objectId)
        except Exception:
            return None

        getItem = getattr(outputObj, "getItem", None)
        if callable(getItem):
            for key, value in (
                    ("_objId", publicId + 1),
                    ("_objId", publicId),
                    ("id", publicId),
                    ("index", publicId),
            ):
                try:
                    item = getItem(key, value)
                    if item is not None:
                        return item
                except Exception:
                    pass

        try:
            for index, item in enumerate(outputObj):
                if index == publicId:
                    return item

                itemIds = self._getExternalViewerObjectIds(item)
                if str(publicId) in itemIds or str(publicId + 1) in itemIds:
                    return item
        except Exception:
            pass

        return None

    def listExternalViewers(
            self,
            protocolId: int,
            outputName: str,
            objectId: Optional[Union[str, int]] = None,
            objectKind: Optional[str] = None,
            mapper=None,
            projectId: Optional[int] = None,
    ) -> List[Dict[str, Any]]:

        protocol, outputObj = self._getProtocolOutputObject(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )

        targetObj = self._resolveExternalViewerTargetObject(
            outputObj=outputObj,
            objectId=objectId,
            objectKind=objectKind,
        )

        viewerClasses = self._findExternalViewerClasses(targetObj)

        descriptors = []
        seenIds: TypingSet[str] = set()
        excludedViewer = ['TomoDataViewer', 'MDViewer', 'DataViewer', 'CtfEstimationTomoViewer']
        for viewerClass in viewerClasses:
            descriptor = self._buildExternalViewerDescriptor(viewerClass)
            viewerId = descriptor["id"]
            if descriptor['className'] in excludedViewer:
                continue

            if viewerId in seenIds:
                className = descriptor.get("className") or viewerId
                viewerId = f"{viewerId}-{len(seenIds) + 1}"
                descriptor["id"] = viewerId
                descriptor["className"] = className

            seenIds.add(viewerId)
            descriptors.append(descriptor)

        return descriptors

    def _matchExternalViewerClass(
        self,
        viewerClasses: List[Any],
        viewerId: str,
    ) -> Tuple[Any, Dict[str, Any]]:
        requested = str(viewerId or "").strip().lower()

        for viewerClass in viewerClasses:
            descriptor = self._buildExternalViewerDescriptor(viewerClass)

            tokens = {
                str(descriptor.get("id") or "").lower(),
                str(descriptor.get("label") or "").lower(),
                str(descriptor.get("className") or "").lower(),
                str(descriptor.get("moduleName") or "").lower(),
            }

            className = str(descriptor.get("className") or "")
            if className.lower().endswith("viewer"):
                tokens.add(className[:-6].lower())

            if requested in tokens:
                return viewerClass, descriptor

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External viewer not found or not compatible: {viewerId}",
        )

    def _createExternalViewerInstance(self, viewerClass: Any, protocol: Any) -> Any:
        attempts = [
            {"project": self.currentProject, "protocol": protocol},
            {"protocol": protocol},
            {"project": self.currentProject},
            {},
        ]

        lastError = None

        for kwargs in attempts:
            try:
                viewer = viewerClass(**kwargs)
                return viewer
            except TypeError as e:
                lastError = e
            except Exception as e:
                lastError = e
                break

        raise RuntimeError(f"Could not create viewer instance: {lastError}")

    def _showExternalView(self, view: Any):
        if view is None:
            return

        for methodName in ("show", "execute", "launch", "run"):
            method = getattr(view, methodName, None)
            if callable(method):
                method()
                return

        if callable(view):
            view()

    def _runExternalViewer(self, viewerClass: Any, protocol: Any, targetObj: Any):
        viewer = self._createExternalViewerInstance(viewerClass, protocol)

        for methodName in ("setProject",):
            method = getattr(viewer, methodName, None)
            if callable(method):
                try:
                    method(self.currentProject)
                except Exception:
                    pass

        for methodName in ("setProtocol",):
            method = getattr(viewer, methodName, None)
            if callable(method):
                try:
                    method(protocol)
                except Exception:
                    pass

        visualize = getattr(viewer, "visualize", None)
        if not callable(visualize):
            visualize = getattr(viewer, "_visualize", None)

        if not callable(visualize):
            raise RuntimeError("Viewer does not expose a visualize method")

        views = visualize(targetObj)

        if views is None:
            return

        if not isinstance(views, (list, tuple)):
            views = [views]

        for view in views:
            self._showExternalView(view)

    def launchExternalViewer(
            self,
            protocolId: int,
            outputName: str,
            viewerId: str,
            objectId: Optional[Union[str, int]] = None,
            objectKind: Optional[str] = None,
            params: Optional[Dict[str, Any]] = None,
            mapper=None,
            projectId: Optional[int] = None,
    ) -> Dict[str, Any]:

        protocol, outputObj = self._getProtocolOutputObject(
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            projectId=projectId,
        )

        targetObj = self._resolveExternalViewerTargetObject(
            outputObj=outputObj,
            objectId=objectId,
            objectKind=objectKind,
        )

        viewerClasses = self._findExternalViewerClasses(targetObj)

        viewerClass, descriptor = self._matchExternalViewerClass(
            viewerClasses=viewerClasses,
            viewerId=viewerId,
        )

        thread = threading.Thread(
            target=self._safeRunExternalViewer,
            args=(viewerClass, protocol, targetObj, descriptor),
            daemon=True,
        )
        thread.start()

        return {
            "success": True,
            "viewerId": descriptor["id"],
            "message": f"{descriptor['label']} launch requested.",
            "pid": None,
            "data": {
                "objectId": objectId,
                "objectKind": objectKind,
            },
        }

    def _safeRunExternalViewer(
        self,
        viewerClass: Any,
        protocol: Any,
        targetObj: Any,
        descriptor: Dict[str, Any],
    ):
        try:
            self._runExternalViewer(
                viewerClass=viewerClass,
                protocol=protocol,
                targetObj=targetObj,
            )
        except Exception as e:
            logger.exception(
                "External viewer failed. viewerId=%s className=%s error=%s",
                descriptor.get("id"),
                descriptor.get("className"),
                e,
            )

    # -----------------------------
    # Tags Service Methods
    # -----------------------------
    def listProjectTags(
        self,
        mapper,
        projectId: int,
        currentUser: dict,
    ) -> List[Dict[str, Any]]:
        # listProjectTags
        listFn = getattr(mapper, "listProjectTags", None)
        if callable(listFn):
            return listFn(projectId=projectId)

        # mapperMethodFallback: keep backward compatibility with older mapper name
        legacyListFn = getattr(mapper, "listProtocolTags", None)
        if callable(legacyListFn):
            return legacyListFn(projectId=projectId)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mapper does not implement listProjectTags",
        )

    def createProjectTag(
        self,
        mapper,
        projectId: int,
        currentUser: dict,
        payload,
    ) -> Dict[str, Any]:
        # createProjectTag
        title = (payload.title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")

        tagId = (payload.id or "").strip() if getattr(payload, "id", None) else ""
        if not tagId:
            tagId = str(uuid4())

        tag = {
            "id": tagId,
            "title": title,
            "description": getattr(payload, "description", None),
            "color": getattr(payload, "color", None),
        }

        try:
            return mapper.upsertProtocolTag(projectId=projectId, tag=tag)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create tag: {e}",
            )

    def updateProjectTag(
        self,
        mapper,
        projectId: int,
        tagId: str,
        currentUser: dict,
        payload,
    ) -> Dict[str, Any]:
        # updateProjectTag
        tagId = (tagId or "").strip()
        if not tagId:
            raise HTTPException(status_code=400, detail="tagId is required")

        existing = None
        for t in self.listProjectTags(mapper=mapper, projectId=projectId, currentUser=currentUser):
            if str(t.get("id", "")).strip() == tagId:
                existing = t
                break

        if not existing:
            raise HTTPException(status_code=404, detail="Tag not found")

        nextTitle = getattr(payload, "title", None)
        if nextTitle is None:
            nextTitle = existing.get("title")
        nextTitle = (nextTitle or "").strip()
        if not nextTitle:
            raise HTTPException(status_code=400, detail="title cannot be empty")

        nextDescription = getattr(payload, "description", None)
        if nextDescription is None:
            nextDescription = existing.get("description")

        nextColor = getattr(payload, "color", None)
        if nextColor is None:
            nextColor = existing.get("color")

        tag = {
            "id": tagId,
            "title": nextTitle,
            "description": nextDescription,
            "color": nextColor,
        }

        try:
            return mapper.upsertProtocolTag(projectId=projectId, tag=tag)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update tag: {e}",
            )

    def deleteProjectTag(
        self,
        mapper,
        projectId: int,
        tagId: str,
        currentUser: dict,
    ) -> bool:
        # deleteProjectTag
        tagId = (tagId or "").strip()
        if not tagId:
            raise HTTPException(status_code=400, detail="tagId is required")

        # cascadeBehavior: protocol_tag_assignments(tagId) has ON DELETE CASCADE
        try:
            return bool(mapper.deleteProtocolTag(projectId=projectId, tagId=tagId))
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete tag: {e}",
            )

    def listProtocolTags(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            currentUser: dict,
    ) -> Dict[str, Any]:
        # listProtocolTags
        protocolDbId = self._resolvePostgresqlProtocolDbId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if protocolDbId is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol not found in PostgreSQL: {protocolId}",
            )

        try:
            tagIds = mapper.getProtocolTagIds(
                projectId=projectId,
                protocolDbId=protocolDbId,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list protocol tags: {e}",
            )

        return {
            "protocolId": str(protocolId),
            "protocolDbId": protocolDbId,
            "tagIds": tagIds,
        }

    def setProtocolTags(
            self,
            mapper,
            projectId: int,
            protocolId: int,
            tagIds: List[str],
            currentUser: dict,
    ) -> Dict[str, Any]:
        # setProtocolTags
        protocolDbId = self._resolvePostgresqlProtocolDbId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if protocolDbId is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol not found in PostgreSQL: {protocolId}",
            )

        try:
            setByDbId = getattr(mapper, "setProtocolTagIdsByProtocolDbId", None)
            if callable(setByDbId):
                return setByDbId(
                    projectId=projectId,
                    protocolDbId=protocolDbId,
                    tagIds=tagIds or [],
                )

            return mapper.setProtocolTagIds(
                projectId=projectId,
                protocolId=int(protocolId),
                tagIds=tagIds or [],
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to set protocol tags: {e}",
            )

    def getContextMenuVisibilityPolicy(self) -> dict:
        return {
               "open":  True,
               "browse":  True,
               "rename":  True,
               "duplicate":  True,
               "copyWorkflow": True,
               "pasteWorkflow": True,
               "delete":  True,
               "restart":  True,
               "continue":  True,
               "reset":  True,
               "stop":  True,
               "selectFrom":  True,
               "selectTo":  True,
               "manageTags":  True,
               "export":  True,
               "upload":  True,
               "nextSteps":  True,
        }

    # -------------------------------
    # Wizards methods
    # -------------------------------
    def executeProtocolWizard(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
            payload,
    ) -> Dict[str, Any]:
        wizardService = ProtocolWizardService(
            currentProject=self.currentProject,
            projectService=self,
        )
        return wizardService.executeProtocolWizard(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            payload=payload,
        )

