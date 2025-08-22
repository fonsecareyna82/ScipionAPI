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

import os
import subprocess
from typing import List, Any
from datetime import datetime
from pathlib import Path

import pyworkflow
from pyworkflow.project import Manager, Project
from pyworkflow.protocol import MODE_RESTART
from pyworkflow.utils import HYPER_BOLD, HYPER_ITALIC, HYPER_LINK1, HYPER_LINK2, parseHyperText

from app.backend.models.project_model import ProjectCreateRequest, ProjectUpdateRequest
from app.utils.scipion_helper import serializeToJson


class ProjectService:
    """Service class to manage project operations"""

    def __init__(self):
        """Initialize manager, in-memory store and preload projects."""
        self.projectList = {}
        self.currentId = 1
        self.manager = Manager()
        self.currentProject = None
        self.loadProjects()

    def getProjectList(self):
        """Return the in-memory project index."""
        return self.projectList

    def getCurrentProject(self):
        """Return the currently loaded Scipion project."""
        return self.currentProject

    def createProject(self, project: ProjectCreateRequest) -> dict:
        """Register a new project in memory."""
        project_id = self.currentId
        self.currentId += 1

        self.projectList[project_id] = {
            "id": project_id,
            "name": project.name,
            "description": project.description,
            "created_at": datetime.now(),
            "status": "created",
            "protocolsCount": project.protocols,
            "diskUsage": project.diskUsage
        }
        return self.projectList[project_id]

    def listProjects(self) -> List[dict]:
        """Return all stored projects as a list."""
        return list(self.projectList.values())

    def deleteProject(self, project_id: int) -> dict:
        """Remove a project by its in-memory ID."""
        if project_id not in self.projectList:
            raise ValueError("Project not found")
        del self.projectList[project_id]
        return {"message": "Project deleted successfully"}

    def updateProject(self, project_id: int, updated: ProjectUpdateRequest) -> dict:
        """Update name and description of an existing project."""
        if project_id not in self.projectList:
            raise ValueError("Project not found")
        project = self.projectList[project_id]
        project["name"] = updated.name
        project["description"] = updated.description
        return project

    @staticmethod
    def getProjectSize(path: Path) -> int:
        """Compute total folder size in bytes without subprocess."""
        result = subprocess.run(["du", "-sb", path], stdout=subprocess.PIPE, text=True)
        return int(result.stdout.split()[0])

    @staticmethod
    def countProtocols(path: str) -> int:
        """Count subdirectories under the 'Runs' folder."""
        return sum(1 for entry in Path(path).iterdir() if entry.is_dir())

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
            if nodeId != 'PROJECT':
                protocol = self.currentProject.getProtocol(int(nodeId))
                self.currentProject._fixProtParamsConfiguration(protocol)

                # Iterate over the inputs
                # input = {}
                # for key, attr in protocol.iterInputAttributes():
                #     input.setdefault(key, {})
                #     input[key]['_class'] = attr.__class__.__name__
                #     input[key]['info'] = attr.__str__()
                #     input[key]['_objValue'] = attr.get()
                #     inputs.append(input)

                # Iterate over the outputs
                output = {}
                for key, attr in protocol.iterOutputAttributes():
                    output.setdefault(key, {})
                    output[key]['_class'] = attr.__class__.__name__
                    try:
                        output[key]['info'] = attr.__str__()
                    except Exception as e:
                        output[key]['info'] = ""
                    output[key]['_objValue'] = "%s.%s" % (nodeObj.getLabel(), key)
                    outputs.append(output)

            graphData[nodeId] = {
                "id": nodeId,
                "children": childrenIds,
                "parents": parentIds,
                "label": nodeObj.getLabel(),
                "status": status,
                "parameter": [],
                "inputs": inputs,
                "outputs": outputs
            }
        return graphData

    def loadProject(self, projectId: str) -> Any:
        """
        Load a Scipion project from disk, build its protocol graph,
        and return metadata + graph structure.
        """
        from pyworkflow import Config
        projPath = self.manager.getProjectPath(projectId)
        if os.path.exists(projPath):
            Config.setDomain("pwem")
            Config.getDomain()
            self.currentProject = Project(pyworkflow.Config.getDomain(), projPath)
            self.currentProject.load(dbPath=self.currentProject.getDbPath())
            runs = self.currentProject.getRunsGraph(refresh=True, checkPids=True)
            graphData = self.buildProtocolsGraph(runs)

            return {
                "id": self.currentProject.getName(),
                "name": self.currentProject.getName(),
                "created_at": str(self.currentProject.getCreationTime()),
                "path": projPath,
                "protocols": graphData
            }
        return None

    def loadProjects(self) -> None:
        """Discover on-disk projects and cache their metadata in memory."""
        projects = self.manager.listProjects()
        self.currentProject = None
        for project in projects:
            projectSize = self.getProjectSize(project.path) / (1024 ** 3)
            protocolCount = self.countProtocols(os.path.join(project.path, 'Runs'))
            self.projectList[project.getName()] = {
                "id": project.getName(),
                "name": project.getName(),
                "description": project.getName(),
                "created_at": project.getCreationTime(),
                "status": "created",
                "protocolsCount": f"{protocolCount}",
                "diskUsage": f"Total size: {projectSize:.2f} GB"
            }

    @staticmethod
    def getProtocolColor(status: str) -> str:
        """Return hex color based on protocol status."""
        status_colors = {
            "finished": "#D2F5CB",
            "failed": "#F5CCCB",
            "aborted": "#F5CCCB",
            "running": "#FCCE62",
            "saved": "#D9F1FA",
            "launched": "#FCCE62"
        }
        return status_colors.get(status.lower(), "#9e9e9e")

    def getProtocolParams(self, projectName: str, protocolId: str) -> dict:
        """
        Retrieve protocol parameters, metadata, inputs/outputs,
        and formatted help/citations for a given node ID.
        """
        from pyworkflow.protocol import Line, Group

        SPECIAL_PARAMS = ['numberOfMpi', 'numberOfThreads', 'hostName', 'expertLevel', '_useQueue']
        OBJ_PARAMS = ['runName', 'comment']
        context = {}
        self.loadProject(projectName)
        # Load the selected protocol
        protocol = self.currentProject.getProtocol(int(protocolId))
        protocol.getPlugin()
        hosts = self.currentProject.getHostNames()
        self.currentProject._fixProtParamsConfiguration(protocol)

        # Package logo
        package = protocol.getClassPackage()
        logoPath = ''
        path = getattr(package, '_logo', '')
        if path != '':
            logoPath = self.getResourceLogo(path)  # Logo

        protName = str(protocol)
        status = protocol.getStatus()  # status
        cite = protocol.citations()
        help = protocol.getHelpText()
        label = protocol._label if hasattr(protocol, '_label') else str(protocol)

        context = {
            "id": protocolId,
            "label": label,
            "protocolName": protName,
            "status": status,
            "color": self.getProtocolColor(status),
            "projectName": self.currentProject.getName(),
            "packageLogo": logoPath,
            "protocolId": protocol.getObjId(),
            "hosts": hosts,
            "favicon": self.getResourceIcon('favicon'),
            "cite": cite,
            "help": help
        }

        for paramName in SPECIAL_PARAMS:
            context.setdefault(paramName, {})
            attr = getattr(protocol, paramName, None)
            if attr is not None:
                context[paramName]['_class'] = attr.__class__.__name__
                context[paramName]['_objValue'] = attr.get()


        # Detect available wizards and viewers
        wizards = self.findWizardsWeb(protocol)
        # viewers = findViewersWeb(protocol)

        # Process citations and documentation
        #protocol.htmlCitations = self.parseText(protocol.citations())
        #protocol.htmlDoc = self.parseText(protocol.getDoc())

        visualize = 0
        viewerDict = None

        inputs = []
        outputs = []

        # Iterate over the inputs
        input = {}
        for key, attr in protocol.iterInputAttributes():
            input.setdefault(key, {})
            input[key]['_class'] = attr.__class__.__name__
            try:
                input[key]['info'] = attr.__str__()
            except Exception as e:
                input[key]['info'] = ""
            input[key]['_objValue'] = "%s.%s" % (protName, key)
            inputs.append(input)

        # Iterate over the outputs
        output = {}
        for key, attr in protocol.iterOutputAttributes():
            output.setdefault(key, {})
            output[key]['_class'] = attr.__class__.__name__
            try:
                output[key]['info'] = attr.__str__()
            except Exception as e:
                output[key]['info'] = ""
            output[key]['_objValue'] = "%s.%s" % (protName, key)
            outputs.append(output)

        context['inputs'] = inputs
        context['outputs'] = outputs

        paramsData = []
        for section in protocol._definition.iterSections():
            sectionData = {"name": section.getLabel(), "params": []}
            for paramName, param in section.iterParams():
                protVar = getattr(protocol, paramName, None)
                if protVar is None:
                    # Handle Group and Line special cases
                    if isinstance(param, Group):
                        group = self.PreprocessParamForm(param, paramName, wizards, None, 0, protVar)
                        group[paramName]['children'] = []
                        for paramGroupName, paramGroup in param.iterParams():
                            protVar = getattr(protocol, paramGroupName, None)

                            # LINE PARAM
                            if isinstance(paramGroup, Line):
                                for paramLineName, paramLine in paramGroup.iterParams():
                                    protVar = getattr(protocol, paramLineName, None)

                                    if protVar is None:
                                        pass
                                    else:
                                        paramChild = self.PreprocessParamForm(paramLine, paramLineName, wizards, None, 0,
                                                                             protVar)
                                        if paramChild:
                                            group[paramName]['children'].append(paramChild)

                            elif protVar is None:
                                pass
                            else:
                                paramChild = self.PreprocessParamForm(paramGroup, paramGroupName, wizards, None, 0, protVar)
                                if paramChild:
                                    group[paramName]['children'].append(paramChild)

                        if group:
                            sectionData["params"].append(group)

                        # LINE PARAM
                    if isinstance(param, Line):
                        line = self.PreprocessParamForm(param, paramName, wizards, None, 0, protVar)
                        line[paramName]['children'] = []
                        for paramLineName, paramLine in param.iterParams():
                            protVar = getattr(protocol, paramLineName, None)

                            if protVar is None:
                                pass
                            else:
                                paramChild = self.PreprocessParamForm(paramLine, paramLineName, wizards, None, 0, protVar)
                                if paramChild:
                                    line[paramName]['children'].append(paramChild)

                        if line:
                            sectionData["params"].append(line)

                else:
                    param = self.PreprocessParamForm(param, paramName, wizards, None, 0, protVar)
                    if param:
                        sectionData["params"].append(param)

            paramsData.append(sectionData)

        context["definition"] = paramsData

        return context

    def launchProtocol(self, protocolId, params):
        """Launch a protocol in RESTART mode."""
        protocol = self.currentProject.getProtocol(int(protocolId))
        protocol.runMode.set(MODE_RESTART)
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
                        context[paramName]['_objValue'] = "%s.%s" % (protVar.getObjValue(), protVar.getExtended())
                        context[paramName]['default'] = context[paramName]['_objValue']
                    else:
                        context[paramName]['_objValue'] = protVar.get() if protVar.get() is not None else ""
                        context[paramName]['default'] = str(context[paramName]['_objValue'])

            return context
        except Exception as ex:
            print("ERROR with param: " + paramName)
            raise ex
