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
from types import SimpleNamespace

from app.backend.api.services.protocol_relation_service import (
    ProtocolRelationService,
)


class FakeRelationParam:
    def getName(self):
        return "relation_ctf"

    def getAttributeName(self):
        return "getInputMicrographs"

    def getDirection(self):
        return 1


class FakePointedObject:
    def __init__(
            self,
            objId,
    ):
        self.objId = objId

    def getObjId(self):
        return self.objId


class FakePointer:
    def __init__(
            self,
            objId,
            extended="",
    ):
        self.obj = FakePointedObject(
            objId
        )
        self.extended = extended

    def getObjValue(self):
        return self.obj

    def getExtended(self):
        return self.extended


class FakeProtocol:
    def __init__(
            self,
            relationParam,
            sourceObject,
    ):
        self.relationParam = (
            relationParam
        )
        self.sourceObject = (
            sourceObject
        )

    def getParam(
            self,
            name,
    ):
        if name == "ctfRelations":
            return self.relationParam

        return None

    def getAttributeValue(
            self,
            name,
    ):
        assert (
            name
            == "getInputMicrographs"
        )

        return self.sourceObject


class FakeProject:
    def __init__(
            self,
            relatedPointers,
    ):
        self.relatedPointers = (
            relatedPointers
        )
        self.calls = []

    def getRelatedObjects(
            self,
            relationName,
            sourceObject,
            direction,
    ):
        self.calls.append({
            "relationName":
                relationName,
            "sourceObject":
                sourceObject,
            "direction":
                direction,
        })

        return self.relatedPointers


class FakeMapper:
    def __init__(self):
        self.protocolRows = {}

    def getProjectProtocolByProtocolId(
            self,
            projectId,
            protocolId,
    ):
        return self.protocolRows.get(
            (
                projectId,
                protocolId,
            )
        )


class FakeProjectService:
    def __init__(
            self,
            project,
    ):
        self.currentProject = project

    def loadPostgresqlRuntimeProjectForMutation(
            self,
            mapper,
            projectId,
            currentUser,
    ):
        return {
            "id": projectId,
        }


def test_ResolveRelationCandidatesUsesScipionRelations(
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.api.services.protocol_relation_service"
    )

    monkeypatch.setattr(
        module,
        "RelationParam",
        FakeRelationParam,
    )

    sourceObject = object()

    project = FakeProject([
        FakePointer(
            9001
        ),
        FakePointer(
            44,
            "outputCTF",
        ),
        FakePointer(
            9001
        ),
    ])

    projectService = (
        FakeProjectService(
            project
        )
    )

    mapper = FakeMapper()

    mapper.protocolRows[
        (
            7,
            44,
        )
    ] = {
        "protocolId": "44",
    }

    service = (
        ProtocolRelationService(
            currentProject=project,
            projectService=(
                projectService
            ),
        )
    )

    protocol = FakeProtocol(
        FakeRelationParam(),
        sourceObject,
    )

    monkeypatch.setattr(
        service,
        "_buildRelationReadyProtocol",
        lambda **kwargs: protocol,
    )

    class FakeRepository:
        def getPersistedOutputObjectByRuntimeId(
                self,
                mapper,
                projectId,
                runtimeObjectId,
                extended=None,
        ):
            if runtimeObjectId == 9001:
                return {
                    "protocolId": 21,
                    "outputName":
                        "outputCTF",
                }

            return None

    monkeypatch.setattr(
        module,
        "ProtocolGraphRepository",
        FakeRepository,
    )

    result = (
        service
        .resolveRelationCandidates(
            mapper=mapper,
            projectId=7,
            currentUser={
                "id": 3,
            },
            protocolClassName=(
                "XmippProtExtractParticles"
            ),
            paramName=(
                "ctfRelations"
            ),
            formValues={
                "inputCoordinates":
                    "12.outputCoordinates",
            },
        )
    )

    assert result == {
        "paramName":
            "ctfRelations",
        "relationName":
            "relation_ctf",
        "values": [
            "21.outputCTF",
            "44.outputCTF",
        ],
    }

    assert project.calls == [{
        "relationName":
            "relation_ctf",
        "sourceObject":
            sourceObject,
        "direction":
            1,
    }]


def test_ResolveRelationCandidatesReturnsEmptyWithoutSource(
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.api.services.protocol_relation_service"
    )

    monkeypatch.setattr(
        module,
        "RelationParam",
        FakeRelationParam,
    )

    project = FakeProject([])

    projectService = (
        FakeProjectService(
            project
        )
    )

    service = (
        ProtocolRelationService(
            currentProject=project,
            projectService=(
                projectService
            ),
        )
    )

    protocol = FakeProtocol(
        FakeRelationParam(),
        None,
    )

    monkeypatch.setattr(
        service,
        "_buildRelationReadyProtocol",
        lambda **kwargs: protocol,
    )

    result = (
        service
        .resolveRelationCandidates(
            mapper=FakeMapper(),
            projectId=7,
            currentUser={
                "id": 3,
            },
            protocolClassName=(
                "XmippProtExtractParticles"
            ),
            paramName=(
                "ctfRelations"
            ),
            formValues={},
        )
    )

    assert result == {
        "paramName":
            "ctfRelations",
        "relationName":
            "relation_ctf",
        "values": [],
    }

    assert project.calls == []


