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

logger = logging.getLogger(__name__)

import os
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Any
from fastapi import HTTPException, status
import pyworkflow
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from pyworkflow import Config
from pyworkflow.project import Manager, Project as ScipionProject
from pyworkflow.protocol.params import (IntParam, FloatParam, BooleanParam, StringParam, EnumParam, PointerParam,
                                        MultiPointerParam, RelationParam, MODE_RESTART)
import pyworkflow.utils as pwutils
from pyworkflow.utils import HYPER_BOLD, HYPER_ITALIC, HYPER_LINK1, HYPER_LINK2, parseHyperText
from app.backend.api.schemas.project_schema import ProjectCreate


from app.backend.models.project_model import ProjectUpdateRequest
from app.utils.scipion_helper import serializeToJson


class ProjectService:
    def __init__(self):
        self.manager = Manager()
        self.currentProject = None

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

        self.manager.deleteProject(path)

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
                    input[key]['_class'] = attr.get().getClassName() if attr.get() else ""
                    try:
                        input[key]['info'] = str(attr.get())
                    except Exception as e:
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
            "new": "#D9F1FA",
        }
        return status_colors.get(status.lower(), "#9e9e9e")

    def _buildProtocolContext(self, projectId, protocol) -> dict:
        """
        Build the common context dictionary for a protocol,
        including inputs, outputs, definition, status, color, logos, etc.
        """
        from pyworkflow.protocol import Line, Group

        HEADER_PARAMS = ['runName',  '_objComment', '_useQueue', '_prerequisites', 'gpuList', 'runMode']
        # Basic metadata
        package = protocol.getClassPackage()
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
            "ScheduleLog": protocol.getScheduleLog(),

        }

        # Detect available wizards and viewers
        wizards = self.findWizardsWeb(protocol)
        # viewers = findViewersWeb(protocol)

        # Inputs
        inputs = []
        for key, attr in protocol.iterInputAttributes():
            inp = {key: {}}
            inp[key]['_class'] = attr.get().getClassName()
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
                    else:
                        param = protocol.getParam(paramName)
                        if param is not None:
                            if paramName == 'gpuList':
                                param.label.set('GPU IDs')
                                param.condition.set(None)
                            elif paramName == 'runMode':
                                param.choices = ['continue', 'restart']
                            paramProcessed = self.PreprocessParamForm(param, paramName, wizards, None, 0, None)
                            if paramProcessed:
                                if paramName == 'runName':
                                    paramProcessed[paramName]['_objValue'] = protName
                                    paramProcessed[paramName]['default'] = protName
                                sectionData["params"].append(paramProcessed)

            paramsData.append(sectionData)

        context["definition"] = paramsData
        return context

    def getNewProtocolParams(self, protocolClassName: str) -> dict:
        """
        Returns the parameters of a new protocol given its class name.
        """
        protClass = self.currentProject.getDomain().getProtocols().get(protocolClassName)
        if protClass:
            protocol = self.currentProject.newProtocol(protClass)
            return self._buildProtocolContext(protocol)
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
        for key, value in params.items():
            param = protocol.getParam(key)
            if param is None:
                continue

            if isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
                parentId = value.get("_parentId")
                rawValue = value.get("value")

                if parentId:
                    try:
                        parentProtocol = self.currentProject.getProtocol(int(parentId))
                        param.set(value['value'])
                        protocol.setAttributeValue(key, parentProtocol)
                        param.default.set(value['value'])
                        pointer = getattr(protocol, key)
                        pointer.setExtended(value['value'].split('.')[-1])

                        logger.info(f"[INFO] Pointer param {key} set from parent {parentId} output {rawValue}")
                    except Exception as e:
                        logger.error(f"[ERROR] Could not set pointer for {key}: {e}")
                else:
                    # Pointer sin parentId, fallback
                    param.set(None)

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
            castedValue = self.castParamValue(param, rawValue)
            param.set(castedValue)
            protocol.setAttributeValue(key, castedValue)
            logger.info(f"[INFO] Set param {key} = {castedValue}")

        # Apply pointer parameters
        self.applyParamsToProtocol(protocol, params)

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

        return protocol

    def launchProtocol(self, mapper, protocolId, protocolClassName, params):
        """Launch a protocol in RESTART mode, applying all params."""

        # Store & launch
        protocol = self.saveProtocol(mapper, protocolId, protocolClassName, params, setToSave=False)
        self.currentProject.launchProtocol(protocol)

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
                            valueList.append({'object': value, 'info': '---'})
                            defaultValueList.append({'object': value, 'info': '---'})
                        context[paramName]['_objValue'] = valueList
                        context[paramName]['default'] = defaultValueList
                    elif isinstance(param, PointerParam):
                        # TODO CHECK THIS LATER to display better when no _extended attribute
                        pointerValue = "%s.%s" % (protVar.getObjValue(), protVar.getExtended()) if protVar.getExtended() else ''
                        context[paramName]['_objValue'] = pointerValue
                        context[paramName]['default'] = context[paramName]['_objValue']
                    else:
                        context[paramName]['_objValue'] = protVar.get() if protVar.get() is not None else ""
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

    def getProtocolLogs(self, projectId: int, protocolId: int, offset: int = 0):
        protocol = self.getProtocolParams(projectId, protocolId)
        logPath = protocol.get("stdoutLog")
        errLogPath = protocol.get("stderrLog")

        stdout_content, stderr_content = "", ""
        new_offset_out, new_offset_err = offset, offset

        # Handle stdout log
        if logPath and os.path.exists(logPath):
            with open(logPath, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(offset)
                stdout_content = f.read()
                new_offset_out = f.tell()

        # Handle stderr log
        if errLogPath and os.path.exists(errLogPath):
            with open(errLogPath, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(offset)
                stderr_content = f.read()
                new_offset_err = f.tell()

        # Si no existe ninguno de los dos, devolvemos 404
        if not stdout_content and not stderr_content and not (
                logPath and os.path.exists(logPath)
        ) and not (errLogPath and os.path.exists(errLogPath)):
            raise HTTPException(status_code=404, detail="No logs found")

        return {
            "stdoutLog": stdout_content,
            "stderrLog": stderr_content,
            "stdoutOffset": new_offset_out,
            "stderrOffset": new_offset_err,
        }

