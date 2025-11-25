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
import numpy as np

from metadataviewer.dao.numpy_dao import NumpyDao
from metadataviewer.model import ObjectManager
from tomo.constants import SCIPION, BOTTOM_LEFT_CORNER

from app.backend.utils.constants import SQLITE_OBJECT_TABLE
from app.backend.utils.outputs_preview import OutputsPreview
from pwem.emlib.image.image_readers import ImageReadersRegistry
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
from typing import List, Optional, Any, Union, Tuple, Dict
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
from app.backend.api.schemas.project_schema import ProjectCreate
from app.backend.utils.file_handlers import FileHandlers


from app.backend.models.project_model import ProjectUpdateRequest
from app.utils.scipion_helper import serializeToJson

from dataclasses import dataclass
from functools import lru_cache
from threading import RLock

_VOLUME3D_LOCK = RLock()


@dataclass(frozen=True)
class _VolSig:
    path: str
    mtime_ns: int
    size: int


def _statSig(p: FsPath) -> _VolSig:
    st = p.stat()
    return _VolSig(str(p), st.st_mtime_ns, st.st_size)


@lru_cache(maxsize=8)
def _readVolumeCached(sig: _VolSig) -> Any:
    """Disk -> numpy only once per (path, mtime, size)."""
    imgStk = ImageReadersRegistry.open(sig.path)
    data = np.asarray(imgStk.getImages())

    if data.ndim not in (2, 3):
        data = np.squeeze(data)
        if data.ndim not in (2, 3):
            raise ValueError(f"Unsupported dimensionality: {data.shape}")

    try:
        props = imgStk.getProperties() or {}
    except Exception:
        props = {}

    return np.asarray(data, dtype=np.float32), props


