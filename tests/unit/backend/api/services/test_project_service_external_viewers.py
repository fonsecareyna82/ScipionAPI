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
import threading

import pytest
from fastapi import HTTPException


class FakeItem:
    def __init__(self, tsId=None, objId=None, label=None, fileName=None):
        self._tsId = tsId
        self._objId = objId
        self.label = label
        self._fileName = fileName

    def getTsId(self):
        if self._tsId is None:
            raise AttributeError("no tsId")
        return self._tsId

    def getObjId(self):
        return self._objId

    def getObjLabel(self):
        return self.label

    def getFileName(self):
        return self._fileName


class FakeIterableOutput:
    def __init__(self, items):
        self.items = list(items)

    def __iter__(self):
        return iter(self.items)


class FakeSetWithGetItem(FakeIterableOutput):
    def __init__(self, items, indexAttr="_objId"):
        super().__init__(items)
        self.indexAttr = indexAttr
        self.getItemCalls = []

    def getItem(self, key, value):
        self.getItemCalls.append((key, value))
        if key != self.indexAttr:
            return None
        for item in self.items:
            if getattr(item, self.indexAttr, None) == value:
                return item
        return None


class FakeSingleObject:
    def getFileName(self):
        return "single.mrc"


class FakeProtocol:
    def __init__(self, outputName, output):
        self._outputName = outputName
        setattr(self, outputName, output)

    def iterOutputAttributes(self):
        return iter([(self._outputName, getattr(self, self._outputName))])


class FakeCurrentProject:
    def __init__(self, protocol):
        self.protocol = protocol
        self.lastGetProtocolId = None

    def getProtocol(self, protocolId):
        self.lastGetProtocolId = protocolId
        return self.protocol


class FakeViewerClassBase:
    _label = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def visualize(self, targetObj):
        return None


@pytest.fixture
def projectServiceModule(authTestEnv):
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    instance = object.__new__(projectServiceModule.ProjectService)
    instance.currentProject = None
    instance.tomoList = {}
    return instance


# ---------------------------------------------------------------------------
# Descriptor / id normalization
# ---------------------------------------------------------------------------

def test_BuildExternalViewerDescriptorStripsViewerSuffixFromLabel(service):
    class SomeThingViewer(FakeViewerClassBase):
        pass

    descriptor = service._buildExternalViewerDescriptor(SomeThingViewer)

    assert descriptor["id"] == "something"
    assert descriptor["label"] == "SomeThing"
    assert descriptor["className"] == "SomeThingViewer"
    assert descriptor["available"] is True


def test_NormalizeExternalViewerIdSanitizesNonAlnum():
    class Weird__Viewer:
        pass

    from app.backend.api.services.project.core import external_viewers

    assert external_viewers.normalizeExternalViewerId(Weird__Viewer) == "weird"


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_MatchExternalViewerClassFindsByNormalizedId(service):
    class FooViewer(FakeViewerClassBase):
        pass

    class BarViewer(FakeViewerClassBase):
        pass

    viewerClass, descriptor = service._matchExternalViewerClass(
        viewerClasses=[FooViewer, BarViewer],
        viewerId="bar",
    )

    assert viewerClass is BarViewer
    assert descriptor["className"] == "BarViewer"


def test_MatchExternalViewerClassRaises404WhenNotFound(service):
    class FooViewer(FakeViewerClassBase):
        pass

    with pytest.raises(HTTPException) as exc:
        service._matchExternalViewerClass(viewerClasses=[FooViewer], viewerId="missing")

    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Object id extraction / single-object detection
# ---------------------------------------------------------------------------

def test_GetExternalViewerObjectIdsCollectsFromMethodsAndAttrs(service):
    item = FakeItem(tsId="ts-1", objId=42, label="Label 1")

    ids = service._getExternalViewerObjectIds(item)

    assert "ts-1" in ids
    assert "42" in ids
    assert "Label 1" in ids


def test_IsSingleExternalViewerObjectDetectsFileNameOnlyObject(service):
    assert service._isSingleExternalViewerObject(FakeSingleObject()) is True
    assert service._isSingleExternalViewerObject(FakeIterableOutput([])) is False
    assert service._isSingleExternalViewerObject(None) is False


