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
        return [value for key, value in self.store.items() if isinstance(key, int)]

    def getMicroscope(self, microscopeId):
        return self.store.get(microscopeId)

    def findMicroscopeIdByName(self, name):
        return next((key for key, value in self.store.items()
                     if isinstance(key, int) and value["name"].lower() == name.lower()), None)

    def saveMicroscope(self, microscopeId, values, detectors):
        if microscopeId is None:
            microscopeId = len(self.store) + 1
        self.store["lastDetectorId"] = self.store.get("lastDetectorId", 0)
        saved = []
        for detector in detectors:
            detectorId = detector["id"]
            if detectorId is None:
                self.store["lastDetectorId"] += 1
                detectorId = self.store["lastDetectorId"]
            saved.append(dict(detector, id=detectorId,
                              pixelSizes=[{"magnification": m, "pixelSize": p} for m, p in detector["pixelSizes"]]))
        self.store[microscopeId] = dict(values, id=microscopeId, detectors=saved)
        return microscopeId

    def countSessions(self, microscopeId):
        return self.store.get(("sessions", microscopeId), 0)

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


FALCON = {"name": "Falcon 4i", "metadataName": "BM-Falcon",
          "pixelSizes": [{"magnification": 120000, "pixelSize": 0.84}, {"magnification": 73000, "pixelSize": 1.35}]}
TALOS = {"name": "Talos 200kV", "csMm": 2.7, "sessionsEnabled": True,
         "detectors": [FALCON, {"name": "Ceta-D", "metadataName": "BM-Ceta"}]}


def _withFalcon(**change):
    return dict(TALOS, detectors=[dict(FALCON, **change)])


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
    falcon, ceta = microscope["detectors"]
    assert [row["magnification"] for row in falcon["pixelSizes"]] == [120000, 73000] and ceta["pixelSizes"] == []
    # The detectors kept keep their id
    edited = client.put("/facility/microscopes/%d" % microscope["id"],
                        json=dict(TALOS, status="maintenance", detectors=[dict(falcon, gainRotation=90)]))
    assert edited.json()["status"] == "maintenance"
    assert [(row["id"], row["gainRotation"]) for row in edited.json()["detectors"]] == [(falcon["id"], 90)]
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
    ({"csMm": -1}, "positive number"),
    (_withFalcon(gainRotation=45), "0, 90, 180 or 270"),
    (_withFalcon(gainFlip="diagonal"), "Unknown gain flip"),
    (_withFalcon(pixelSizes=[{"magnification": 120000, "pixelSize": 0.84},
                             {"magnification": 120000, "pixelSize": 0.85}]), "calibrated twice"),
    (_withFalcon(pixelSizes=[{"magnification": 0, "pixelSize": 0.84}]), "positive"),
    (_withFalcon(name=" "), "Each detector needs a name"),
    (_withFalcon(id=7), "not one of this microscope's"),
    ({"detectors": [FALCON, dict(FALCON, name="falcon 4I", metadataName="")]}, "Two detectors are named"),
    ({"detectors": [FALCON, dict(FALCON, name="Falcon 2")]}, "in the metadata"),
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


def test_TheDetectorOfAMovieIsTheOneItsMetadataNames(modules):
    _, service = modules
    falcon = {"name": "Falcon 4i", "metadataName": "BM-Falcon"}
    ceta = {"name": "Ceta-D", "metadataName": ""}

    assert service.detectorFor([falcon, ceta], "bm-falcon") is falcon
    assert service.detectorFor([falcon, ceta], "CETA-D") is ceta
    # Unknown or unnamed: only a microscope with a single detector tells
    assert service.detectorFor([falcon, ceta], "EF-CCD") is None
    assert service.detectorFor([falcon, ceta]) is None
    assert service.detectorFor([falcon], None) is falcon
    assert service.detectorFor([], "BM-Falcon") is None


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


def test_AMicroscopeWithSessionsStays(modules, monkeypatch):
    store = {}
    client = _client(modules, monkeypatch, ["facility.manage"], store=store)
    microscopeId = client.post("/facility/microscopes", json=TALOS).json()["id"]
    store[("sessions", microscopeId)] = 3

    response = client.delete("/facility/microscopes/%d" % microscopeId)

    assert response.status_code == 409 and "out of service" in response.json()["detail"]