class ProjectService:
    def __init__(self):
        self.manager = Manager()
        self.currentProject = None
        # Keep objectManager attribute for backward compatibility,
        # but new HTTP endpoints use a fresh ObjectManager per request.
        self.objectManager = None

    def clearCurrentProject(self):
        self.currentProject = None

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
        # Retrieve projects from PostgreSQL using the mapper
        dbProjects = mapper.listProjects(ownerId=currentUser["id"])
        result = []

        for dbProj in dbProjects:
            path = self.manager.getProjectPath(dbProj['name'])
            sizeGB = self.getProjectSize(path) / (1024 ** 3)
            protCount = self.countProtocols(os.path.join(path, "Runs"))

            result.append({
                "id": dbProj['id'],
                "name": os.path.basename(dbProj['name']),
                "description": dbProj.get('description', ''),
                "createdAt": dbProj.get('createdAt'),
                "status": dbProj.get('status', 'active'),
                "protocolsCount": str(protCount),
                "diskUsage": f"{sizeGB:.2f} GB"
            })

        return result

    def getProjectById(self, mapper: PostgresqlFlatMapper, projectId: int, currentUser) -> Optional[dict]:
        # Retrieve project from PostgreSQL using the mapper
        dbProj = mapper.getProject(projectId=projectId, ownerId=currentUser["id"])
        if not dbProj:
            return None
        projectPath = dbProj['name']
        if not os.path.exists(projectPath):
            return None

        return self.loadProject(dbProj, mapper)

    def updateProject(self, mapper: PostgresqlFlatMapper, projectId: int, currentUser: dict, projectData: ProjectUpdateRequest):
        project = self.getProjectById(mapper, projectId, currentUser)

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        self.manager.renameProject(project['name'], projectData.name)
        mapper.updateProject(projectId, currentUser['id'],
                             self.manager.getProjectPath(projectData.name),
                             projectData.description)

        return project

    def deleteProject(self, mapper: PostgresqlFlatMapper, currentUser, projectId) -> Optional[dict]:
        project = self.getProjectById(mapper, projectId, currentUser)
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

                # Iterate over the inputs
                for key, attr in protocol.iterInputAttributes():
                    input = {}
                    input.setdefault(key, {})
                    try:
                        input[key]['_class'] = attr.get().getClassName() if attr and attr.get() else ""
                        input[key]['info'] = str(attr.get())
                    except Exception as e:
                        input[key]['_class'] = ""
                        input[key]['info'] = ""

                    input[key]['_objValue'] ="%s.%s" % (attr.getObjValue(), attr.getExtended())
                    input[key]['_parentId'] = attr.getObjValue().getObjId()
                    inputs.append(input)

                # Iterate over the outputs
                for key, attr in protocol.iterOutputAttributes():
                    output = {}
                    output.setdefault(key, {})
                    output[key]['_class'] = attr.__class__.__name__
                    try:
                        output[key]['info'] = attr.__str__()
                    except Exception as e:
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

    def loadProject(self, dbProj: dict, mapper: PostgresqlFlatMapper = None) -> dict:
        projPath = dbProj['name']
        self.currentProject = ScipionProject(pyworkflow.Config.getDomain(), projPath)
        self.currentProject.load(dbPath=self.currentProject.getDbPath())
        runs = self.currentProject.getRunsGraph(refresh=True, checkPids=True)
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
        status_colors = {
            "finished": "#D2F5CB",
            "failed": "#F5CCCB",
            "aborted": "#F5CCCB",
            "running": "#FCCE62",
            "saved": "#D9F1FA",
            "launched": "#FCCE62",
            "scheduled": "#918516",
            "new": "#D9F1FA",
        }
        return status_colors.get(status.lower(), "#9e9e9e")

    def _buildProtocolContext(self, projectId, protocol) -> dict:
        """
        Build the common context dictionary for a protocol,
        including inputs, outputs, definition, status, color, logos, etc.
        """
        from pyworkflow.protocol import Line, Group

        HEADER_PARAMS = ['runName',  '_objComment', '_useQueue', '_prerequisites', 'gpuList', 'numberOfThreads']
        # Basic metadata
        package = protocol.getClassPackage()
        hasExpert = protocol.hasExpert()
        if hasExpert:
            HEADER_PARAMS.append('expertLevel')
        HEADER_PARAMS.append('runMode')
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
                        if paramName not in HEADER_PARAMS:
                            protVar = getattr(protocol, paramName, None)
                            if protVar is None:
                                # Handle Group
                                if isinstance(param, Group):
                                    group = self.PreprocessParamForm(param, paramName, wizards, None, 0, protVar)
                                    group[paramName]['children'] = []
                                    for paramGroupName, paramGroup in param.iterParams():
                                        protVar = getattr(protocol, paramGroupName, None)

                                        # LINE PARAM
                                        if isinstance(paramGroup, Line):
                                            for paramLineName, paramLine in paramGroup.iterParams():
                                                protVar = getattr(protocol, paramLineName, None)
                                                if protVar:
                                                    paramChild = self.PreprocessParamForm(paramLine, paramLineName, wizards, None,
                                                                                          0, protVar)
                                                    if paramChild:
                                                        group[paramName]['children'].append(paramChild)
                                        elif protVar:
                                            paramChild = self.PreprocessParamForm(paramGroup, paramGroupName, wizards, None, 0,
                                                                                  protVar)
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
                                            paramChild = self.PreprocessParamForm(paramLine, paramLineName, wizards, None, 0,
                                                                                  protVar)
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
                    for paramName in HEADER_PARAMS:
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
                            paramProcessed[paramName]['help'] = pwutils.Message.HELP_USEQUEUE % (pyworkflow.Config.SCIPION_HOSTS, pyworkflow.DOCSITEURLS.HOST_CONFIG)
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
                            paramProcessed[paramName]['help'] = pwutils.Message.HELP_WAIT_FOR % pyworkflow.DOCSITEURLS.WAIT_FOR
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
                            # Pointer sin parentId, fallback
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
                    else:  # Pointer without parentId, fallback
                        # MultiPointer validation
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
                errors = param.validate(castedValue)
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

        dbProtocol = mapper.getProtocolByProtocolId(protocolId=protocol.getObjId(),
                                                    projectId=27)
        if not dbProtocol:
            # Insert a new protocol
            pass
        else:
            # Update parameters and status if exists
            pass
        # Save dependencies
        # graphData = self.currentProject.getRunsGraph(refresh=True, checkPids=True)
        # self.saveProtocolDependencies(mapper, graphData._nodesDict)

        return protocol, errorList

    def launchProtocol(self, mapper, protocolId, protocolClassName, params):
        """Launch a protocol in RESTART mode, applying all params."""

        # Store & launch
        protocol, errors = self.saveProtocol(mapper, protocolId, protocolClassName, params, setToSave=False)
        try:
            errors += protocol._validate()
        except Exception as e:
            errors += ['**Other errors:**There are other validation errors that may be resolved by correcting the previous ones.']
        if not errors:
            self.currentProject.launchProtocol(protocol)
        else:
            raise HTTPException(status_code=422, detail=errors)

    def findWizardsWeb(self, protocol):
        # TODO: Find wizards...
        """Stub for finding web‐based wizards (to be implemented)."""
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
            # if protVar.get() is None:
            #    raise Exception("protVar.hasValue...and .get() is None")
            # TODO: CHECK THIS LATER to display better when _extended attribute
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
        #        parsedText = parseHyperText(text, func)
        return parsedText[:-6]

    def PreprocessParamForm(self, param, paramName, wizards, viewerDict, visualize, protVar):
        """
        Serialize a protocol parameter into a dict, handling scalar, pointer, and multipointer types.
        """
        try:
            context = {}
            from pyworkflow.protocol import MultiPointerParam, PointerParam, RelationParam, Boolean
            # RELATION PARAM
            if isinstance(param, RelationParam):
                pass
                # param.htmlValue, param.htmlIdValue = self.getPointerHtml(protVar)
                # param.relationName = param.getName()
                # param.attributeName = param.getAttributeName()
                # param.direction = param.getDirection()

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
                        # TODO CHECK THIS LATER to display better when no _extended attribute
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
                        # TODO CHECK THIS LATER to display better when no _extended attribute
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
        dbProj = mapper.getProject(projectId=projectId, ownerId=currentUser['id'])
        if not dbProj:
            return None
        from pyworkflow.gui.project.viewprotocols_extra import ProtocolTreeConfig
        configProtocols = Config.SCIPION_PROTOCOLS
        localDir = Config.SCIPION_LOCAL_CONFIG
        protConf = os.path.join(localDir, configProtocols)
        protocolsTree = ProtocolTreeConfig.load(self.currentProject.getDomain(),  protConf)
        protocolsTree = serializeToJson(protocolsTree)
        self.walkAndReplaceProtocols(protocolsTree, self.getProtocolName)
        return protocolsTree

    def replaceDefaultProtocolText(self, node: dict, resolverFn):
        # Determine type and extract text, tag, and children
        if isinstance(node, dict):
            text = node.get("text")
            tag = node.get("tag")
            children = node.get("childs", [])
        else:  # assume ProtocolConfig
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
                    # If the value is a dict, check/replace its text
                    self.replaceDefaultProtocolText(value, resolverFn)
                elif isinstance(value, list):
                    # If the value is a list, apply the function to each item
                    for item in value:
                        if isinstance(item, dict):
                            self.replaceDefaultProtocolText(item, resolverFn)
        elif isinstance(data, list):
            # If the root itself is a list, iterate and apply the replacement
            for item in data:
                if isinstance(item, dict):
                   self.replaceDefaultProtocolText(item, resolverFn)

    def getProtocolName(self, node):
        text = node.get('text')
        if text:
            value = node.get('value') if node.get('value') is not None else text
            protClassName = value.split('.')[-1]  # Take last part
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

        stdout_content, stderr_content, schedule_content = "", "", ""
        new_offset_out, new_offset_err, new_offset_schedule = offset, errOffset, scheduleOffset

        # Handle stdout log
        if logPath and os.path.exists(logPath):
            with open(logPath, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(offset)
                stdout_content = f.read()
                new_offset_out = f.tell()

        # Handle stderr log
        if errLogPath and os.path.exists(errLogPath):
            with open(errLogPath, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(errOffset)
                stderr_content = f.read()
                new_offset_err = f.tell()

        if scheduleLogPath and os.path.exists(scheduleLogPath):
            with open(scheduleLogPath, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(scheduleOffset)
                schedule_content = f.read()
                new_offset_schedule = f.tell()

        if not stdout_content and not stderr_content and not schedule_content and not (
                logPath and os.path.exists(logPath)
        ) and not (errLogPath and os.path.exists(errLogPath)) and not (scheduleLogPath and os.path.exists(scheduleLogPath)):
            raise HTTPException(status_code=404, detail="No logs found")

        return {
            "stdoutLog": stdout_content,
            "stderrLog": stderr_content,
            "stdoutOffset": new_offset_out,
            "stderrOffset": new_offset_err,
            "scheduleLog": schedule_content,
            "scheduleOffset": new_offset_schedule,
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

    def restartProtocolAll(self,protocolId: int):
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

    def _protocolRoot(self, protocol_id: Union[int, str]) -> FsPath:
        """
        Resolve the absolute root folder for a protocol, using your service.
        """
        root = self.getProtocolPath(str(protocol_id))
        if not root:
            raise HTTPException(status_code=404, detail="Protocol path not found")
        return FsPath(root).resolve()

    @staticmethod
    def _guardJoin(root: FsPath, rel_path: str) -> FsPath:
        """
        Join root + rel_path, resolve, and ensure it stays inside root.
        """
        # Treat incoming path as relative to the protocol root
        rel = (rel_path or "").strip().lstrip("/\\")
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
        """Return the directory file list"""
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
        outputPreview = OutputsPreview(self.currentProject, protocol, output, requestHeaders=requestHeaders,
                                       colormapOverride=colormap,)
        objMgr = self._createObjectManager()
        return outputPreview.preview(protocolId, outputPath, objMgr)

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
        # Generic singular/plural fallbacks
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

        # This expects OutputsPreview to expose `getVolumeHistogram`
        if isinstance(output, SetOfVolumes):
            output = output.getItem('_objId', volumeId+1)
        raw = op.getVolumeHistogram(volumePath=output.getFileName(), bins=bins)

        if not raw:
            return {"binEdges": [], "counts": []}

        # Accept a couple of variants from OutputsPreview and normalize
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
            thumb: Optional[int] = None, fast: bool = False, quality: int = 75,
    ) -> Response:
        protocol, output = self._resolveOutputForVolumes(protocolId, outputName)
        op = OutputsPreview(self.currentProject, protocol, output)
        # IMPORTANT: forward all args (antes no pasaba fmt/fast/quality)
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

    def _readVolumeArray3d(self, volumePath: str) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Read a volume using ImageReadersRegistry (same as OutputsPreview),
        returning:
          - arr: float32 numpy array (Z, Y, X)
          - props: dict with reader properties
        Cached by (path, mtime_ns, size).
        """
        p = FsPath(volumePath)
        if not p.exists():
            raise HTTPException(status_code=404, detail="Volume file not found on disk")

        sig = _statSig(p)

        # Guard cache access in case multiple threads hit it at once
        with _VOLUME3D_LOCK:
            arr, props = _readVolumeCached(sig)

        if arr.ndim == 2:
            arr = arr[None, ...]  # (1, Y, X)

        return arr, props

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

        vol, _props = self._readVolumeArray3d(volumePath)  # Z,Y,X
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

            # Frontend volumeId is 0-based index; Scipion items are 1-based in this context.
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
            # try common keys
            for k in ("data", "volume", "arr_0"):
                if k in zf:
                    return np.asarray(zf[k], dtype=np.float32)
            # fallback to first key
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

        # Try pwem ImageHandler (common in Scipion)
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
                # Fallback to binning if scipy is not installed
                pass

        # Default: binning
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

        tomogramList: List[Dict[str, Any]] = []
        tomos_iter = None

        for attr_name in ("iterTomograms", "iterVolumes"):
            func = getattr(setOfCoordinates3D, attr_name, None)
            if callable(func):
                try:
                    tomos_iter = func()
                    break
                except Exception:
                    tomos_iter = None

        if tomos_iter is None:
            get_tomos = getattr(setOfCoordinates3D, "getTomograms", None)
            if callable(get_tomos):
                try:
                    tomos = get_tomos()
                    tomos_iter = (
                        tomos.iterItems() if hasattr(tomos, "iterItems") else iter(tomos)
                    )
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to iterate tomograms: {e}",
                    )

        if tomos_iter is None:
            raise HTTPException(
                status_code=500,
                detail="SetOfCoordinates3D does not expose tomograms iterator",
            )

        if hasattr(tomos_iter, "iterItems"):
            iterator = tomos_iter.iterItems()
        else:
            iterator = iter(tomos_iter)

        for index, tomo in enumerate(iterator):
            tomo_id = None
            for fn_name in ("getTsId", "getObjId"):
                fn = getattr(tomo, fn_name, None)
                if callable(fn):
                    try:
                        tomo_id = fn()
                        if tomo_id is not None:
                            break
                    except Exception:
                        continue
            if tomo_id is None:
                tomo_id = index

            label = None
            for fn_name in ("getObjLabel", "getNameId", "getFileName"):
                fn = getattr(tomo, fn_name, None)
                if callable(fn):
                    try:
                        label = fn()
                        if label:
                            break
                    except Exception:
                        continue

            if not label:
                label = str(tomo_id)

            sr = tomo.getSamplingRate()

            tomogramList.append(
                {
                    "id": tomo_id,
                    "name": str(label),
                    "label": tomo_id,
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

        Shape devuelto:
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
            sr = float(setOfCoordinates3D.getSamplingRate())
        except Exception:
            sr = None

        key: Union[int, str] = tomogramId
        if isinstance(tomogramId, str):
            try:
                key = int(tomogramId)
            except ValueError:
                key = tomogramId

        try:
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
                x = int(coord.getX(BOTTOM_LEFT_CORNER))
                y = int(coord.getY(BOTTOM_LEFT_CORNER))
                z = int(coord.getZ(BOTTOM_LEFT_CORNER))
            except Exception:
                continue

            p: Dict[str, Any] = {"x": x, "y": y, "z": z}

            get_id_fn = getattr(coord, "getObjId", None)
            if callable(get_id_fn):
                try:
                    objId = get_id_fn()
                    if objId is not None:
                        p["id"] = objId
                except Exception:
                    pass

            get_class_fn = getattr(coord, "getClassId", None)
            if callable(get_class_fn):
                try:
                    classId = get_class_fn()
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

            get_weight_fn = getattr(coord, "getWeight", None)
            if callable(get_weight_fn):
                try:
                    w = get_weight_fn()
                    if w is not None:
                        p["weight"] = float(w)
                except Exception:
                    pass

            if sr is not None:
                p["radius"] = float(sr)

            p["tomoId"] = tomoId

            points.append(p)

        return points

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
            thumb: Optional[int] = None,
            fast: bool = False,
            quality: int = 75,
    ) -> Response:
        """
        Render a 2D slice from a tomogram referenced by a SetOfCoordinates3D.

        This is similar in spirit to renderVolumeSliceService, but it takes the
        tomogram from the SetOfCoordinates3D instead of from a Volume/SetOfVolumes
        output. The response is an image (PNG/JPEG/WEBP) ready to be consumed by
        the frontend as <img src="..."> or as an object URL.
        """
        from PIL import Image as PILImage  # local import

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

        vol3d, _props = self._readVolumeArray3d(volumePath)  # Z, Y, X

        axis = (axis or "z").lower()
        if axis not in ("x", "y", "z"):
            axis = "z"

        # Check slice index bounds and extract the 2D slice
        if axis == "z":
            dim = vol3d.shape[0]
        elif axis == "y":
            dim = vol3d.shape[1]
        else:
            dim = vol3d.shape[2]

        if sliceIndex < 0 or sliceIndex >= dim:
            raise HTTPException(status_code=400, detail="Slice index out of range")

        if axis == "z":
            slice2d = vol3d[sliceIndex, :, :]
        elif axis == "y":
            slice2d = vol3d[:, sliceIndex, :]
        else:
            slice2d = vol3d[:, :, sliceIndex]

        slice2d = np.asarray(slice2d, dtype=np.float32)

        # Optional scaling factor (keep it simple, best effort)
        if scale is not None and scale != 1.0:
            try:
                from scipy.ndimage import zoom
                slice2d = zoom(slice2d, zoom=float(scale), order=1, prefilter=False)
            except Exception:
                # If scipy is not available, ignore scale
                pass

        # Normalize to 0..1 for display
        normalize = (normalize or "minmax").lower()
        if normalize == "zscore":
            mean = float(slice2d.mean())
            std = float(slice2d.std()) or 1.0
            slice2d = (slice2d - mean) / std

        vmin = float(slice2d.min())
        vmax = float(slice2d.max())
        if vmax > vmin:
            sliceNorm = (slice2d - vmin) / (vmax - vmin)
        else:
            sliceNorm = np.zeros_like(slice2d, dtype=np.float32)

        # Optional thumbnail: enforce max size in pixels
        if thumb is not None and thumb > 0:
            imgTmp = (sliceNorm * 255.0).clip(0, 255).astype(np.uint8)
            pilTmp = PILImage.fromarray(imgTmp, mode="L")
            pilTmp.thumbnail((thumb, thumb))
            sliceNorm = np.asarray(pilTmp, dtype=np.float32) / 255.0

        # Map to 0..255 and optionally apply colormap
        imgArray = (sliceNorm * 255.0).clip(0, 255).astype(np.uint8)
        pilMode = "L"

        if colormap:
            try:
                import matplotlib.cm as cm
                cmapObj = cm.get_cmap(colormap)
                rgba = cmapObj(sliceNorm)  # 0..1 RGBA
                rgb = (rgba[..., :3] * 255.0).clip(0, 255).astype(np.uint8)
                imgArray = rgb
                pilMode = "RGB"
            except Exception:
                # If matplotlib is not available or colormap fails, fall back to grayscale
                pilMode = "L"

        img = PILImage.fromarray(imgArray, mode=pilMode)

        # Encode image into requested format
        buf = io.BytesIO()
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

        img.save(buf, format=pilFormat, **saveKw)

        # HTTP headers (similar style to other preview endpoints)
        disp = "inline" if inline else "attachment"
        filename = f"coords3d_{tomogramId}_axis-{axis}_slice-{sliceIndex}.{fmtLower}"

        headers = {
            "Content-Disposition": f'{disp}; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition, X-Preview-Mime, X-Preview-Width, X-Preview-Height, X-Preview-Depth, X-Preview-Colormap, X-Preview-Format, X-Preview-TomogramId",
            "X-Preview-Mime": mediaType,
            "X-Preview-Width": str(img.width),
            "X-Preview-Height": str(img.height),
            "X-Preview-Depth": "1",
            "X-Preview-Colormap": colormap or "",
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
        if not metaPath or not os.path.exists(metaPath):
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
        # Follow the same pattern used in OutputsPreview._previewSqlite
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

        # Image cells: do not materialize the image here, just mark as image
        if clsName == "ImageRenderer":
            return {
                "kind": "image",
                "path": "" if rawValue is None else str(rawValue),
            }

        # Matrix cells: render and convert ndarray to list
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

        # Default: just render and ensure JSON-friendly
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
        Used by:
          GET /projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables
        """
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
        Used by:
          GET /projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/schema
        """
        objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)

        visibleLabels = []
        orderLabels = []
        renderLabels = []

        # It is only possible to manage the main table("object").
        if table.getName() == SQLITE_OBJECT_TABLE:
            from pwem.viewers.viewers_data import RegistryViewerConfig
            protocol = self.currentProject.getProtocol(int(protocolId))
            output = getattr(protocol, outputName)

            # Get viewer config or fall back to empty dict
            config = RegistryViewerConfig.getConfig(type(output)) or {}

            fileNameLabel = ' _filename'
            stackLabel = ' stack'

            # Read raw label strings with safe defaults
            visibleLabelsStr = config.get(VISIBLE, '')
            orderLabelsStr = config.get(ORDER, '')
            renderLabelsStr = config.get(RENDER, '')

            # Replace only the first filename occurrence by stack
            orderLabelsStr = orderLabelsStr.replace(fileNameLabel, stackLabel, 1)
            renderLabelsStr = renderLabelsStr.replace(fileNameLabel, stackLabel, 1)

            # Ensure stack is rendered if filename was visible
            if fileNameLabel in visibleLabelsStr and stackLabel not in renderLabelsStr:
                renderLabelsStr += stackLabel
                visibleLabelsStr += stackLabel

            # Convert space-separated strings to lists
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

            if hasattr(col, "isVisible"):
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
        objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)
        columns = list(table.getColumns())

        # Selection-only mode: use Table.Selection if present
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
            # Normal pagination: offset + limit
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
        import csv  # local import to avoid touching module header

        objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)
        columns = list(table.getColumns())
        colNames = [c.getName() for c in columns]

        # Determine row ids to export
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
            rowIds = None  # will export whole table

        # Collect rows to export
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
            # XLSX export requires openpyxl
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

        The row can be located either by:
        - rowIndex (preferred for virtual scrolling): 0-based index in the current table order
        - rowId (legacy): logical row id, interpreted as 1-based index
        """
        from PIL import Image as PILImage  # local import

        objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)
        columns = list(table.getColumns())

        # Resolve column index
        colIndex = table.getColumnIndexFromLabel(columnName)
        if colIndex < 0 or colIndex >= len(columns):
            raise HTTPException(
                status_code=404,
                detail=f"Column '{columnName}' not found in table '{tableName}'",
            )

        # Decide which row index to use in objMgr.getRows
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
            # Legacy behaviour: logical id treated as 1-based index
            idx0 = rowIdInt - 1

        # Fetch the corresponding row
        rows = objMgr.getRows(tableName, idx0, 1) or []
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"Row index {idx0} not found in table '{tableName}'",
            )

        row = rows[0]
        rowValues = row.getValues()
        if colIndex >= len(rowValues):
            raise HTTPException(
                status_code=404,
                detail=f"Column index {colIndex} out of range for this row",
            )

        rawValue = rowValues[colIndex]
        column = columns[colIndex]
        renderer = column.getRenderer()

        # Ensure renderer behaves like ImageRenderer
        if hasattr(renderer, "setSize"):
            renderer.setSize(size)
        if hasattr(renderer, "setApplyTransformation"):
            renderer.setApplyTransformation(applyTransform)

        try:
            img = renderer.render(rawValue, rowValues)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Cannot render image cell: {e}",
            )

        if img is None:
            raise HTTPException(status_code=404, detail="No image for this cell")

        # If renderer returns ndarray, convert to PIL.Image
        if isinstance(img, np.ndarray):
            if img.ndim == 2:
                mode = "L"
            elif img.ndim == 3 and img.shape[-1] == 3:
                mode = "RGB"
            else:
                mode = "L"
            img = PILImage.fromarray(img, mode=mode)

        if not hasattr(img, "save"):
            raise HTTPException(
                status_code=500,
                detail="Renderer did not return a PIL image",
            )

        try:
            img.thumbnail((size, size))
            # Normalize image
            arr = np.array(img)
            iMax = arr.max()
            iMin = arr.min()
            im255 = ((arr - iMin) / (iMax - iMin) * 255).astype(np.uint8)
            img = PILImage.fromarray(im255, mode="L")

        except Exception:
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

        img.save(buf, format=pilFormat)

        disp = "inline" if inline else "attachment"
        # For backwards compat, include the logical id if present; else fall back to 1-based index
        filenameId = rowId if rowId is not None else (idx0 + 1)
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
        - Each returned row uses `id` as the 0-based row index (stable for the viewer),
          and also exposes `rowId` with the logical DAO id (which may be sparse).
        """
        objMgr, table = self._openMetadataTable(protocolId, outputName, tableName)
        columns = list(table.getColumns())

        # Normalize offset/limit
        offset = max(0, int(offset or 0))
        limit = max(1, int(limit or 1))

        # Total rows
        try:
            totalRows = objMgr.getTableRowCount(tableName) or 0
        except Exception:
            totalRows = 0

        if totalRows <= 0:
            rows = []
        else:
            # Selection-only mode: map offset/limit over selection ids
            if selectionOnly:
                rows = []
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
                        rows = []
                except Exception:
                    rows = []
            else:
                # Normal case: offset + limit sobre la tabla completa
                if offset >= totalRows:
                    rows = []
                else:
                    rows = objMgr.getRows(tableName, offset, limit) or []

        resultRows = []
        for local_index, row in enumerate(rows):
            try:
                logical_id = row.getId()
            except Exception:
                logical_id = None
            rowValues = row.getValues()

            valuesPayload = []
            for idx, rawVal in enumerate(rowValues):
                if idx >= len(columns):
                    break
                col = columns[idx]
                renderer = col.getRenderer()
                cell = self._convertCellForPage(renderer, rawVal, rowValues)
                valuesPayload.append(cell)

            global_index = offset + local_index

            resultRows.append({
                # 0-based row index for the viewer (used to request images).
                "id": global_index,
                "index": global_index,
                # Logical DAO id (may be non-consecutive); kept for future selection/export logic.
                "rowId": logical_id,
                "values": valuesPayload,
            })

        return {
            "offset": offset,
            "limit": limit,
            "totalRows": int(totalRows),
            "rows": resultRows,
        }