# ---------------------------------------------------------------------------
# Coords3d tomogram resolution (self.tomoList caching)
# ---------------------------------------------------------------------------

def test_ResolveExternalViewerCoords3dTomogramCachesResolvedTomogram(service):
    tomo = FakeItem(tsId="tomo-7")

    class FakeCoords3dOutput:
        def iterTomograms(self):
            return iter([tomo])

    resolved = service._resolveExternalViewerCoords3dTomogram(
        outputObj=FakeCoords3dOutput(),
        objectId="tomo-7",
    )

    assert resolved is tomo
    assert service.tomoList["tomo-7"] is tomo

    # Second call should hit the cache without re-scanning outputObj.
    class ExplodingOutput:
        def iterTomograms(self):
            raise AssertionError("should not iterate when cached")

    cachedResolved = service._resolveExternalViewerCoords3dTomogram(
        outputObj=ExplodingOutput(),
        objectId="tomo-7",
    )

    assert cachedResolved is tomo


def test_ResolveExternalViewerCoords3dTomogramReturnsNoneWhenNotFound(service):
    class FakeCoords3dOutput:
        def iterTomograms(self):
            return iter([])

    resolved = service._resolveExternalViewerCoords3dTomogram(
        outputObj=FakeCoords3dOutput(),
        objectId="missing",
    )

    assert resolved is None
    assert service.tomoList == {}


# ---------------------------------------------------------------------------
# CTFTomoSeries / set-item-by-public-id resolution
# ---------------------------------------------------------------------------

def test_ResolveExternalViewerCTFTomoSeriesMatchesByTsId(service):
    target = FakeItem(tsId="cts-1")
    other = FakeItem(tsId="cts-2")

    resolved = service._resolveExternalViewerCTFTomoSeries(
        outputObj=FakeIterableOutput([other, target]),
        objectId="cts-1",
    )

    assert resolved is target


def test_ResolveExternalViewerSetItemByPublicIdUsesGetItem(service):
    target = FakeItem(objId=5)
    fakeSet = FakeSetWithGetItem([FakeItem(objId=4), target])

    resolved = service._resolveExternalViewerSetItemByPublicId(
        outputObj=fakeSet,
        objectId=4,
    )

    assert resolved is target
    assert fakeSet.getItemCalls[0] == ("_objId", 5)


def test_ResolveExternalViewerSetItemByPublicIdFallsBackToEnumeration(service):
    target = FakeItem()
    outputObj = FakeIterableOutput([FakeItem(), target])

    resolved = service._resolveExternalViewerSetItemByPublicId(
        outputObj=outputObj,
        objectId=1,
    )

    assert resolved is target


# ---------------------------------------------------------------------------
# Target-object dispatch
# ---------------------------------------------------------------------------

def test_ResolveExternalViewerTargetObjectReturnsOutputWhenNoObjectId(service):
    outputObj = FakeIterableOutput([])

    result = service._resolveExternalViewerTargetObject(outputObj=outputObj)

    assert result is outputObj


def test_ResolveExternalViewerTargetObjectSingleVolumeReturnsWholeOutput(service):
    outputObj = FakeSingleObject()

    result = service._resolveExternalViewerTargetObject(
        outputObj=outputObj,
        objectId="0",
        objectKind="volume",
    )

    assert result is outputObj


def test_ResolveExternalViewerTargetObjectDispatchesToCoords3d(service):
    tomo = FakeItem(tsId="tomo-9")

    class FakeCoords3dOutput:
        def iterTomograms(self):
            return iter([tomo])

    resolved = service._resolveExternalViewerTargetObject(
        outputObj=FakeCoords3dOutput(),
        objectId="tomo-9",
        objectKind="coords3dTomogram",
    )

    assert resolved is tomo
    assert service.tomoList["tomo-9"] is tomo


