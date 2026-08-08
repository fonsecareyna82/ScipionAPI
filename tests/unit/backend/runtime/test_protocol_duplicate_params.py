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
from types import SimpleNamespace

import app.backend.runtime.protocol_duplicate_service as duplicateServiceModule

from app.backend.runtime.protocol_duplicate_service import (
    RuntimeProtocolDuplicateService,
)


class FakeSourceProtocol:
    def getParam(self, key):
        return None


def test_BuildDuplicatedProtocolParamsDropsObjectMetadata():
    params = {
        "object.id": 41,
        "object.label": "Union sets",
        "object.comment": "Original protocol",
        "object.className": "ProtUnionSet",
        "runName": "Union sets",
        "ignoreDuplicates": True,
    }

    result = RuntimeProtocolDuplicateService().buildDuplicatedProtocolParams(
        sourceProtocol=FakeSourceProtocol(),
        sourceParams=params,
    )

    assert result == {
        "runName": "Union sets copy",
        "ignoreDuplicates": True,
    }


def test_LegacyProtocolDuplicationCompatibilityIsRemoved():
    service = RuntimeProtocolDuplicateService()

    assert not hasattr(
        service,
        "duplicateLegacyProtocols",
    )
    assert not hasattr(
        service,
        "detachProtocolOutputsForCopy",
    )
    assert not hasattr(
        service,
        "restoreProtocolOutputsAfterCopy",
    )


