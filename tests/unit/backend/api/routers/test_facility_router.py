"""Facility mode and the microscopes routes: off, nothing of it exists; on, only the staff see it."""
import importlib
import io

import pytest
from PIL import Image
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


class _Mapper:
    def __init__(self, store):
        self.store = store

    def listMicroscopes(self):
        return [value for key, value in self.store.items() if not isinstance(key, tuple)]

    def getMicroscope(self, microscopeId):
        return self.store.get(microscopeId)

    def findMicroscopeIdByName(self, name):
        return next((key for key, value in self.store.items() if value["name"].lower() == name.lower()), None)

    def insertMicroscope(self, values, pixelSizes):
        microscopeId = len(self.store) + 1
        self.store[microscopeId] = dict(values, id=microscopeId,
                                        pixelSizes=[{"magnification": m, "pixelSize": p} for m, p in pixelSizes])
        return microscopeId

    def updateMicroscope(self, microscopeId, values, pixelSizes):
        self.store[microscopeId] = dict(values, id=microscopeId,
                                        pixelSizes=[{"magnification": m, "pixelSize": p} for m, p in pixelSizes])

    def deleteMicroscope(self, microscopeId):
        self.store.pop(microscopeId)

    def getPhoto(self, microscopeId):
        return self.store.get(("photo", microscopeId))

    def savePhoto(self, microscopeId, contentType, data):
        self.store[("photo", microscopeId)] = {"contentType": contentType, "data": data}

    def deletePhoto(self, microscopeId):
        self.store.pop(("photo", microscopeId), None)


@pytest.fixture
def modules(authTestEnv):
    return (importlib.import_module("app.backend.api.routers.facility_router"),
            importlib.import_module("app.backend.api.services.facility_service"))


def _client(modules, monkeypatch, permissions, mode="1", store=None):
    router, service = modules
    dependencies = importlib.import_module("app.backend.api.dependencies")
    database = importlib.import_module("app.backend.database")
    monkeypatch.setenv("SCIPIONWEB_FACILITY_MODE", mode)
    store = {} if store is None else store
    monkeypatch.setattr(service, "FacilityMicroscopePostgresqlMapper", lambda db: _Mapper(store))
    events = []
    monkeypatch.setattr(router, "recordAudit", lambda mapper, user, action, *args: events.append(action))
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[dependencies.getCurrentUser] = lambda: {"id": 1, "permissions": list(permissions)}
    app.dependency_overrides[database.getMapper] = lambda: type("Mapper", (), {"db": None})()
    client = TestClient(app)
    client.events = events
    return client


TALOS = {"name": "Talos 200kV", "csMm": 2.7, "sessionsEnabled": True,
         "pixelSizes": [{"magnification": 120000, "pixelSize": 0.84}, {"magnification": 73000, "pixelSize": 1.35}]}


def test_WithoutFacilityModeNothingOfItExists(modules, monkeypatch):
    client = _client(modules, monkeypatch, ["facility.manage"], mode="0")

    assert client.get("/facility/status").json() == {"enabled": False, "permissions": []}
    assert client.get("/facility/microscopes").status_code == 404
    assert client.post("/facility/microscopes", json=TALOS).status_code == 404


def test_TheStatusTellsTheWebWhatToShow(modules, monkeypatch):
    client = _client(modules, monkeypatch, ["facility.monitor", "projects.create"])

    assert client.get("/facility/status").json() == {"enabled": True, "permissions": ["facility.monitor"]}


def test_TheManagerKeepsTheMicroscopes(modules, monkeypatch):
    client = _client(modules, monkeypatch, ["facility.manage"])

    created = client.post("/facility/microscopes", json=TALOS)
    assert created.status_code == 201
    microscope = created.json()
    assert [row["magnification"] for row in microscope["pixelSizes"]] == [120000, 73000]
    edited = client.put("/facility/microscopes/%d" % microscope["id"], json=dict(TALOS, status="maintenance"))
    assert edited.json()["status"] == "maintenance"
    assert client.delete("/facility/microscopes/%d" % microscope["id"]).status_code == 204
    assert client.events == ["facility.microscopeCreated", "facility.microscopeUpdated",
                             "facility.microscopeDeleted"]


def test_TheStaffSeeTheMicroscopesAndOnlyTheManagerChangesThem(modules, monkeypatch):
    store = {}
    _client(modules, monkeypatch, ["facility.manage"], store=store).post("/facility/microscopes", json=TALOS)

    technician = _client(modules, monkeypatch, ["facility.sessions"], store=store)
    assert [row["name"] for row in technician.get("/facility/microscopes").json()] == ["Talos 200kV"]
    assert technician.post("/facility/microscopes", json=dict(TALOS, name="Krios")).status_code == 403

    user = _client(modules, monkeypatch, ["projects.create"], store=store)
    assert user.get("/facility/microscopes").status_code == 403