class _SessionService:
    """Keeps sessions in memory, as the routes see the service."""
    store = {}
    calls = []

    def __init__(self, db):
        pass

    def listSessions(self, statuses=None, text=""):
        self.calls.append(("list", statuses, text))
        return list(self.store.values())

    def getSession(self, sessionId):
        return self.store[sessionId]

    def saveSession(self, payload, sessionId=None, userId=None):
        sessionId = sessionId or len(self.store) + 1
        self.store[sessionId] = dict(payload, id=sessionId, name=payload.get("name") or "2026_10_31_Gaoxin_%06d" % sessionId,
                                     microscopeName="Talos", createdBy=userId,
                                     datasets=[dict(row, folder="DATA") for row in payload.get("datasets") or []])
        return self.store[sessionId]

    def deleteSession(self, sessionId):
        return self.store.pop(sessionId)

    def addImage(self, ownerKind, ownerId, data, caption="", userId=None):
        return {"image": {"id": 60, "caption": caption}, "session": {"id": 1, "name": "S"}}


@pytest.fixture
def sessionClient(modules, monkeypatch):
    router, _ = modules
    _SessionService.store, _SessionService.calls = {}, []
    monkeypatch.setattr(router, "FacilitySessionService", _SessionService)
    return lambda permissions, mode="1": _client(modules, monkeypatch, permissions, mode=mode)


SESSION = {"microscopeId": 1, "userId": 7, "bookingRef": "B-1203",
           "datasets": [{"number": 1, "gridId": 6}, {"number": 2, "gridId": 9}]}


def test_TheStaffWhoRunSessionsKeepThem(sessionClient):
    technician = sessionClient(["facility.sessions"])

    created = technician.post("/facility/sessions", json=SESSION)
    assert created.status_code == 201
    session = created.json()
    assert session["name"] == "2026_10_31_Gaoxin_000001" and session["createdBy"] == 1
    assert technician.put("/facility/sessions/1", json=dict(SESSION, status="acquiring")).status_code == 200
    assert technician.delete("/facility/sessions/1").status_code == 204
    assert technician.events == ["facility.sessionCreated", "facility.sessionUpdated", "facility.sessionDeleted"]


def test_TheListShowsTheActiveSessionsUnlessAskedOtherwise(sessionClient):
    monitor = sessionClient(["facility.monitor"])

    assert monitor.get("/facility/sessions").status_code == 200
    monitor.get("/facility/sessions?status=all&q=gaoxin")
    monitor.get("/facility/sessions?status=finished")
    assert _SessionService.calls == [("list", ["planned", "acquiring"], ""), ("list", [], "gaoxin"),
                                     ("list", ["finished"], "")]


def test_OnlyTheStaffWhoRunSessionsChangeThem(sessionClient):
    monitor = sessionClient(["facility.monitor"])

    assert monitor.post("/facility/sessions", json=SESSION).status_code == 403
    assert monitor.post("/facility/sessions/1/images", content=b"jpeg").status_code == 403
    assert sessionClient(["projects.create"]).get("/facility/sessions").status_code == 403
    assert sessionClient(["facility.manage"], mode="0").get("/facility/sessions").status_code == 404


def test_SessionsAndDatasetsKeepImages(sessionClient):
    technician = sessionClient(["facility.sessions"])

    added = technician.post("/facility/datasets/4/images?caption=Atlas", content=b"jpeg")

    assert added.status_code == 201 and added.json()["image"]["caption"] == "Atlas"
    assert technician.events == ["facility.sessionUpdated"]


def test_TheRoomScreenNeedsItsTokenNotAUser(modules, monkeypatch):
    router, _ = modules

    class Room:
        def __init__(self, db):
            pass

        def checkToken(self, token):
            if token != "good":
                raise HTTPException(status_code=404, detail="No such screen")

        def view(self):
            return {"microscopes": [], "upcoming": []}

        def link(self):
            return {"enabled": True, "token": "good"}

    monkeypatch.setattr(router, "FacilityRoom", Room)
    client = _client(modules, monkeypatch, [])
    # No user at all: the screen's routes do not ask for one
    client.app.dependency_overrides.clear()
    database = importlib.import_module("app.backend.database")
    client.app.dependency_overrides[database.getMapper] = lambda: type("Mapper", (), {"db": None})()

    assert client.get("/facility/room?token=good").json() == {"microscopes": [], "upcoming": []}
    assert client.get("/facility/room?token=bad").status_code == 404
    assert client.get("/facility/room").status_code == 404
    assert _client(modules, monkeypatch, ["facility.sessions"]).get("/facility/settings/room-screen").status_code == 403
    assert _client(modules, monkeypatch, ["facility.manage"]).get("/facility/settings/room-screen").json()["token"] == "good"


