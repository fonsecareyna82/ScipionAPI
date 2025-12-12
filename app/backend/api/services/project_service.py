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
import io
import logging
import threading
from functools import lru_cache

import numpy as np

from metadataviewer.dao.numpy_dao import NumpyDao
from metadataviewer.model import ObjectManager
from tomo.constants import BOTTOM_LEFT_CORNER
from tomo.objects import SetOfTiltSeries, TiltSeries, SetOfCTFTomoSeries, CTFTomoSeries, CTFTomo

from app.backend.utils.constants import SQLITE_OBJECT_TABLE, maxThumbSize
from app.backend.utils.outputs_preview import OutputsPreview
from app.backend.utils.volume_utils import readVolumeArray3d
from pwem.emlib.image.image_readers import ImageReadersRegistry, ImageStack
from pwem.objects import SetOfVolumes
from pwem.viewers import VISIBLE, ORDER, RENDER
from pwem.viewers.mdviewer.readers import ScipionImageReader
from pwem.viewers.mdviewer.sqlite_dao import ScipionSetsDAO
from pwem.viewers.mdviewer.star_dao import StarFile
from pyworkflow.object import PointerList, Pointer

logger = logging.getLogger(__name__)

import os
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Any, Union, Tuple, Dict, Set
from fastapi import HTTPException, status, Response
from pathlib import Path as FsPath
import mimetypes
import pyworkflow
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from pyworkflow import Config
from pyworkflow.project import Manager, Project as ScipionProject
from pyworkflow.protocol.params import (IntParam, FloatParam, BooleanParam, StringParam, EnumParam, PointerParam,
                                        MultiPointerParam, RelationParam)
import pyworkflow.utils as pwutils
from pyworkflow.utils import HYPER_BOLD, HYPER_ITALIC, HYPER_LINK1, HYPER_LINK2, parseHyperText
from app.backend.api.schemas.project_schema import ProjectCreate, ProjectUpdate
from app.backend.utils.file_handlers import FileHandlers

from app.utils.scipion_helper import serializeToJson
from contextvars import ContextVar


# Per-request context for current project and tomoList
_currentProjectVar: ContextVar[Optional[ScipionProject]] = ContextVar(
    "_currentProjectVar", default=None
)
_tomoListVar: ContextVar[Optional[Dict[Any, Any]]] = ContextVar(
    "_tomoListVar", default=None
)

# Global lock for metadata / DAO operations (not thread-safe)
_metadataLock = threading.Lock()