@pytest.mark.parametrize("change, message", [
    ({"name": " "}, "needs a name"),
    ({"status": "broken"}, "Unknown microscope status"),
    ({"gainRotation": 45}, "0, 90, 180 or 270"),
    ({"gainFlip": "diagonal"}, "Unknown gain flip"),
    ({"csMm": -1}, "positive number"),
    ({"pixelSizes": [{"magnification": 120000, "pixelSize": 0.84}, {"magnification": 120000, "pixelSize": 0.85}]},
     "calibrated twice"),
    ({"pixelSizes": [{"magnification": 0, "pixelSize": 0.84}]}, "positive"),
])
def test_AMicroscopeIsCheckedBeforeItIsKept(modules, monkeypatch, change, message):
    client = _client(modules, monkeypatch, ["facility.manage"])

    response = client.post("/facility/microscopes", json=dict(TALOS, **change))

    assert response.status_code == 400 and message in response.json()["detail"]


def test_ATakenNameIsAConflict(modules, monkeypatch):
    client = _client(modules, monkeypatch, ["facility.manage"])
    client.post("/facility/microscopes", json=TALOS)

    assert client.post("/facility/microscopes", json=dict(TALOS, name="talos 200KV")).status_code == 409


def test_TheCalibratedPixelIsFoundByMagnificationOrNearTheNominalOne(modules):
    _, service = modules
    table = [{"magnification": 120000, "pixelSize": 0.84}, {"magnification": 92000, "pixelSize": 1.14}]

    assert service.calibratedPixelSize(table, magnification=120000.0) == 0.84
    assert service.calibratedPixelSize(table, magnification=150000, nominalPixelSize=1.1453) == 1.14
    # Farther than the tolerance: the nominal one is kept
    assert service.calibratedPixelSize(table, nominalPixelSize=1.0) is None
    assert service.calibratedPixelSize([], magnification=120000) is None


def _png(width=2400, height=1800):
    output = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(output, format="PNG")
    return output.getvalue()


def test_AMicroscopeGetsAPhotoKeptAsAWebImage(modules, monkeypatch):
    store = {}
    manager = _client(modules, monkeypatch, ["facility.manage"], store=store)
    microscopeId = manager.post("/facility/microscopes", json=TALOS).json()["id"]

    uploaded = manager.put("/facility/microscopes/%d/photo" % microscopeId, content=_png(),
                           headers={"Content-Type": "image/png"})
    assert uploaded.status_code == 200

    technician = _client(modules, monkeypatch, ["facility.sessions"], store=store)
    photo = technician.get("/facility/microscopes/%d/photo" % microscopeId)
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/webp"
    image = Image.open(io.BytesIO(photo.content))
    assert image.format == "WEBP" and image.size == (1600, 1200)
    assert manager.events[-1] == "facility.microscopeUpdated"


def test_OnlyTheManagerChangesThePhoto(modules, monkeypatch):
    store = {}
    microscopeId = _client(modules, monkeypatch, ["facility.manage"], store=store).post(
        "/facility/microscopes", json=TALOS).json()["id"]
    technician = _client(modules, monkeypatch, ["facility.sessions"], store=store)

    assert technician.put("/facility/microscopes/%d/photo" % microscopeId, content=_png()).status_code == 403
    assert technician.delete("/facility/microscopes/%d/photo" % microscopeId).status_code == 403
    assert technician.get("/facility/microscopes/%d/photo" % microscopeId).status_code == 404


@pytest.mark.parametrize("body, statusCode", [
    (b"", 400),
    (b"not an image at all", 400),
    (b"GIF89a" + b"\x00" * 64, 400),
])
def test_OnlyImagesAreKeptAsPhotos(modules, monkeypatch, body, statusCode):
    client = _client(modules, monkeypatch, ["facility.manage"])
    microscopeId = client.post("/facility/microscopes", json=TALOS).json()["id"]

    assert client.put("/facility/microscopes/%d/photo" % microscopeId, content=body).status_code == statusCode


def test_ATooBigPhotoIsRefusedBeforeItIsRead(modules, monkeypatch):
    _, service = modules
    client = _client(modules, monkeypatch, ["facility.manage"])
    microscopeId = client.post("/facility/microscopes", json=TALOS).json()["id"]
    monkeypatch.setattr(service, "PHOTO_MAX_UPLOAD_BYTES", 10)

    assert client.put("/facility/microscopes/%d/photo" % microscopeId, content=_png(20, 20)).status_code == 413