def test_DuplicateRuntimeProtocolsUsesStrictScipionProtocolIdentity(
        monkeypatch,
):
    strictCalls = []

    class ProtocolIdentityResolverStub:
        def __init__(self, mapper, projectId):
            assert mapper is not None
            assert projectId == 7

        def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
            strictCalls.append(int(protocolId))

            return {
                19: 101,
                29: 202,
            }.get(int(protocolId))

        def resolvePostgresqlProtocolDbId(self, protocolId):
            raise AssertionError(
                "Known Scipion protocol ids must not use the dual PostgreSQL resolver"
            )

    class ProtocolGraphRepositoryStub:
        def getProtocolRuntimeInfoByDbId(
                self,
                mapper,
                projectId,
                protocolDbId,
        ):
            assert projectId == 7
            assert protocolDbId == 101

            return {
                "protocolClassName": "ExampleProtocol",
                "params": {},
            }

    class ValueHolder:
        def set(self, value):
            self.value = value

    class ProtocolStub:
        def __init__(self, protocolId):
            self.protocolId = protocolId
            self.runMode = ValueHolder()

        def getObjId(self):
            return self.protocolId

        def getParam(self, key):
            return None

        def setSaved(self):
            self.saved = True

    monkeypatch.setattr(
        duplicateServiceModule,
        "ProtocolIdentityResolver",
        ProtocolIdentityResolverStub,
    )

    monkeypatch.setattr(
        duplicateServiceModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    service = RuntimeProtocolDuplicateService()

    monkeypatch.setattr(
        service,
        "copyPostgresqlInputRefsForDuplicatedProtocol",
        lambda **kwargs: {
            "dependenciesSaved": 0,
        },
    )

    monkeypatch.setattr(
        service,
        "restorePostgresqlPointerInputsBeforeCopy",
        lambda **kwargs: {
            "errors": [],
        },
    )

    sourceProtocol = ProtocolStub(19)
    duplicatedProtocol = ProtocolStub(29)

    result = service.duplicatePostgresqlRuntimeProtocols(
        mapper=object(),
        projectId=7,
        protocols=[
            SimpleNamespace(id=500),
        ],
        getScipionProtocolForRuntimeCallback=lambda **kwargs: sourceProtocol,
        getScipionProtocolByRuntimeIdCallback=lambda protocolId: None,
        getScipionObjectIdCallback=lambda protocol: protocol.getObjId(),
        saveProtocolCallback=lambda **kwargs: (duplicatedProtocol, []),
        syncPostgresqlRuntimeProtocolCallback=lambda **kwargs: {},
        storeProtocolCallback=lambda protocol: None,
        buildProtocolMutationResultCallback=lambda message, **kwargs: kwargs,
    )

    assert strictCalls == [
        19,
        29,
    ]

    assert result["duplicated"] == [
        {
            "sourceId": "19",
            "newId": "29",
        },
    ]


def test_CopyInputRefsUsesStrictScipionProtocolIdentity(
        monkeypatch,
):
    strictCalls = []
    savedRefs = []

    class ProtocolIdentityResolverStub:
        def __init__(self, mapper, projectId):
            assert mapper is not None
            assert projectId == 7

        def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
            strictCalls.append(int(protocolId))

            return {
                19: 101,
                29: 202,
                39: 303,
            }.get(int(protocolId))

        def resolvePostgresqlProtocolDbId(self, protocolId):
            raise AssertionError(
                "Known Scipion protocol ids must not use the dual PostgreSQL resolver"
            )

    class ProtocolGraphRepositoryStub:
        def loadInputRefsForProtocolCopy(
                self,
                mapper,
                projectId,
                protocolDbId,
        ):
            assert projectId == 7
            assert protocolDbId == 101

            return [
                {
                    "inputName": "inputParticles",
                    "itemIndex": 0,
                    "parentProtocolDbId": None,
                    "parentProtocolId": "39",
                    "parentOutputName": "outputParticles",
                    "objectClassName": "SetOfParticles",
                    "objectId": "91",
                },
            ]

        def replaceDependenciesForProtocol(
                self,
                mapper,
                projectId,
                childProtocolDbId,
                parentProtocolDbIds,
        ):
            assert childProtocolDbId == 202
            assert parentProtocolDbIds == [303]
            return 1

        def replaceInputRefsForProtocol(
                self,
                mapper,
                projectId,
                protocolDbId,
                refs,
        ):
            assert protocolDbId == 202
            savedRefs.extend(refs)
            return 1

        def updateProtocolParentIds(
                self,
                mapper,
                projectId,
                protocolDbId,
                parentProtocolIds,
        ):
            assert protocolDbId == 202
            assert parentProtocolIds == [39]

    monkeypatch.setattr(
        duplicateServiceModule,
        "ProtocolIdentityResolver",
        ProtocolIdentityResolverStub,
    )

    monkeypatch.setattr(
        duplicateServiceModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    service = RuntimeProtocolDuplicateService()
    state = service.createDuplicateState()

    report = service.copyPostgresqlInputRefsForDuplicatedProtocol(
        state=state,
        mapper=object(),
        projectId=7,
        sourceProtocolId=19,
        duplicatedProtocolId=29,
    )

    assert strictCalls == [
        19,
        29,
        39,
    ]

    assert report["sourceProtocolDbId"] == 101
    assert report["duplicatedProtocolDbId"] == 202
    assert report["parentProtocolDbIds"] == [303]
    assert report["parentProtocolIds"] == [39]

    assert savedRefs[0]["parentProtocolDbId"] == 303
    assert savedRefs[0]["parentProtocolId"] == "39"


def test_RestorePointerInputsUsesStrictParentScipionIdentity(
        monkeypatch,
):
    strictCalls = []
    loadedProtocolIds = []
    parentProtocol = object()

    class FakePointerParam:
        pass

    class FakeMultiPointerParam:
        pass

    class FakeRelationParam:
        pass

    class ProtocolIdentityResolverStub:
        def __init__(self, mapper, projectId):
            assert mapper is not None
            assert projectId == 7

        @staticmethod
        def toOptionalInt(value):
            if value in (None, ""):
                return None

            return int(value)

        def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
            strictCalls.append(int(protocolId))

            return {
                19: 101,
                39: 303,
            }.get(int(protocolId))

        def resolveScipionProtocolId(self, protocolId):
            raise AssertionError(
                "protocol_input_refs parentProtocolId is already a Scipion protocol id"
            )

        def resolvePostgresqlProtocolDbId(self, protocolId):
            raise AssertionError(
                "Known Scipion protocol ids must not use the dual PostgreSQL resolver"
            )

    class ProtocolGraphRepositoryStub:
        def loadSelfInputRefs(
                self,
                mapper,
                projectId,
                protocolDbId,
        ):
            assert protocolDbId == 101
            return []

    class RuntimePointerResolverStub:
        def loadInputRefsByInputName(
                self,
                mapper,
                projectId,
                protocolDbId,
        ):
            assert protocolDbId == 101

            return {
                "inputParticles": [
                    {
                        "parentProtocolId": "39",
                        "parentOutputName": "outputParticles",
                    },
                ],
            }

        def restorePointerAttributeFromInputRefs(
                self,
                protocol,
                inputName,
                inputRefs,
                isMultiPointer,
                resolveParentProtocolCallback,
        ):
            parentProtocolId, resolvedParentProtocol = resolveParentProtocolCallback(
                inputRefs[0]["parentProtocolId"]
            )

            assert parentProtocolId == 39
            assert resolvedParentProtocol is parentProtocol

            return {
                "restored": [
                    {
                        "inputName": inputName,
                        "parentProtocolId": "39",
                    },
                ],
                "skipped": False,
            }

    class ProtocolStub:
        def __init__(self):
            self.param = FakePointerParam()

        def getObjId(self):
            return 19

        def iterInputAttributes(self):
            return [
                (
                    "inputParticles",
                    object(),
                ),
            ]

        def getParam(self, inputName):
            assert inputName == "inputParticles"
            return self.param

    monkeypatch.setattr(
        duplicateServiceModule,
        "PointerParam",
        FakePointerParam,
    )

    monkeypatch.setattr(
        duplicateServiceModule,
        "MultiPointerParam",
        FakeMultiPointerParam,
    )

    monkeypatch.setattr(
        duplicateServiceModule,
        "RelationParam",
        FakeRelationParam,
    )

    monkeypatch.setattr(
        duplicateServiceModule,
        "ProtocolIdentityResolver",
        ProtocolIdentityResolverStub,
    )

    monkeypatch.setattr(
        duplicateServiceModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    monkeypatch.setattr(
        duplicateServiceModule,
        "RuntimePointerResolver",
        RuntimePointerResolverStub,
    )

    def getScipionProtocolByRuntimeId(protocolId):
        loadedProtocolIds.append(int(protocolId))

        if int(protocolId) == 39:
            return parentProtocol

        return None

    report = RuntimeProtocolDuplicateService().restorePostgresqlPointerInputsBeforeCopy(
        mapper=object(),
        projectId=7,
        protocol=ProtocolStub(),
        getScipionProtocolByRuntimeIdCallback=getScipionProtocolByRuntimeId,
    )

    assert report["protocolId"] == "19"
    assert report["protocolDbId"] == 101
    assert report["restored"] == 1
    assert report["errors"] == []

    assert strictCalls == [
        19,
        39,
    ]

    assert loadedProtocolIds == [
        39,
    ]