class ProjectService:
    def __init__(self):
        self.manager = Manager()
        # Keep objectManager attribute for backward compatibility,
        # but new HTTP endpoints use a fresh ObjectManager per request.
        self.objectManager = None

    # ------------------------------------------------------------------
    # Per-request project / tomogram context
    # ------------------------------------------------------------------
    @property
    def currentProject(self) -> Optional[ScipionProject]:
        """Return the current ScipionProject bound to this request context."""
        return _currentProjectVar.get()

    @currentProject.setter
    def currentProject(self, value: Optional[ScipionProject]):
        _currentProjectVar.set(value)

    @property
    def tomoList(self) -> Dict[Any, Any]:
        """Return the per-request tomogram cache dictionary."""
        value = _tomoListVar.get()
        if value is None:
            value = {}
            _tomoListVar.set(value)
        return value

    @tomoList.setter
    def tomoList(self, value: Dict[Any, Any]):
        _tomoListVar.set(value)

    def clearCurrentProject(self):
        """Clear per-request project and tomogram cache."""
        _currentProjectVar.set(None)
        _tomoListVar.set({})

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

    def createProject(self, mapper: PostgresqlFlatMapper, projectData: ProjectCreate, currentUser) -> dict:
        # Check if a project with the same name already exists for this user
        existingProjects = mapper.listProjects(ownerId=currentUser['id'])
        if any(p['name'] == projectData.name for p in existingProjects):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A project with this name already exists for the current user"
            )

        # Check if the project already exists in the file system (Scipion)
        scipionPath = self.manager.getProjectPath(projectData.name)
        if os.path.exists(scipionPath):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A project with this name already exists in the file system"
            )

        # Create the project in Scipion
        proj = self.manager.createProject(projectData.name)
        proj.setComment(projectData.description or "")

        # Insert project metadata into PostgreSQL via mapper
        dbProjectId = mapper.insertProject(
            ownerId=currentUser['id'],
            name=scipionPath,
            description=projectData.description,
            status=projectData.status
        )

        # Return the response payload
        return {
            "id": dbProjectId,
            "name": projectData.name,
            "description": projectData.description,
            "createdAt": datetime.utcnow(),
            "status": projectData.status,
            "protocolsCount": 0,
            "diskUsage": f"{0.0} GB"
        }

    def listProjects(self, mapper: PostgresqlFlatMapper, currentUser) -> List[dict]:
        """
        List all projects visible for the current user:
        - owned projects
        - shared projects (from project_shares)
        """
        dbProjects = mapper.listProjects(ownerId=currentUser["id"])
        result = []

        for dbProj in dbProjects:
            # projects.name currently stores the absolute Scipion project path
            projectPath = dbProj.get("name")

            if not projectPath:
                # Skip inconsistent rows
                continue

            # If name is not absolute, normalize it using Scipion manager
            if not os.path.isabs(projectPath):
                projectPath = self.manager.getProjectPath(projectPath)

            # Compute size and number of protocols for this project
            try:
                sizeGB = self.getProjectSize(projectPath) / (1024 ** 3)
            except Exception:
                sizeGB = 0.0

            runsPath = os.path.join(projectPath, "Runs")
            protCount = self.countProtocols(runsPath)

            # Ownership and sharing flags coming from the mapper
            isOwner = dbProj.get("isOwner", dbProj.get("ownerId") == currentUser["id"])
            isShared = dbProj.get("isShared", False)
            permission = dbProj.get(
                "permission",
                "owner" if isOwner else "full"
            )
            projectOwnerId = dbProj.get("ownerId")

            result.append({
                "id": dbProj["id"],
                "name": os.path.basename(projectPath),
                "description": dbProj.get("description", ""),
                "createdAt": dbProj.get("createdAt"),
                "status": dbProj.get("status", "active"),
                "protocolsCount": str(protCount),
                "diskUsage": f"{sizeGB:.2f} GB",
                "isOwner": bool(isOwner),
                "isShared": bool(isShared),
                "permission": permission,
                "projectOwnerId": projectOwnerId,
            })

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

    def getProjectById(self, mapper: PostgresqlFlatMapper, projectId: int, currentUser, refresh=True, checkPid=True) -> Optional[dict]:
        # Retrieve project from PostgreSQL using the mapper
        userId = currentUser["id"]
        dbProj = mapper.getProject(projectId=projectId, userId=userId)
        if not dbProj:
            return None
        projectPath = dbProj['name']
        if not os.path.exists(projectPath):
            return None

        return self.loadProject(dbProj, mapper, refresh=refresh, checkPid=checkPid)

    def updateProject(self, mapper: PostgresqlFlatMapper, projectId: int, currentUser: dict, projectData: ProjectUpdate):
        project = self.getProjectById(mapper, projectId, currentUser)

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        self.manager.renameProject(project['name'], projectData.name)
        mapper.updateProject(projectId, currentUser['id'],
                             self.manager.getProjectPath(projectData.name),
                             projectData.description)

        return project

    def deleteProject(self, mapper: PostgresqlFlatMapper, currentUser, projectId) -> Optional[dict]:
        project = self.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
        deleted = mapper.deleteProject(projectId, currentUser["id"])
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        path = self.manager.getProjectPath(project['name'])
        if not os.path.exists(path):
            return None
        cwd = self.manager.PROJECTS
        self.manager.deleteProject(path)
        os.chdir(cwd)

        return {"message": "Project deleted successfully"}

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

    def buildProtocolsGraph(self, runs) -> dict:
        """Assemble dependency graph of protocols and their status."""
        nodesDict = runs._nodesDict
        graphData = {}
        for nodeId, nodeObj in nodesDict.items():
            childrenIds = [child.getName() for child in nodeObj._children]
            parentIds = [parent.getName() for parent in nodeObj._parents]
            status = nodeObj.run.getStatus() if nodeObj.run else ''
            inputs = []
            outputs = []
            cpuTime = ''
            elapsedTime = ''
            isinteractive = False
            numberOfSteps = 0
            stepsDone = 0
            if nodeId != 'PROJECT':
                protocol = self.currentProject.getProtocol(int(nodeId))
                cpuTime = str(protocol.cpuTime)
                elapsedTime = str(protocol.getElapsedTime().total_seconds()).split('.')[0]
                isinteractive = protocol.isInteractive()
                numberOfSteps = protocol.numberOfSteps
                stepsDone = protocol.stepsDone
                self.currentProject._fixProtParamsConfiguration(protocol)

                # Iterate over inputs
                for key, attr in protocol.iterInputAttributes():
                    input = {}
                    input.setdefault(key, {})
                    try:
                        input[key]['_class'] = attr.get().getClassName() if attr and attr.get() else ""
                        input[key]['info'] = str(attr.get())
                    except Exception:
                        input[key]['_class'] = ""
                        input[key]['info'] = ""

                    input[key]['_objValue'] = "%s.%s" % (attr.getObjValue(), attr.getExtended())
                    input[key]['_parentId'] = attr.getObjValue().getObjId()
                    inputs.append(input)

                # Iterate over outputs
                for key, attr in protocol.iterOutputAttributes():
                    output = {}
                    output.setdefault(key, {})
                    output[key]['_class'] = attr.__class__.__name__
                    try:
                        output[key]['info'] = attr.__str__()
                    except Exception:
                        output[key]['info'] = ""
                    output[key]['_objValue'] = "%s.%s" % (str(nodeObj.run), key)
                    output[key]['_parentId'] = protocol.getObjId()
                    outputs.append(output)

            graphData[nodeId] = {
                "id": nodeId,
                "children": childrenIds,
                "parents": parentIds,
                "label": nodeObj.getLabel(),
                "status": status,
                "parameter": [],
                "inputs": inputs,
                "outputs": outputs,
                "cpuTime": cpuTime,
                "elapsedTime": elapsedTime,
                "isInteractive": isinteractive,
                "numberOfSteps": numberOfSteps,
                "stepsDone": stepsDone
            }
        return graphData

    def loadProject(self, dbProj: dict, mapper: PostgresqlFlatMapper = None, refresh=True, checkPid=True) -> dict:
        projPath = dbProj['name']
        self.currentProject = ScipionProject(pyworkflow.Config.getDomain(), projPath)
        self.currentProject.load(dbPath=self.currentProject.getDbPath())
        runs = self.currentProject.getRunsGraph(refresh=refresh, checkPids=checkPid)
        graphData = self.buildProtocolsGraph(runs)
        # self.saveProtocolDependencies(mapper, graphData)

        return {
            "id": dbProj['id'],
            "name": dbProj['name'],
            "shortName": os.path.basename(dbProj['name']),
            "createdAt": str(dbProj['createdAt']),
            "status": str(dbProj['status']),
            "path": projPath,
            "protocols": graphData
        }

    def saveProtocolDependencies(self, mapper: PostgresqlFlatMapper, graphData: dict):
        for nodeId, nodeInfo in graphData.items():
            parentIds = [int(pid) for pid in nodeInfo['parents'] if pid != 'PROJECT']
            childIds = [int(cid) for cid in nodeInfo['children']]
            mapper.updateProtocolDependencies(
                protocolId=nodeId,
                parentIds=parentIds,
                childIds=childIds
            )

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

    def _buildProtocolContext(self, projectId, protocol) -> dict:
        """
        Build the common context dictionary for a protocol,
        including inputs, outputs, definition, status, color, logos, etc.
        """
        from pyworkflow.protocol import Line, Group

        headerParams = ['runName', '_objComment', '_useQueue', '_prerequisites', 'gpuList', 'numberOfThreads']
        # Basic metadata
        package = protocol.getClassPackage()
        hasExpert = protocol.hasExpert()
        if hasExpert:
            headerParams.append('expertLevel')
        headerParams.append('runMode')
        logoPath = ''
        path = getattr(package, '_logo', '')
        if path != '':
            logoPath = self.getResourceLogo(path)

        protName = str(protocol)
        status = protocol.getStatus()
        label = protocol._label if hasattr(protocol, '_label') else protName
        protocolClassName = protocol.getClassName()
        hosts = self.currentProject.getHostNames()

        context = {
            "id": protocol.getObjId(),
            "label": label,
            "protocolName": protName,
            "status": status,
            "expertLevel": hasExpert,
            "color": self.getProtocolColor(status),
            "projectName": self.currentProject.getName(),
            "projectId": projectId,
            "packageLogo": logoPath,
            "protocolId": protocol.getObjId(),
            "hosts": hosts,
            "favicon": self.getResourceIcon('favicon'),
            "cite": protocol.citations(),
            "help": protocol.getHelpText(),
            "protocolClassName": protocolClassName,
            "stdoutLog": protocol.getStdoutLog(),
            "stderrLog": protocol.getStderrLog(),
            "scheduleLog": protocol.getScheduleLog(),
        }

        # Detect available wizards and viewers
        wizards = self.findWizardsWeb(protocol)
        # viewers = findViewersWeb(protocol)

        # Inputs
        inputs = []
        for key, attr in protocol.iterInputAttributes():
            inp = {key: {}}
            inp[key]['_class'] = attr.get().getClassName() if attr and attr.get() else ""
            try:
                inp[key]['info'] = str(attr.get())
            except Exception:
                inp[key]['info'] = ""
            inp[key]['_objValue'] = f"{attr.getObjValue()}.{attr.getExtended()}"
            inp[key]['_parentId'] = attr.getObjValue().getObjId()
            inputs.append(inp)
        context['inputs'] = inputs

        # Outputs
        outputs = []
        for key, attr in protocol.iterOutputAttributes():
            outp = {key: {}}
            outp[key]['_class'] = attr.__class__.__name__
            try:
                outp[key]['info'] = str(attr)
            except Exception:
                outp[key]['info'] = ""
            outp[key]['_objValue'] = f"{protName}.{key}"
            outp[key]['_parentId'] = protocol.getObjId()
            outputs.append(outp)
        context['outputs'] = outputs

        # Definition (params, sections, Line/Group)
        paramsData = []
        for section in protocol._definition.iterSections():
            if section.getLabel() != 'Parallelization':
                sectionData = {"name": section.getLabel(), "params": []}
                if section.getLabel() != 'General':
                    for paramName, param in section.iterParams():
                        if paramName not in headerParams:
                            protVar = getattr(protocol, paramName, None)
                            if protVar is None:
                                # Handle Group
                                if isinstance(param, Group):
                                    group = self.PreprocessParamForm(param, paramName, wizards, None, 0, protVar)
                                    group[paramName]['children'] = []
                                    for paramGroupName, paramGroup in param.iterParams():
                                        protVar = getattr(protocol, paramGroupName, None)

                                        # Line param
                                        if isinstance(paramGroup, Line):
                                            for paramLineName, paramLine in paramGroup.iterParams():
                                                protVar = getattr(protocol, paramLineName, None)
                                                if protVar:
                                                    paramChild = self.PreprocessParamForm(
                                                        paramLine, paramLineName, wizards, None, 0, protVar
                                                    )
                                                    if paramChild:
                                                        group[paramName]['children'].append(paramChild)
                                        elif protVar:
                                            paramChild = self.PreprocessParamForm(
                                                paramGroup, paramGroupName, wizards, None, 0, protVar
                                            )
                                            if paramChild:
                                                group[paramName]['children'].append(paramChild)
                                    if group:
                                        sectionData["params"].append(group)

                                # Handle Line
                                if isinstance(param, Line):
                                    line = self.PreprocessParamForm(param, paramName, wizards, None, 0, protVar)
                                    line[paramName]['children'] = []
                                    for paramLineName, paramLine in param.iterParams():
                                        protVar = getattr(protocol, paramLineName, None)
                                        if protVar:
                                            paramChild = self.PreprocessParamForm(
                                                paramLine, paramLineName, wizards, None, 0, protVar
                                            )
                                            if paramChild:
                                                line[paramName]['children'].append(paramChild)
                                    if line:
                                        sectionData["params"].append(line)

                            else:
                                paramProcessed = self.PreprocessParamForm(param, paramName, wizards, None, 0, protVar)
                                if paramProcessed:
                                    sectionData["params"].append(paramProcessed)

                if section.getLabel() == 'General':
                    # Special params
                    for paramName in headerParams:
                        paramProcessed = {}
                        paramValue = getattr(protocol, paramName, None)
                        if paramName == '_objComment':
                            paramProcessed.setdefault(paramName, {})
                            paramProcessed[paramName]['label'] = 'Comment'
                            paramProcessed[paramName]['expertLevel'] = 0
                            paramProcessed[paramName]['condition'] = None
                            paramProcessed[paramName]['_isImportant'] = True
                            paramProcessed[paramName]['help'] = 'Protocol comments'
                            paramProcessed[paramName]['_class'] = 'StringParam'
                            paramProcessed[paramName]['_objValue'] = paramValue
                            paramProcessed[paramName]['default'] = paramValue
                            paramProcessed[paramName]['readOnly'] = False
                            sectionData["params"].append(paramProcessed)
                        elif paramName == '_useQueue':
                            paramProcessed.setdefault(paramName, {})
                            paramProcessed[paramName]['label'] = 'Use a queue engine?'
                            paramProcessed[paramName]['expertLevel'] = 0
                            paramProcessed[paramName]['condition'] = None
                            paramProcessed[paramName]['_isImportant'] = True
                            paramProcessed[paramName]['help'] = pwutils.Message.HELP_USEQUEUE % (
                                pyworkflow.Config.SCIPION_HOSTS, pyworkflow.DOCSITEURLS.HOST_CONFIG
                            )
                            paramProcessed[paramName]['_class'] = 'BooleanParam'
                            paramProcessed[paramName]['_objValue'] = paramValue
                            paramProcessed[paramName]['default'] = paramValue
                            paramProcessed[paramName]['readOnly'] = False
                            sectionData["params"].append(paramProcessed)
                        elif paramName == '_prerequisites':
                            paramProcessed.setdefault(paramName, {})
                            paramProcessed[paramName]['label'] = 'Wait for'
                            paramProcessed[paramName]['expertLevel'] = 0
                            paramProcessed[paramName]['condition'] = None
                            paramProcessed[paramName]['_isImportant'] = True
                            paramProcessed[paramName]['help'] = pwutils.Message.HELP_WAIT_FOR % (
                                pyworkflow.DOCSITEURLS.WAIT_FOR
                            )
                            paramProcessed[paramName]['_class'] = 'StringParam'
                            paramProcessed[paramName]['_objValue'] = paramValue
                            paramProcessed[paramName]['default'] = paramValue
                            paramProcessed[paramName]['readOnly'] = False
                            sectionData["params"].append(paramProcessed)
                        elif paramName == 'expertLevel':
                            paramProcessed.setdefault(paramName, {})
                            paramProcessed[paramName]['label'] = 'Expert Level'
                            paramProcessed[paramName]['display'] = 0
                            paramProcessed[paramName]['choices'] = ['Normal', 'Advanced']
                            paramProcessed[paramName]['condition'] = None
                            paramProcessed[paramName]['_isImportant'] = True
                            paramProcessed[paramName]['_class'] = 'EnumParam'
                            paramProcessed[paramName]['_objValue'] = 0
                            paramProcessed[paramName]['default'] = 0
                            paramProcessed[paramName]['readOnly'] = False
                            sectionData["params"].append(paramProcessed)
                        else:
                            param = protocol.getParam(paramName)
                            if param is not None:
                                if paramName == 'gpuList':
                                    param.label.set('GPU IDs')
                                    param.condition.set(None)
                                elif paramName == 'runMode':
                                    param.choices = ['Continue', 'Restart']
                                    param.display = 0
                                paramProcessed = self.PreprocessParamForm(param, paramName, wizards, None, 0, None)
                                if paramProcessed:
                                    if paramName == 'runName':
                                        paramProcessed[paramName]['_objValue'] = protName
                                        paramProcessed[paramName]['default'] = protName
                                    sectionData["params"].append(paramProcessed)

                paramsData.append(sectionData)

        context["definition"] = paramsData
        return context

    def getNewProtocolParams(self, projectId, protocolClassName: str) -> dict:
        """
        Returns the parameters of a new protocol given its class name.
        """
        protClass = self.currentProject.getDomain().getProtocols().get(protocolClassName)
        if protClass:
            protocol = self.currentProject.newProtocol(protClass)
            return self._buildProtocolContext(projectId, protocol)
        return {}

    def getProtocolParams(self, projectId: int, protocolId: int) -> dict:
        """
        Returns the parameters of an existing protocol given its ID.
        """
        protocol = self.currentProject.getProtocol(int(protocolId))
        protocol.getPlugin()
        self.currentProject._fixProtParamsConfiguration(protocol)
        return self._buildProtocolContext(projectId, protocol)

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
        else:
            return rawValue

    def applyParamsToProtocol(self, protocol, params):
        """Apply pointer parameters to protocol."""
        errorList = []
        for key, value in params.items():
            param = protocol.getParam(key)
            if param is None:
                continue

            if isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):

                if isinstance(param, MultiPointerParam):
                    newInputs = PointerList()
                    for v in value:
                        parentId = v.get("_parentId")
                        rawValue = v.get("value")
                        if parentId:
                            try:
                                parentProtocol = self.currentProject.getProtocol(int(parentId))
                                extended = (v['_objValue'].split('.')[-1])
                                newInputs.append(Pointer(parentProtocol, extended=extended))
                                logger.info(f"[INFO] Pointer param {key} set from parent {parentId} output {rawValue}")
                            except Exception as e:
                                logger.error(f"[ERROR] Could not set pointer for {key}: {e}")
                        else:
                            # Pointer without parentId, fallback
                            param.set(None)
                    # MultiPointer validation
                    if newInputs.isEmpty() and not param.allowsNull.get():
                        errorList.append('**' + param.label.get() + '** it must not be empty.')
                    protocol.setAttributeValue(key, newInputs)
                elif isinstance(param, PointerParam):
                    parentId = value.get("_parentId")
                    rawValue = value.get("value")
                    if parentId:
                        try:
                            parentProtocol = self.currentProject.getProtocol(int(parentId))
                            val = value['value'] if 'value' in value else value['_objValue']
                            param.set(val)
                            protocol.setAttributeValue(key, parentProtocol)
                            param.default.set(val)
                            pointer = getattr(protocol, key)
                            pointer.setExtended(val.split('.')[-1])

                            logger.info(f"[INFO] Pointer param {key} set from parent {parentId} output {rawValue}")
                        except Exception as e:
                            logger.error(f"[ERROR] Could not set pointer for {key}: {e}")
                    else:
                        # Pointer without parentId, fallback
                        if not param.allowsNull.get():
                            errorList.append('**' + param.label.get() + '** it must not be empty.')
                        param.set(None)
        return errorList

    def setPointerParam(self, protocol, key, value, parentId):
        """Resolve and set a pointer param from parent protocol outputs."""
        param = protocol.getParam(key)
        if not isinstance(param, PointerParam):
            logger.warning(f"[WARN] Param {key} is not a PointerParam")
            return
        parentProtocol = self.currentProject.getProtocol(int(parentId))
        param.set(value['editableValue'])
        protocol.setAttributeValue(key, parentProtocol)
        param.default.set(value['editableValue'])

    def saveProtocol(self, mapper, protocolId, protocolClassName, params, setToSave=True):
        errorList = []
        if not protocolId:  # new protocol
            protClass = self.currentProject.getDomain().getProtocols().get(protocolClassName)
            protocol = self.currentProject.newProtocol(protClass)
        else:  # retrieve a protocol by id
            protocol = self.currentProject.getProtocol(int(protocolId))
        # Set non-pointer parameters
        for key, value in params.items():
            param = protocol.getParam(key)
            if param is None:
                logger.warning(f"[WARN] Param not found: {key}")
                continue

            if isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
                continue

            rawValue = value.get("value")
            try:
                castedValue = self.castParamValue(param, rawValue)
                errors = param.validate(castedValue) if hasattr(param, 'validate') else []
                if errors:
                    errorListAux = ['**' + param.label.get() + '** ' + error for error in errors]
                    errorList += errorListAux
                param.set(castedValue)
                protocol.setAttributeValue(key, castedValue)
                logger.info(f"[INFO] Set param {key} = {castedValue}")
            except Exception as e:
                import re
                cleaned = re.sub(r'[^A-Za-z0-9\s+\-*/=<>\!&|^%()\[\]{}_,.;:]', '', str(e))
                errorList += ['**' + param.label.get() + '** ' + cleaned]

        # Apply pointer parameters
        errorList += self.applyParamsToProtocol(protocol, params)

        if setToSave:
            protocol.setSaved()

        if protocol.hasObjId():
            self.currentProject._storeProtocol(protocol)
        else:
            self.currentProject._setupProtocol(protocol)

        # dbProtocol = mapper.getProtocolByProtocolId(protocolId=protocol.getObjId(),   projectId=27)
        # if not dbProtocol:
        #     # Insert a new protocol
        #     pass
        # else:
        #     # Update parameters and status if exists
        #     pass
        # Save dependencies
        # graphData = self.currentProject.getRunsGraph(refresh=True, checkPids=True)
        # self.saveProtocolDependencies(mapper, graphData._nodesDict)

        return protocol, errorList

    def launchProtocol(self, mapper, protocolId, protocolClassName, params):
        """Launch a protocol in RESTART mode, applying all params."""
        protocol, errors = self.saveProtocol(mapper, protocolId, protocolClassName, params, setToSave=False)
        try:
            errors += protocol._validate()
        except Exception:
            errors += [
                '**Other errors:**There are other validation errors that may be resolved by correcting the previous ones.'
            ]
        if not errors:
            self.currentProject.launchProtocol(protocol)
        else:
            raise HTTPException(status_code=422, detail=errors)

    def findWizardsWeb(self, protocol):
        # TODO: Find wizards...
        """Stub for finding web-based wizards (to be implemented)."""
        return {}

    def getResourceIcon(self, icon):
        """Return absolute path to an icon resource."""
        return os.path.join(self.currentProject.getPath(), icon)

    def getResourceLogo(self, logo):
        """Return absolute path to a logo resource."""
        return os.path.join(self.currentProject.getPath(), logo)

    @staticmethod
    def getPointerHtml(protVar):
        """
        Return (nameId, objId::extended) if pointer parameter has a value,
        otherwise return two empty strings.
        """
        if protVar.hasValue():
            return protVar.getObjValue().getNameId(), '%s::%s' % (protVar.getObjValue().getObjId(),
                                                                  protVar._extended.get())
        return '', ''

    @staticmethod
    def replacePattern(m, mode):
        """Replace hypertext patterns based on the given mode."""
        g1 = m.group(mode)
        if mode == HYPER_BOLD:
            text = " <b>%s</b> " % g1
        elif mode == HYPER_ITALIC:
            text = " <i>%s</i> " % g1
        elif mode == HYPER_LINK1:
            text = " <a href='%s' target='_blank' style='color:firebrick;'>%s</a> " % (g1, g1)
        elif mode == HYPER_LINK2:
            if g1.startswith("sci-open:"):
                url = 'javascript:launchViewer(%s)' % g1[len("sci-open:"):]
            else:
                url = g1
            text = " <a href='%s' target='_blank' style='color:firebrick;'>%s</a> " % (url, m.group('link2_label'))
        else:
            raise Exception("Unrecognized pattern mode: " + mode)

        return text

    def parseText(self, text, func=replacePattern):
        """
        Parse a string or list of strings into HTML,
        injecting <br /> tags at line breaks.
        """
        parsedText = ""
        if isinstance(text, list):
            for itemText in text:
                splitLines = itemText.splitlines(True)
                if len(splitLines) == 0:
                    parsedText += '<br />'
                else:
                    for lineText in splitLines:
                        parsedText += parseHyperText(lineText, func) + '<br />'
        else:
            splitLines = text.splitlines(True)
            for lineText in splitLines:
                parsedText += parseHyperText(lineText, func) + '<br />'
        return parsedText[:-6]

    def PreprocessParamForm(self, param, paramName, wizards, viewerDict, visualize, protVar):
        """
        Serialize a protocol parameter into a dict, handling scalar, pointer, and multipointer types.
        """
        try:
            context = {}
            from pyworkflow.protocol import MultiPointerParam, PointerParam, RelationParam, Boolean
            # RelationParam
            if isinstance(param, RelationParam):
                pass
            else:
                context.setdefault(paramName, {})
                # Public attributes
                for name, value in param.getAttributes():
                    context[paramName][name] = serializeToJson(value)
                # Protected attributes
                for name, value in vars(param).items():
                    if name != 'paramClass' and name != '_form':
                        context[paramName][name] = serializeToJson(value)

                context[paramName]['_class'] = param.__class__.__name__
                if protVar is not None:
                    if isinstance(param, MultiPointerParam):
                        valueList = []
                        defaultValueList = []
                        for pointer in protVar:
                            value = "%s.%s" % (pointer.getObjValue(), pointer.getExtended())
                            obj = {'object': value,
                                   'info': str(pointer.get()),
                                   '_objValue': value,
                                   '_parentId': pointer.get().getObjParentId()}
                            valueList.append(obj)
                            defaultValueList.append(obj)
                        context[paramName]['_objValue'] = valueList
                        context[paramName]['default'] = defaultValueList
                    elif isinstance(param, PointerParam):
                        pointerValue = "%s.%s" % (protVar.getObjValue(), protVar.getExtended()) if protVar.getExtended() else ''
                        context[paramName]['_objValue'] = pointerValue
                        context[paramName]['value'] = pointerValue
                        context[paramName]['default'] = context[paramName]['_objValue']
                        if protVar.get() is not None:
                            context[paramName]['_parentId'] = protVar.get().getObjParentId()
                    else:
                        context[paramName]['_objValue'] = protVar.get() if protVar.get() is not None else ""
                        context[paramName]['value'] = str(context[paramName]['_objValue'])
                        context[paramName]['default'] = str(context[paramName]['_objValue'])

            return context
        except Exception as ex:
            logger.error("ERROR with param: " + paramName)
            raise ex

    def getProtocols(self, mapper: PostgresqlFlatMapper, projectId: int, currentUser) -> Optional[dict]:
        # Retrieve all protocols
        dbProj = mapper.getProject(projectId=projectId, userId=currentUser['id'])
        if not dbProj:
            return None
        from pyworkflow.gui.project.viewprotocols_extra import ProtocolTreeConfig
        configProtocols = Config.SCIPION_PROTOCOLS
        localDir = Config.SCIPION_LOCAL_CONFIG
        protConf = os.path.join(localDir, configProtocols)
        protocolsTree = ProtocolTreeConfig.load(self.currentProject.getDomain(), protConf)
        protocolsTree = serializeToJson(protocolsTree)
        self.walkAndReplaceProtocols(protocolsTree, self.getProtocolName)
        return protocolsTree

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

    def getProtocolName(self, node):
        text = node.get('text')
        if text:
            value = node.get('value') if node.get('value') is not None else text
            protClassName = value.split('.')[-1]
            emProtocolsDict = self.currentProject.getDomain().getProtocols()
            prot = emProtocolsDict.get(protClassName, None)

            if node.get('tag') == 'protocol' and text == 'default':
                if prot is None:
                    logger.warning("Protocol className '%s' not found!!!. \n"
                                   "Fix your config/protocols.conf configuration."
                                   % protClassName)
                    return

                text = prot.getClassLabel()
                return text

        return 'default'

    def getProtocolLogs(self, projectId: int, protocolId: int,
                        offset: int = 0,
                        errOffset: int = 0,
                        scheduleOffset: int = 0):
        protocol = self.getProtocolParams(projectId, protocolId)
        logPath = protocol.get("stdoutLog")
        errLogPath = protocol.get("stderrLog")
        scheduleLogPath = protocol.get("scheduleLog")

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

    def renameProtocol(self, protocolId: int, newName: str):
        protocol = self.currentProject.getProtocol(int(protocolId))
        protocol.setObjLabel(newName)
        self.currentProject._storeProtocol(protocol)
        return {"status": "ok", "message": "Protocol renamed successfully"}

    def duplicateProtocol(self, protocols: Any):
        try:
            protList = []
            for protocol in protocols:
                protList.append(self.currentProject.getProtocol(int(protocol.id)))
            self.currentProject.copyProtocol(protList)
            return {"status": "ok", "message": "Protocol was duplicated successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def deleteProtocol(self, protocols: Any):
        try:
            protList = []
            for protocol in protocols:
                protList.append(self.currentProject.getProtocol(int(protocol)))
            self.currentProject.deleteProtocol(*protList)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def restartProtocolAll(self, protocolId: int):
        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
            workflowProtocolList, activeProtList = self.currentProject._getSubworkflow(protocol)
            errorList = []
            self.currentProject._restartWorkflow(errorList, workflowProtocolList)
            return errorList
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def continueProtocolAll(self, mapper, projectId: int, protocolId: int, currentUser: dict):
        raise NotImplementedError

    def resetProtocolFrom(self, protocolId: int):
        protocol = self.currentProject.getProtocol(int(protocolId))
        try:
            workflowProtocolList, activeProtList = self.currentProject._getSubworkflow(protocol)
            errorProtList = self.currentProject.resetWorkFlow(workflowProtocolList)
            if errorProtList:
                raise HTTPException(status_code=500, detail=errorProtList)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def stopProtocol(self, protocols: Any):
        try:
            for protocolId in protocols:
                protocol = self.currentProject.getProtocol(int(protocolId))
                self.currentProject.stopProtocol(protocol)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def getProtocolPath(self, protocolId):
        protocol = self.currentProject.getProtocol(int(protocolId))
        return protocol.getPath()

    def _protocolRoot(self, protocolId: Union[int, str]) -> FsPath:
        """
        Resolve the absolute root folder for a protocol, using your service.
        """
        root = self.getProtocolPath(str(protocolId))
        if not root:
            raise HTTPException(status_code=404, detail="Protocol path not found")
        return FsPath(root).resolve()

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

    def listProtocolDir(self, protocolId: str, path: str):
        """Return the directory file list."""
        listProjDir = FileHandlers(self.currentProject)
        return listProjDir.listProtocolDir(protocolId, path)

    def previewProtocolTextFile(self, protocolId: str, path: str):
        """
        Return a lightweight preview for a file inside a protocol workspace.
        """
        previewProtTextFile = FileHandlers(self.currentProject)
        return previewProtTextFile.previewProtocolTextFile(protocolId, path)

    def previewProtocolImageFile(self, protocolId, path, inline: bool):
        """
        inline == False:
            - attachment download (binary as-is)
        inline == True:
            - preview mode:
              * if MRC/volume -> PNG slice + X-Preview-* headers
              * if normal image -> raw image + X-Preview-* headers
              * else -> raw bytes + minimal headers
        """
        previewProtImgFile = FileHandlers(self.currentProject)
        return previewProtImgFile.previewProtocolImageFile(protocolId, path, inline)

    def outputPreview(self, protocolId: int, outputName: str, requestHeaders: dict = None, colormap: str = None):
        """
        Return a preview for selected output.

        A fresh ObjectManager is created for every request to keep
        underlying DAOs (and SQLite connections) thread-safe.
        """
        protocol = self.currentProject.getProtocol(protocolId)
        output = getattr(protocol, outputName)
        outputPath = output.getFileName()
        outputPreview = OutputsPreview(
            self.currentProject,
            protocol,
            output,
            requestHeaders=requestHeaders,
            colormapOverride=colormap,
        )
        objMgr = self._createObjectManager()
        return outputPreview.preview(protocolId, outputPath, objMgr)

    # ----------------------------------------------------------------------
    # Internal helpers for TiltSeries (SetOfTiltSeries)
    # ----------------------------------------------------------------------

    @lru_cache
    def _resolveOutputForTiltSeries(self, protocolId: int, outputName: str):
        """
        Resolve protocol + SetOfTiltSeries-like output for tilt series operations.
        """
        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception:
            raise HTTPException(status_code=404, detail="Protocol not found")

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

    # ======================================================================
    # Analyze Results: CTF Tomography (CTFTomoSeries)
    # ======================================================================

    @lru_cache
    def _resolveOutputForCtftomoSeries(self, protocolId: int, outputName: str):
        """
        Resolve protocol + CTFTomoSeries-like output for CTF tomography operations.

        The output can be:
          * a single CTFTomoSeries (one tilt-series)
          * a container of CTFTomoSeries objects (SetOfCTFTomoSeries)
        """
        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception:
            raise HTTPException(status_code=404, detail="Protocol not found")

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
        protocol, output = self._resolveOutputForCtftomoSeries(protocolId, outputName)

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
        protocol, output = self._resolveOutputForCtftomoSeries(protocolId, outputName)

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
    ) -> Response:
        """
            Render a single CTFtomo PSD image using the OutputsPreview pipeline.

            - psdPath can be relative to the protocol root or an absolute path.
            - size sets the max side in pixels for the thumbnail (square).
            - fmt controls the output format: png | jpg | webp.
            - index is used when the PSD is stored in a stack file.
            - applyTransform/rot/shifts are optional alignment parameters.
            """
        protocol, output = self._resolveOutputForCtftomoSeries(protocolId, outputName)
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

    # ======================================================================
    # Analyze Results: Volumes (Volume / VolumeMask / SetOfVolumes)
    # ======================================================================

    def _resolveOutputForVolumes(self, protocolId: int, outputName: str):
        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception:
            raise HTTPException(status_code=404, detail="Protocol not found")

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

    def listOutputVolumesService(self, projectId: int, protocolId: int, outputName: str):
        protocol, output = self._resolveOutputForVolumes(protocolId, outputName)
        op = OutputsPreview(self.currentProject, protocol, output)
        return op.listOutputVolumes()

    def getVolumeInfoService(self, projectId: int, protocolId: int, outputName: str, volumeId: int):
        protocol, output = self._resolveOutputForVolumes(protocolId, outputName)
        op = OutputsPreview(self.currentProject, protocol, output)
        return op.getVolumeInfo(volumeId)

    def getVolumeHistogramService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            volumeId: Union[int, str],
            bins: int = 128,
    ):
        """
        Compute or retrieve an intensity histogram for a single volume.

        It delegates to OutputsPreview so all volume handling stays in one place.
        The result is normalized to always expose:
        {
          "binEdges": [...],
          "counts":   [...]
        }
        """
        protocol, output = self._resolveOutputForVolumes(protocolId, outputName)
        op = OutputsPreview(self.currentProject, protocol, output)

        if isinstance(output, SetOfVolumes):
            output = output.getItem('_objId', volumeId + 1)
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

    def renderVolumeSliceService(
            self, projectId: int, protocolId: int, outputName: str, volumeId: int,
            sliceIndex: int, axis: str, colormap: Optional[str], normalize: Optional[str],
            scale: float, inline: bool, fmt: str = "webp",
            thumb: Optional[int] = None, fast: bool = True, quality: int = 75,
    ) -> Response:
        protocol, output = self._resolveOutputForVolumes(protocolId, outputName)
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
    ):
        protocol, output = self._resolveOutputForVolumes(protocolId, outputName)
        volumePath = self._getVolumePathFromOutput(output, volumeId)

        try:
            vol, _props = readVolumeArray3d(volumePath)  # Z, Y, X
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Volume file not found on disk")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Cannot read volume file: {e}")

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
        _, setOfTiltSeries = self._resolveOutputForTiltSeries(protocolId, outputName)

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
        protocol, setOfTiltSeries = self._resolveOutputForTiltSeries(protocolId, outputName)
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
        protocol, inputSet = self._resolveOutputForCtftomoSeries(protocolId, outputName)

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
        try:
            protocol._defineOutputs(**{newOutputName: outputSet})
            protocol._store()
        except Exception:
            logger.exception("Error attaching Ctftomo filtered set '%s' to protocol", newOutputName,)

        logger.info(
            "The new Ctftomo set (%s) has been created successfully with %d series", newOutputName, createdCount,)

        return {
            "status": "ok",
            "outputName": newOutputName,
            "createdSeries": createdCount,
            "restack": bool(restack),
        }

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
    ):
        protocol, setOfTiltSeries = self._resolveOutputForTiltSeries(protocolId, outputName)
        ts = setOfTiltSeries.getItem('_tsId', tiltSeriesId)
        ti = ts.getItem('_index', index)
        rot = shifts = None
        if applyTransform and ti.hasTransform():
            transf = ti.getTransform()
            _, _, rot = transf.getEulerAngles()
            rot = np.rad2deg(-rot)
            list = transf.getMatrixAsList()
            shifts = list[2], list[5]

        preview = OutputsPreview(
            currentProject=self.currentProject,
            protocol=protocol,
            output=ts,
            requestHeaders=requestHeaders,
        )
        return preview.renderImageFromFilePath(os.path.abspath(ti.getFileName()),
                                               size=size,
                                               fmt=fmt,
                                               index=index,
                                               applyTransform=applyTransform,
                                               inline=inline,
                                               rot=rot,
                                               shifts=shifts)

    def createNewSetOfTiltSeriesService(
        self,
        projectId: int,
        protocolId: int,
        outputName: str,
        exclusions: Dict[str, Any],
        restack: bool,
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
        protocol, inputSet = self._resolveOutputForTiltSeries(protocolId, outputName)
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
            excludedTiltIndices: Set[int] = set()

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
        logger.info("The new set (%s) has been created successfully", newOutputName)

        return {
            "status": "ok",
            "outputName": newOutputName,
            "createdTiltSeries": createdCount,
            "hasOddEven": bool(hasOddEven),
            "restack": bool(restack),
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
    def listCoordinates3dTomogramsService(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
    ):
        """
        Return a list of tomograms referenced by the SetOfCoordinates3D output.

        Normalized shape:
        [
          { "id": <tomoId>, "name": "<label>" },
          ...
        ]
        """
        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception:
            raise HTTPException(status_code=404, detail="Protocol not found")

        setOfCoordinates3D = getattr(protocol, outputName, None)
        if setOfCoordinates3D is None:
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' not found in protocol",
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
          },
          ...
        ]
        """
        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception:
            raise HTTPException(status_code=404, detail="Protocol not found")

        setOfCoordinates3D = getattr(protocol, outputName, None)
        if setOfCoordinates3D is None:
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' not found in protocol",
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

        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception:
            raise HTTPException(status_code=404, detail="Protocol not found")

        setOfCoordinates3D = getattr(protocol, outputName, None)
        if setOfCoordinates3D is None:
            raise HTTPException(
                status_code=404,
                detail=f"Output '{outputName}' not found in protocol",
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
            gray = np.asarray(pilTmp, copy=False)

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

    # ======================================================================
    # Internal helpers for metadata tables (STAR / SQLITE / etc.)
    # ======================================================================

    def _resolveOutputForMetadata(self, protocolId: int, outputName: str):
        """
        Resolve protocol and output object for metadata operations.

        It also normalizes the metadata file path:
        - If getFileName() returns a relative path, it is interpreted as
          project-relative.
        - Raises 404 if the final path does not exist on disk.
        """
        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception:
            raise HTTPException(status_code=404, detail="Protocol not found")

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

    def _openMetadataTable(self, protocolId: int, outputName: str, tableName: str):
        """
        Resolve (ObjectManager, Table) for a given output + tableName.
        """
        _, _, metaPath = self._resolveOutputForMetadata(protocolId, outputName)
        objMgr = self._getMetadataObjectManager(metaPath)
        table = objMgr.getTable(tableName)
        if table is None:
            raise HTTPException(
                status_code=404,
                detail=f"Metadata table '{tableName}' not found"
            )
        return objMgr, table

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
                                        outputName: str):
        """
        List logical metadata tables associated with an output.
        """
        with _metadataLock:
            _, _, metaPath = self._resolveOutputForMetadata(protocolId, outputName)
            objMgr = self._getMetadataObjectManager(metaPath)

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
                                      tableName: str):
        """
        Return logical schema for one metadata table: columns, renderers, flags.
        """
        with _metadataLock:
            objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)

            visibleLabels = []
            orderLabels = []
            renderLabels = []

            if table.getName() == SQLITE_OBJECT_TABLE:
                from pwem.viewers.viewers_data import RegistryViewerConfig
                protocol = self.currentProject.getProtocol(int(protocolId))
                output = getattr(protocol, outputName)

                config = RegistryViewerConfig.getConfig(type(output)) or {}

                fileNameLabel = ' _filename'
                stackLabel = ' stack'

                visibleLabelsStr = config.get(VISIBLE, '')
                orderLabelsStr = config.get(ORDER, '')
                renderLabelsStr = config.get(RENDER, '')

                orderLabelsStr = orderLabelsStr.replace(fileNameLabel, stackLabel, 1)
                renderLabelsStr = renderLabelsStr.replace(fileNameLabel, stackLabel, 1)

                if fileNameLabel in visibleLabelsStr and stackLabel not in renderLabelsStr:
                    renderLabelsStr += stackLabel
                    visibleLabelsStr += stackLabel

                visibleLabels = visibleLabelsStr.split()
                orderLabels = orderLabelsStr.split()
                renderLabels = renderLabelsStr.split()

            try:
                hasColumnId = table.hasColumnId()
            except Exception:
                hasColumnId = True

            columns = list(table.getColumns())
            schema = {
                "name": tableName,
                "alias": table.getAlias(),
                "hasColumnId": bool(hasColumnId),
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
    ):
        """
        Return one logical page of rows for a metadata table.
        Sorting is currently delegated to the underlying DAO default order.
        """
        with _metadataLock:
            objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)
            columns = list(table.getColumns())

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
    ) -> Response:
        """
        Export metadata table as CSV or XLSX.

        - If ids is provided -> export those ids.
        - Else if selectionOnly -> try server-side selection.
        - Else -> export whole table.
        """
        import csv

        with _metadataLock:
            objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)
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

        # Resolve metadata root path for relative image paths
        try:
            _protocol, _output, metaPath = self._resolveOutputForMetadata(protocolId, outputName)
            metaDir = LocalPath(metaPath).parent
        except HTTPException:
            # If the output / metadata file is really missing, that is a real error
            raise
        except Exception:
            metaDir = None

        objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)
        columns = list(table.getColumns())

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
                        imgPath = LocalPath(img)

                        # Build candidates for relative paths:
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
                                    prot = self.currentProject.getProtocol(int(protocolId))
                                    protPath = LocalPath(prot.getPath())
                            except Exception:
                                protPath = None

                            if protPath is not None:
                                candidates.append(protPath / imgPath)
                            if projPath is not None:
                                candidates.append(projPath / imgPath)

                            # Original relative path as last resort
                            candidates.append(imgPath)

                        resolvedPath = None
                        for cand in candidates:
                            if cand.exists():
                                resolvedPath = cand
                                break

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
                                logger.error(
                                    "Cannot open image file '%s' for metadata cell: %s",
                                    str(resolvedPath),
                                    e,
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

            im255 = self._normalize2dSlice(arrGray, mode="minmax")
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
            objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)
            columns = list(table.getColumns())

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
