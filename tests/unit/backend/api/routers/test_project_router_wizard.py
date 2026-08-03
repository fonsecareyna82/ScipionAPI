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
import importlib


class FakeProjectService:
    def __init__(self):
        self.executeProtocolWizardCalls = []

    def getProjectById(self, *args, **kwargs):
        raise AssertionError("Wizard router must not load the legacy Scipion project")

    def executeProtocolWizard(
            self,
            mapper,
            projectId,
            currentUser,
            payload,
    ):
        self.executeProtocolWizardCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "payload": payload,
        })

        return {
            "success": True,
            "wizardId": "tests.FakeWizard",
            "kind": "compute",
            "paramUpdates": {
                "boxSize": 128,
            },
            "message": "Wizard executed successfully",
        }


def test_ExecuteProtocolWizardRouteDelegatesWithoutLegacyProjectLoad(authTestEnv):
    projectRouterModule = importlib.import_module(
        "app.backend.api.routers.project_router"
    )

    mapper = object()
    payload = object()
    currentUser = {"id": 7}
    service = FakeProjectService()

    result = projectRouterModule.executeProtocolWizardRoute(
        projectId=11,
        payload=payload,
        currentUser=currentUser,
        mapper=mapper,
        service=service,
    )

    assert result == {
        "success": True,
        "wizardId": "tests.FakeWizard",
        "kind": "compute",
        "paramUpdates": {
            "boxSize": 128,
        },
        "message": "Wizard executed successfully",
    }

    assert service.executeProtocolWizardCalls == [
        {
            "mapper": mapper,
            "projectId": 11,
            "currentUser": currentUser,
            "payload": payload,
        }
    ]