def test_ThePhotoCanBeRemoved(modules, monkeypatch):
    client = _client(modules, monkeypatch, ["facility.manage"])
    microscopeId = client.post("/facility/microscopes", json=TALOS).json()["id"]
    client.put("/facility/microscopes/%d/photo" % microscopeId, content=_png(40, 30))

    assert client.delete("/facility/microscopes/%d/photo" % microscopeId).status_code == 200
    assert client.get("/facility/microscopes/%d/photo" % microscopeId).status_code == 404


class _SampleService:
    """Keeps samples in memory, as the routes see the service."""
    store = {}

    def __init__(self, db):
        pass

    def listSamples(self, text=""):
        return [sample for sample in self.store.values() if text.lower() in sample["code"].lower()]

    def saveSample(self, payload, sampleId=None):
        sampleId = sampleId or len(self.store) + 1
        self.store[sampleId] = dict(payload, id=sampleId)
        return self.store[sampleId]

    def deleteSample(self, sampleId):
        return self.store.pop(sampleId)

    def addImage(self, ownerKind, ownerId, data, caption="", userId=None):
        image = {"id": 50, "caption": caption, "contentType": "image/webp", "data": b"webp", "sampleId": 1}
        self.store[("image", 50)] = image
        return {"image": {"id": 50, "caption": caption}, "sample": {"id": 1, "code": "NZ251"}}

    def getImage(self, imageId):
        return self.store[("image", imageId)]

    def deleteImage(self, imageId):
        self.store.pop(("image", imageId))
        return {"id": 1, "code": "NZ251"}


@pytest.fixture
def sampleClient(modules, monkeypatch):
    router, _ = modules
    _SampleService.store = {}
    monkeypatch.setattr(router, "FacilitySampleService", _SampleService)
    return lambda permissions, mode="1": _client(modules, monkeypatch, permissions, mode=mode)


NZ = {"code": "NZ251", "boxes": [{"label": "1", "vitrifiedOn": "2026-09-28",
                                  "grids": [{"position": 1, "gridNumber": 1, "gridType": "Graphene"}]}]}


def test_TheStaffWhoRunSessionsRecordSamples(sampleClient):
    technician = sampleClient(["facility.sessions"])

    created = technician.post("/facility/samples", json=NZ)
    assert created.status_code == 201
    sampleId = created.json()["id"]
    assert technician.put("/facility/samples/%d" % sampleId, json=dict(NZ, description="nsp9")).status_code == 200
    assert [sample["code"] for sample in technician.get("/facility/samples?q=nz2").json()] == ["NZ251"]
    assert technician.delete("/facility/samples/%d" % sampleId).status_code == 204
    assert technician.events == ["facility.sampleCreated", "facility.sampleUpdated", "facility.sampleDeleted"]


def test_TheMonitorSeesSamplesButDoesNotRecordThem(sampleClient):
    sampleClient(["facility.manage"]).post("/facility/samples", json=NZ)
    monitor = sampleClient(["facility.monitor"])

    assert monitor.get("/facility/samples").status_code == 200
    assert monitor.post("/facility/samples", json=dict(NZ, code="NZ252")).status_code == 403
    assert sampleClient(["projects.create"]).get("/facility/samples").status_code == 403


def test_WithoutFacilityModeThereAreNoSamples(sampleClient):
    assert sampleClient(["facility.manage"], mode="0").get("/facility/samples").status_code == 404


def test_ABoxDateIsADate(sampleClient):
    payload = dict(NZ, boxes=[dict(NZ["boxes"][0], vitrifiedOn="28/09/2026")])

    assert sampleClient(["facility.manage"]).post("/facility/samples", json=payload).status_code == 422


def test_TheStaffWhoKeepSamplesAddAndRemoveImagesAndAnyStaffSeesThem(sampleClient):
    technician = sampleClient(["facility.sessions"])

    added = technician.post("/facility/grids/101/images?caption=Atlas", content=b"jpeg")
    assert added.status_code == 201 and added.json()["image"]["caption"] == "Atlas"
    assert technician.events == ["facility.sampleUpdated"]

    monitor = sampleClient(["facility.monitor"])
    image = monitor.get("/facility/images/50")
    assert image.status_code == 200 and image.headers["content-type"] == "image/webp"
    assert "immutable" in image.headers["cache-control"]
    assert monitor.post("/facility/boxes/10/images", content=b"jpeg").status_code == 403
    assert monitor.delete("/facility/images/50").status_code == 403

    assert technician.delete("/facility/images/50").status_code == 200
