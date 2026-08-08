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
import inspect

import app.backend.runtime.pointer_resolver as pointerResolverModule
from app.backend.runtime.pointer_resolver import RuntimePointerResolver


class MapperStub:
    def __init__(self):
        self.db = object()


class ProtocolStub:
    def getObjId(self):
        return 19


def test_CompletePointerValuesDelegatesInputRefRead(monkeypatch):
    mapper = MapperStub()
    resolver = RuntimePointerResolver()
    repositoryCalls = []

    class ProtocolIdentityResolverStub:
        def __init__(self, mapper, projectId):
            assert mapper is not None
            assert projectId == 7

        def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
            assert protocolId == 19
            return 31

    class ProtocolGraphRepositoryStub:
        def loadInputRefPointerValues(
                self,
                mapper,
                projectId,
                protocolDbId,
                inputName,
        ):
            repositoryCalls.append({
                "mapper": mapper,
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "inputName": inputName,
            })

            return [
                "17.outputParticles",
                "22.outputParticles",
                "23.outputVolume",
            ]

    monkeypatch.setattr(
        pointerResolverModule,
        "ProtocolIdentityResolver",
        ProtocolIdentityResolverStub,
    )

    monkeypatch.setattr(
        pointerResolverModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    result = resolver.completePointerValuesFromInputRefs(
        mapper=mapper,
        projectId=7,
        protocol=ProtocolStub(),
        inputName="inputObjects",
        rawValue=[
            "outputParticles",
            "outputVolume",
            "19.alreadyComplete",
        ],
    )

    assert result == [
        "19.alreadyComplete",
        "outputParticles",
        "23.outputVolume",
    ]

    assert repositoryCalls == [
        {
            "mapper": mapper,
            "projectId": 7,
            "protocolDbId": 31,
            "inputName": "inputObjects",
        },
    ]

    source = inspect.getsource(
        RuntimePointerResolver.completePointerValuesFromInputRefs
    )

    assert "protocolGraphRepository.loadInputRefPointerValues(" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_ResolvePointerTargetUsesStrictResolvedScipionProtocolIdentity(
        monkeypatch,
):
    resolver = RuntimePointerResolver()
    parentProtocol = object()
    parentProtocolCalls = []
    outputCalls = []

    class ProtocolIdentityResolverStub:
        def __init__(self, mapper, projectId):
            assert mapper is not None
            assert projectId == 7

        def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
            assert protocolId == 19
            return 31

        def resolvePostgresqlProtocolDbId(self, protocolId):
            raise AssertionError(
                "Resolved Scipion protocol ids must not use the dual PostgreSQL resolver"
            )

    monkeypatch.setattr(
        pointerResolverModule,
        "ProtocolIdentityResolver",
        ProtocolIdentityResolverStub,
    )

    def getParentProtocol(
            mapper,
            projectId,
            parentId,
    ):
        parentProtocolCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "parentId": parentId,
        })

        return 19, parentProtocol

    def resolveParentOutput(**kwargs):
        outputCalls.append(kwargs)

        return {
            "exists": True,
        }

    mapper = object()

    result = resolver.resolvePointerTarget(
        mapper=mapper,
        projectId=7,
        pointerValue="500.outputParticles",
        paramLabel="Input particles",
        getParentProtocolCallback=getParentProtocol,
        resolveParentOutputCallback=resolveParentOutput,
    )

    assert result["ok"] is True
    assert result["parentId"] == "500"
    assert result["parentScipionProtocolId"] == 19
    assert result["parentProtocolDbId"] == 31
    assert result["parentProtocol"] is parentProtocol
    assert result["outputName"] == "outputParticles"

    assert parentProtocolCalls == [
        {
            "mapper": mapper,
            "projectId": 7,
            "parentId": "500",
        },
    ]

    assert len(outputCalls) == 1
    assert outputCalls[0]["parentProtocolDbId"] == 31
    assert outputCalls[0]["parentScipionProtocolId"] == 19


