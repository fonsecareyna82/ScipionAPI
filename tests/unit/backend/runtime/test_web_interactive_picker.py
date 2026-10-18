"""A picking protocol's interactive step waits for the web picker, like for Java."""
import threading
import time

import pytest

from app.backend.runtime import web_interactive_picker as picker


class FakeProtocol:
    def __init__(self):
        self.outputCoordinates = None
        self.registered = []

    def getObjId(self):
        return 116

    def iterOutputAttributes(self):
        if self.outputCoordinates is not None:
            yield "outputCoordinates", self.outputCoordinates

    def registerCoords(self, coordsDir):
        self.registered.append(coordsDir)

        class Coordinates:
            def getSize(self):
                return 26

        self.outputCoordinates = Coordinates()


def startStep(tmp_path, protocol):
    process = picker.launchWebSupervisedPicker("mics.sqlite", str(tmp_path), protocol)
    finished = {}
    thread = threading.Thread(target=lambda: finished.setdefault("code", process.wait()), daemon=True)
    thread.start()
    return thread, finished


def test_the_step_waits_until_the_web_closes_the_picker(tmp_path):
    thread, finished = startStep(tmp_path, FakeProtocol())
    time.sleep(0.5)
    session = picker.readSession(str(tmp_path))
    assert session["protocolId"] == 116 and session["sessionId"] and not finished
    assert picker.requestClose(str(tmp_path)) is True
    thread.join(5)
    assert finished == {"code": 0}
    assert picker.readSession(str(tmp_path)) is None
    assert picker.requestClose(str(tmp_path)) is False


def test_the_running_protocol_registers_the_coordinates_the_web_asks_for(tmp_path):
    protocol = FakeProtocol()
    thread, _ = startStep(tmp_path, protocol)
    answer = picker.requestRegisterCoordinates(str(tmp_path), timeout=10)
    assert answer == {"id": answer["id"], "ok": True, "outputName": "outputCoordinates", "totalCoordinates": 26}
    assert protocol.registered == [str(tmp_path)]
    picker.requestClose(str(tmp_path))
    thread.join(5)


def test_an_unanswered_request_fails_cleanly_when_no_step_waits(tmp_path):
    (tmp_path / picker.CHANNEL_FOLDER).mkdir()
    answer = picker.requestRegisterCoordinates(str(tmp_path), timeout=2)
    assert answer["ok"] is False
    assert not list((tmp_path / picker.CHANNEL_FOLDER).iterdir())


def test_a_stale_session_is_not_open(tmp_path, monkeypatch):
    thread, _ = startStep(tmp_path, FakeProtocol())
    time.sleep(0.3)
    monkeypatch.setattr(picker, "SESSION_TIMEOUT_SECONDS", -1)
    assert picker.readSession(str(tmp_path)) is None
    monkeypatch.setattr(picker, "SESSION_TIMEOUT_SECONDS", 20)
    picker.requestClose(str(tmp_path))
    thread.join(5)


def test_protocol_modules_get_the_web_picker_while_running(monkeypatch):
    import sys
    import types
    from pwem.viewers import showj
    original = showj.launchSupervisedPickerGUI
    # As xmipp3's picking protocol: from pwem.viewers import launchSupervisedPickerGUI
    picking = types.ModuleType("fake_picking_protocol")
    picking.launchSupervisedPickerGUI = original
    monkeypatch.setitem(sys.modules, "fake_picking_protocol", picking)
    assert picking.launchSupervisedPickerGUI is original
    with picker.webInteractivePickers():
        assert picking.launchSupervisedPickerGUI is picker.launchWebSupervisedPicker
        assert showj.launchSupervisedPickerGUI is picker.launchWebSupervisedPicker
    assert picking.launchSupervisedPickerGUI is original
    monkeypatch.setenv(picker.SWITCH, "0")
    with picker.webInteractivePickers():
        assert picking.launchSupervisedPickerGUI is original


def test_every_launch_is_a_new_session(tmp_path):
    ids = []
    for _ in range(2):
        thread, _ = startStep(tmp_path, FakeProtocol())
        time.sleep(0.3)
        ids.append(picker.readSession(str(tmp_path))["sessionId"])
        picker.requestClose(str(tmp_path))
        thread.join(5)
    assert ids[0] != ids[1]