class _BookingService:
    calls = []
    notified = []
    BOOKING = {"id": 5, "resourceName": "Krios", "kind": "booking", "status": "requested",
               "startsAt": "2026-12-01T08:00:00+00:00", "endsAt": "2026-12-02T08:00:00+00:00", "ownerId": 7,
               "ownerEmail": "gaoxin@example.com", "sessionName": None}

    def __init__(self, db):
        pass

    def listResources(self, user):
        return [{"id": 1, "name": "Krios"}]

    def saveResource(self, payload, resourceId=None):
        self.calls.append(("resource", payload["name"]))
        return dict(payload, id=resourceId or 1)

    def getResource(self, resourceId):
        return {"id": resourceId, "name": "Krios", "unit": "session", "minHours": None, "maxHours": None,
                "dayStart": "09:00", "active": True, "microscopeId": None, "requiresAuthorization": False}

    def listBookings(self, user, start, end, resourceIds, statuses):
        self.calls.append(("list", start, end, resourceIds, statuses))
        return []

    def create(self, payload, user):
        self.calls.append(("create", payload))
        return dict(self.BOOKING, ownerId=payload.get("ownerId", user["id"]))

    def decide(self, bookingId, payload, user):
        self.calls.append(("decide", payload))
        return dict(self.BOOKING, status="confirmed")

    def notify(self, booking, what):
        self.notified.append(what)


@pytest.fixture
def bookingClient(modules, monkeypatch):
    router, _ = modules
    _BookingService.calls, _BookingService.notified = [], []
    monkeypatch.setattr(router, "FacilityBookingService", _BookingService)
    return lambda permissions, mode="1": _client(modules, monkeypatch, permissions, mode=mode)


def test_EveryUserAsksForTimeAndOnlyTheFacilityDecides(bookingClient):
    user = bookingClient([])

    assert user.get("/facility/resources").json() == [{"id": 1, "name": "Krios"}]
    asked = user.post("/facility/bookings", json={"resourceId": 1, "startsAt": "2026-12-01T09:00:00+01:00",
                                                  "endsAt": "2026-12-02T09:00:00+01:00"})
    assert asked.status_code == 201
    # Only what was sent goes to the service: whom a booking is for is not said, so it is the user's
    assert _BookingService.calls[-1] == ("create", {"resourceId": 1, "startsAt": "2026-12-01T09:00:00+01:00",
                                                    "endsAt": "2026-12-02T09:00:00+01:00"})
    user.get("/facility/bookings?start=2026-12-01T00:00:00Z&resourceId=1&resourceId=2&status=confirmed")
    assert _BookingService.calls[-1] == ("list", "2026-12-01T00:00:00Z", None, [1, 2], ["confirmed"])
    assert user.post("/facility/bookings/5/decision", json={"action": "confirm"}).status_code == 403
    assert user.post("/facility/resources", json={"name": "GP2"}).status_code == 403
    assert user.events == ["facility.bookingRequested"]
    assert _BookingService.notified == []

    technician = bookingClient(["facility.sessions"])
    assert technician.post("/facility/bookings", json={"resourceId": 1, "ownerId": 7, "startsAt": "a",
                                                       "endsAt": "b"}).status_code == 201
    assert technician.post("/facility/bookings/5/decision", json={"action": "confirm", "reason": "Fits"}).json()[
        "status"] == "confirmed"
    assert technician.events == ["facility.bookingCreated", "facility.bookingConfirmed"]
    assert _BookingService.notified == ["was booked for you by the facility", "is confirmed"]

    manager = bookingClient(["facility.manage"])
    assert manager.post("/facility/resources", json={"name": "GP2", "unit": "hour"}).status_code == 201
    assert manager.events == ["facility.resourceCreated"]
    assert bookingClient(["facility.manage"], mode="0").get("/facility/bookings").status_code == 404
