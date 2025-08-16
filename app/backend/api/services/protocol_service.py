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
from pyworkflow.project import Manager
from .project_service import ProjectService


class ProtocolService:
    """Service class to manage protocols operations"""

    def __init__(self):
        self.projectList = {}
        self.currentId = 1
        self.manager = Manager()

    def getProtocolParams(self, projectId, protocolName):
        """Return the protocol parameters and types"""
        projectService = ProjectService()
        project = projectService.getCurrentProject()
        print(project)
        protocol = project.getProtocol(protocolName)
        print(protocol)
        return {'id': 'Pepe',
                'parents': [],
                'children': [],
                'label': 'Pepe',
                'status': 'running',
                'color': 'red',
                'parameters': []}
