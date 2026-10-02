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

def test_BuildRelationReadyProtocolHandlesScalarPointerPayloadsBeforeCasting(
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.api.services.protocol_relation_service"
    )

    class LabelStub:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    class ScalarParamStub:
        allowsPointers = True

        def __init__(self, name, label):
            self.name = name
            self.label = LabelStub(label)
            self.values = []

        def validate(self, value):
            return []

        def set(self, value):
            self.values.append(value)

    pointerParam = ScalarParamStub(
        "boxSize",
        "Particle box size (px)",
    )

    literalParam = ScalarParamStub(
        "resizeSamplingRate",
        "Resize sampling rate",
    )

    class ProtocolStub:
        def __init__(self):
            self.params = {
                "boxSize": pointerParam,
                "resizeSamplingRate": literalParam,
            }
            self.attributes = {}

        def getParam(self, name):
            return self.params.get(name)

        def setAttributeValue(self, name, value):
            self.attributes[name] = value

    protocol = ProtocolStub()
    protocolClass = object()

    class DomainStub:
        def getProtocols(self):
            return {
                "ExampleProtocol": protocolClass,
            }

    class ProjectStub:
        def getDomain(self):
            return DomainStub()

        def newProtocol(self, receivedClass):
            assert receivedClass is protocolClass
            return protocol

        def _fixProtParamsConfiguration(self, receivedProtocol):
            assert receivedProtocol is protocol

    class ProjectServiceStub:
        def __init__(self):
            self.pointerCalls = []

        def applyParamsToProtocol(
                self,
                mapper,
                projectId,
                protocol,
                params,
        ):
            self.pointerCalls.append({
                "mapper": mapper,
                "projectId": projectId,
                "protocol": protocol,
                "params": params,
            })
            return []

    casts = []

    def fakeCastProtocolParamValue(param, value):
        if isinstance(value, dict):
            raise TypeError(
                "scalar pointer payload must be normalized before casting"
            )

        casts.append(
            (
                param.name,
                value,
            )
        )

        if param is literalParam:
            return float(value)

        return value

    monkeypatch.setattr(
        module,
        "castProtocolParamValue",
        fakeCastProtocolParamValue,
    )

    projectService = ProjectServiceStub()

    service = ProtocolRelationService(
        currentProject=ProjectStub(),
        projectService=projectService,
    )

    mapper = object()

    result = service._buildRelationReadyProtocol(
        protocolClassName="ExampleProtocol",
        formValues={
            "boxSize": {
                "pointerMode": True,
                "value": "2852.boxSizeExtraction",
            },
            "resizeSamplingRate": {
                "pointerMode": False,
                "value": "1.25",
            },
        },
        mapper=mapper,
        projectId=7,
    )

    assert result is protocol

    assert casts == [
        (
            "resizeSamplingRate",
            "1.25",
        ),
    ]

    assert protocol.attributes == {
        "resizeSamplingRate": 1.25,
    }

    assert len(projectService.pointerCalls) == 1
    assert projectService.pointerCalls[0]["mapper"] is mapper
    assert projectService.pointerCalls[0]["projectId"] == 7
    assert projectService.pointerCalls[0]["protocol"] is protocol
    assert projectService.pointerCalls[0]["params"] == {
        "boxSize": {
            "pointerMode": True,
            "value": "2852.boxSizeExtraction",
        },
        "resizeSamplingRate": {
            "pointerMode": False,
            "value": "1.25",
        },
    }

def test_BuildRelationReadyProtocolDoesNotBlockOnPointerApplicationErrors(
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.api.services.protocol_relation_service"
    )

    class LabelStub:
        def get(self):
            return "Some scalar"

    class ScalarParamStub:
        allowsPointers = False
        label = LabelStub()

        def validate(self, value):
            return []

        def set(self, value):
            self.value = value

    scalarParam = ScalarParamStub()

    class ProtocolStub:
        def __init__(self):
            self.scalar = None

        def getParam(self, name):
            if name == "someScalar":
                return scalarParam

            return None

        def setAttributeValue(self, name, value):
            setattr(self, name, value)

    protocol = ProtocolStub()
    protocolClass = object()

    class DomainStub:
        def getProtocols(self):
            return {
                "ExampleProtocol": protocolClass,
            }

    class ProjectStub:
        def getDomain(self):
            return DomainStub()

        def newProtocol(self, receivedClass):
            assert receivedClass is protocolClass
            return protocol

        def _fixProtParamsConfiguration(self, receivedProtocol):
            assert receivedProtocol is protocol

    pointerErrors = [
        (
            "**Particle box size (px)** parent protocol 2852 "
            "does not have output boxSizeExtraction "
            "in PostgreSQL or runtime."
        ),
    ]

    class ProjectServiceStub:
        def applyParamsToProtocol(
                self,
                mapper,
                projectId,
                protocol,
                params,
        ):
            return list(pointerErrors)

    monkeypatch.setattr(
        module,
        "castProtocolParamValue",
        lambda param, value: int(value),
    )

    service = ProtocolRelationService(
        currentProject=ProjectStub(),
        projectService=ProjectServiceStub(),
    )

    result = service._buildRelationReadyProtocol(
        protocolClassName="ExampleProtocol",
        formValues={
            "someScalar": "3",
            "boxSize": {
                "pointerMode": True,
                "value": "2852.boxSizeExtraction",
            },
        },
        mapper=object(),
        projectId=7,
    )

    assert result is protocol
    assert protocol.someScalar == 3

def test_ResolveRelationCandidatesUsesDirectPostgresqlRelationWhenNativeGraphIsEmpty(
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

    sourceObject = FakePointedObject(
        1005762
    )

    project = FakeProject([])

    projectService = FakeProjectService(
        project
    )

    mapper = FakeMapper()

    service = ProtocolRelationService(
        currentProject=project,
        projectService=projectService,
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
            assert projectId == 7
            assert runtimeObjectId == 1005762

            return {
                "protocolDbId": 5035,
                "protocolId": "2640",
                "runtimeObjectId": 1005762,
                "outputName": "outputMicrographs",
                "className": "SetOfMicrographs",
            }

        def loadRuntimeOutputRelations(
                self,
                mapper,
                projectId,
                sourceProtocolDbId,
                sourceOutputName,
        ):
            assert projectId == 7
            assert sourceProtocolDbId == 5035
            assert sourceOutputName == "outputMicrographs"

            return [
                {
                    "relationId": 3415,
                    "relationName": "relation_ctf",
                    "sourceProtocolId": "2640",
                    "sourcePersistedOutputName":
                        "outputMicrographs",
                    "targetProtocolId": "2640",
                    "targetPersistedOutputName":
                        "outputCTF",
                    "targetClassName":
                        "SetOfCTF",
                },
                {
                    "relationId": 3416,
                    "relationName":
                        "relation_datasource",
                    "sourceProtocolId": "2640",
                    "sourcePersistedOutputName":
                        "outputMicrographs",
                    "targetProtocolId": "2640",
                    "targetPersistedOutputName":
                        "outputCTF",
                    "targetClassName":
                        "SetOfCTF",
                },
            ]

    monkeypatch.setattr(
        module,
        "ProtocolGraphRepository",
        FakeRepository,
    )

    result = service.resolveRelationCandidates(
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
                "3170.outputCoordinates_Full",
        },
    )

    assert result == {
        "paramName":
            "ctfRelations",
        "relationName":
            "relation_ctf",
        "values": [
            "2640.outputCTF",
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
