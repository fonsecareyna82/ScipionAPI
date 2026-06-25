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


class FakeDb:
    def __init__(self):
        self.fetchOneCalls = []


class FakeMapper:
    def __init__(self):
        self.db = FakeDb()


def test_ResolveAnalyzeViewerDecisionReturnsHandledFalse(authTestEnv):
    module = importlib.import_module("app.backend.api.services.project_service")
    service = module.ProjectService()
    mapper = FakeMapper()

    result = service.resolveAnalyzeViewerDecision(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        ctx={
            "outputName": "outputVolume",
            "pointerClass": "Volume",
            "paramClass": "PointerParam",
        },
    )

    assert result == {"handled": False}
    assert mapper.db.fetchOneCalls == []


def test_ResolveAnalyzeViewerDecisionDoesNotResolveRuntimeObjects(authTestEnv):
    module = importlib.import_module("app.backend.api.services.project_service")
    service = module.ProjectService()
    mapper = FakeMapper()

    result = service.resolveAnalyzeViewerDecision(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        ctx={
            "outputName": "outputCustom",
            "pointerClass": "UnknownExternalObject",
            "paramClass": "PointerParam",
        },
    )

    assert result == {"handled": False}
    assert mapper.db.fetchOneCalls == []