def test_BuildInputRefsUsesStrictResolvedScipionProtocolIdentity(
        monkeypatch,
):
    resolver = RuntimePointerResolver()
    identityCalls = []

    class PointerParamStub:
        pass

    class ProtocolIdentityResolverStub:
        def __init__(self, mapper, projectId):
            assert mapper is not None
            assert projectId == 7

        def resolveScipionProtocolId(self, protocolId):
            identityCalls.append({
                "method": "resolveScipionProtocolId",
                "protocolId": protocolId,
            })

            assert protocolId == "500"
            return 19

        def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
            identityCalls.append({
                "method": "resolvePostgresqlProtocolDbIdFromScipionProtocolId",
                "protocolId": protocolId,
            })

            assert protocolId == 19
            return 31

        def resolvePostgresqlProtocolDbId(self, protocolId):
            raise AssertionError(
                "Resolved Scipion protocol ids must not use the dual PostgreSQL resolver"
            )

    class ProtocolGraphRepositoryStub:
        def getPersistedOutputInfoForInputRef(
                self,
                mapper,
                projectId,
                parentProtocolDbId,
                outputName,
        ):
            assert projectId == 7
            assert parentProtocolDbId == 31
            assert outputName == "outputParticles"

            return {
                "className": "SetOfParticles",
                "runtimeObjectId": 91,
            }

    monkeypatch.setattr(
        pointerResolverModule,
        "ProtocolIdentityResolver",
        ProtocolIdentityResolverStub,
    )

    monkeypatch.setattr(
        pointerResolverModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    result = resolver.buildInputRefsFromPointerParams(
        mapper=object(),
        projectId=7,
        protocolDbId=41,
        protocolId=29,
        params={
            "inputParticles": "500.outputParticles",
        },
        getParamCallback=lambda inputName: PointerParamStub(),
        isPointerParamCallback=lambda param: True,
    )

    assert result["parentProtocolDbIds"] == [31]
    assert result["parentProtocolIds"] == [19]

    assert result["inputRefs"] == [
        {
            "projectId": 7,
            "protocolDbId": 41,
            "protocolId": "29",
            "inputName": "inputParticles",
            "itemIndex": 0,
            "parentProtocolDbId": 31,
            "parentProtocolId": "19",
            "parentOutputName": "outputParticles",
            "objectClassName": "SetOfParticles",
            "objectId": 91,
        },
    ]

    assert identityCalls == [
        {
            "method": "resolveScipionProtocolId",
            "protocolId": "500",
        },
        {
            "method": "resolvePostgresqlProtocolDbIdFromScipionProtocolId",
            "protocolId": 19,
        },
    ]


def test_LoadInputRefsByInputNameDelegatesRepositoryRows(monkeypatch):
    mapper = MapperStub()
    resolver = RuntimePointerResolver()
    repositoryCalls = []

    class ProtocolGraphRepositoryStub:
        def loadInputRefsForProtocolCopy(
                self,
                mapper,
                projectId,
                protocolDbId,
        ):
            repositoryCalls.append({
                "mapper": mapper,
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return [
                {
                    "inputName": "inputVolume",
                    "itemIndex": 0,
                    "parentProtocolDbId": 23,
                    "parentProtocolId": "17",
                    "parentOutputName": "outputVolume",
                    "objectClassName": "Volume",
                    "objectId": "91",
                },
                {
                    "inputName": "inputParticles",
                    "itemIndex": 0,
                    "parentProtocolDbId": 24,
                    "parentProtocolId": "18",
                    "parentOutputName": "outputParticles",
                    "objectClassName": "SetOfParticles",
                    "objectId": "92",
                },
                {
                    "inputName": "inputParticles",
                    "itemIndex": 1,
                    "parentProtocolDbId": 25,
                    "parentProtocolId": "19",
                    "parentOutputName": "outputParticles",
                    "objectClassName": "SetOfParticles",
                    "objectId": "93",
                },
                {
                    "inputName": "",
                    "itemIndex": 2,
                    "parentProtocolId": "20",
                    "parentOutputName": "ignoredOutput",
                },
                {
                    "inputName": "invalidInput",
                    "itemIndex": 3,
                    "parentProtocolId": None,
                    "parentOutputName": "ignoredOutput",
                },
            ]

    monkeypatch.setattr(
        pointerResolverModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    result = resolver.loadInputRefsByInputName(
        mapper=mapper,
        projectId=7,
        protocolDbId=31,
    )

    assert list(result) == [
        "inputVolume",
        "inputParticles",
    ]

    assert len(result["inputVolume"]) == 1
    assert len(result["inputParticles"]) == 2

    assert result["inputVolume"][0]["parentProtocolId"] == "17"
    assert result["inputParticles"][0]["parentProtocolId"] == "18"
    assert result["inputParticles"][1]["parentProtocolId"] == "19"

    assert repositoryCalls == [
        {
            "mapper": mapper,
            "projectId": 7,
            "protocolDbId": 31,
        },
    ]

    source = inspect.getsource(
        RuntimePointerResolver.loadInputRefsByInputName
    )

    assert "protocolGraphRepository.loadInputRefsForProtocolCopy(" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source