def test_ResolveExternalViewerTargetObjectFallsBackToGenericIteration(service):
    target = FakeItem(label="pick-me")
    outputObj = FakeIterableOutput([FakeItem(label="other"), target])

    resolved = service._resolveExternalViewerTargetObject(
        outputObj=outputObj,
        objectId="pick-me",
        objectKind="unknownKind",
    )

    assert resolved is target


def test_ResolveExternalViewerTargetObjectRaises404WhenNotFound(service):
    outputObj = FakeIterableOutput([FakeItem(label="only-one")])

    with pytest.raises(HTTPException) as exc:
        service._resolveExternalViewerTargetObject(
            outputObj=outputObj,
            objectId="missing",
        )

    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Protocol output resolution
# ---------------------------------------------------------------------------

def test_GetProtocolOutputObjectReturnsDirectAttribute(service):
    output = FakeIterableOutput([])
    protocol = FakeProtocol("outputTomograms", output)
    service.currentProject = FakeCurrentProject(protocol)

    resolvedProtocol, resolvedOutput = service._getProtocolOutputObject(
        protocolId=3,
        outputName="outputTomograms",
    )

    assert resolvedProtocol is protocol
    assert resolvedOutput is output
    assert service.currentProject.lastGetProtocolId == 3


def test_GetProtocolOutputObjectRaises404WhenOutputMissing(service):
    class EmptyProtocol:
        def iterOutputAttributes(self):
            return iter([])

    service.currentProject = FakeCurrentProject(EmptyProtocol())

    with pytest.raises(HTTPException) as exc:
        service._getProtocolOutputObject(protocolId=3, outputName="missingOutput")

    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# listExternalViewers / launchExternalViewer end-to-end
# ---------------------------------------------------------------------------

def test_ListExternalViewersBuildsDescriptorsAndExcludesBlockedViewers(
    service,
    monkeypatch,
):
    output = FakeIterableOutput([])
    protocol = FakeProtocol("outputSet", output)
    service.currentProject = FakeCurrentProject(protocol)

    class GoodViewer(FakeViewerClassBase):
        pass

    class TomoDataViewer(FakeViewerClassBase):
        pass

    externalViewersModule = importlib.import_module(
        "app.backend.api.services.project.core.external_viewers"
    )

    class FakeDomain:
        def findViewers(self, targetObj, desktop):
            return [GoodViewer, TomoDataViewer]

    class FakeConfig:
        @staticmethod
        def getDomain():
            return FakeDomain()

    monkeypatch.setattr(externalViewersModule, "Config", FakeConfig)

    descriptors = service.listExternalViewers(
        protocolId=3,
        outputName="outputSet",
    )

    assert [d["className"] for d in descriptors] == ["GoodViewer"]


def test_LaunchExternalViewerRunsViewerInBackgroundThreadWithCurrentProject(
    service,
    monkeypatch,
):
    output = FakeIterableOutput([])
    protocol = FakeProtocol("outputSet", output)
    currentProject = FakeCurrentProject(protocol)
    service.currentProject = currentProject

    visualizeCalls = []

    class GoodViewer(FakeViewerClassBase):
        def visualize(self, targetObj):
            visualizeCalls.append((self.kwargs.get("project"), targetObj))
            return None

    externalViewersModule = importlib.import_module(
        "app.backend.api.services.project.core.external_viewers"
    )

    class FakeDomain:
        def findViewers(self, targetObj, desktop):
            return [GoodViewer]

    class FakeConfig:
        @staticmethod
        def getDomain():
            return FakeDomain()

    startedThreads = []
    realThreadInit = threading.Thread.__init__

    def trackingThreadInit(self, *args, **kwargs):
        realThreadInit(self, *args, **kwargs)
        startedThreads.append(self)

    monkeypatch.setattr(externalViewersModule, "Config", FakeConfig)
    monkeypatch.setattr(threading.Thread, "__init__", trackingThreadInit)

    result = service.launchExternalViewer(
        protocolId=3,
        outputName="outputSet",
        viewerId="good",
    )

    assert result["success"] is True
    assert result["viewerId"] == "good"

    for thread in startedThreads:
        thread.join(timeout=5)

    assert visualizeCalls == [(currentProject, output)]