class FakeClassifier:
    def __init__(self, delay=0.0):
        self.calls = []
        self.lastAutopicked = None
        self.delay = delay
        self.closed = False

    def train(self, rows, rectangle):
        time.sleep(self.delay)
        self.calls.append(("train", rows, rectangle))

    def autopick(self, micrograph, percent):
        self.calls.append(("autopick", micrograph, percent))
        self.lastAutopicked = micrograph
        return [(1, 2, 0.5)]

    def correct(self, added, automatic):
        self.calls.append(("correct", added, automatic))


@pytest.fixture
def stepClassifier(monkeypatch):
    from app.backend.runtime import xmipp_classifier_session as classifiers
    fake = FakeClassifier()
    created = []

    def classifierSession(folder, size, mics, cwd):
        created.append((folder, size, tuple(mics), cwd))
        return fake

    monkeypatch.setattr(classifiers, "classifierSession", classifierSession)
    monkeypatch.setattr(classifiers, "closeClassifierSession",
                        lambda folder: setattr(fake, "closed", True))
    return fake, created


def test_the_api_reaches_the_classifier_kept_alive_by_the_waiting_step(tmp_path, stepClassifier):
    from app.backend.runtime.xmipp_classifier_session import StepClassifier
    fake, created = stepClassifier
    thread, _ = startStep(tmp_path, FakeProtocol())
    classifier = StepClassifier(str(tmp_path), 33, ["/p/a.mrc", "/p/b.mrc"], "/p")
    assert classifier.lastAutopicked is None
    classifier.train([("/p/a.mrc", "/p/a.pos")], (0, 0, 10, 10))
    assert classifier.autopick("/p/a.mrc", 50) == [(1, 2, 0.5)]
    # A new API request (another object, maybe another API process) sees the same state.
    assert StepClassifier(str(tmp_path), 33, ["/p/a.mrc", "/p/b.mrc"], "/p").lastAutopicked == "/p/a.mrc"
    classifier.correct([(3, 4)], [(1, 2, 0.5, -1)])
    assert fake.calls == [("train", [("/p/a.mrc", "/p/a.pos")], (0, 0, 10, 10)),
                          ("autopick", "/p/a.mrc", 50),
                          ("correct", [(3, 4)], [(1, 2, 0.5, -1)])]
    assert created[0] == (str(tmp_path), 33, ("/p/a.mrc", "/p/b.mrc"), "/p")
    picker.requestClose(str(tmp_path))
    thread.join(5)
    # The classifier ends with the step, as the Java picker does.
    assert fake.closed


def test_classifier_errors_reach_the_api(tmp_path, stepClassifier):
    from app.backend.runtime.xmipp_classifier_session import ClassifierError, StepClassifier
    fake, _ = stepClassifier
    fake.train = lambda rows, rectangle: (_ for _ in ()).throw(RuntimeError("no particles"))
    thread, _ = startStep(tmp_path, FakeProtocol())
    with pytest.raises(ClassifierError, match="no particles"):
        StepClassifier(str(tmp_path), 33, [], "/p").train([], (0, 0, 1, 1))
    picker.requestClose(str(tmp_path))
    thread.join(5)


def test_the_session_stays_open_while_the_classifier_trains(tmp_path, stepClassifier, monkeypatch):
    from app.backend.runtime.xmipp_classifier_session import StepClassifier
    fake, _ = stepClassifier
    fake.delay = 1.5
    monkeypatch.setattr(picker, "HEARTBEAT_SECONDS", 0.1)
    monkeypatch.setattr(picker, "SESSION_TIMEOUT_SECONDS", 0.5)
    thread, _ = startStep(tmp_path, FakeProtocol())
    training = threading.Thread(
        target=lambda: StepClassifier(str(tmp_path), 33, [], "/p").train([], (0, 0, 1, 1)), daemon=True)
    training.start()
    time.sleep(1.0)
    assert training.is_alive() and picker.readSession(str(tmp_path)) is not None
    training.join(5)
    picker.requestClose(str(tmp_path))
    thread.join(5)
