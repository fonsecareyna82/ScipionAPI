"""A picking protocol's interactive step waits for the web picker, like for Java."""
import threading
import time

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
