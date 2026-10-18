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


def test_the_wizard_route_runs_the_wizard_for_the_signed_in_user(authTestEnv, monkeypatch):
    projectRouterModule = importlib.import_module(
        "app.backend.api.routers.project_router"
    )
    calls = []

    def runProtocolWizard(**kwargs):
        calls.append(kwargs)
        return {"status": "done", "paramUpdates": {"boxSize": 128}, "messages": []}

    monkeypatch.setattr(projectRouterModule, "runProtocolWizard", runProtocolWizard)
    mapper, payload, currentUser = object(), object(), {"id": 7}

    result = projectRouterModule.runProtocolWizardRoute(
        projectId=11, payload=payload, currentUser=currentUser, mapper=mapper)

    assert result["paramUpdates"] == {"boxSize": 128}
    assert calls == [{"mapper": mapper, "currentUser": currentUser, "projectId": 11, "payload": payload}]
