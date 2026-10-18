"""Protocol form wizards run their own show() with the dialogs answered by the web."""
import pytest

from app.backend.api.services import protocol_wizard_runtime as runtime


class Value:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeProtocol:
    def __init__(self, **values):
        for name, value in values.items():
            setattr(self, name, Value(value))


def run(wizardClass, protocol=None, answers=None, preview=None, paramName="radius"):
    return runtime.runWizard(wizardClass, protocol or FakeProtocol(radius=1), paramName,
                             answers=answers, preview=preview)


def test_a_wizard_without_dialogs_returns_what_it_set():
    class BoxSize:
        def show(self, form):
            form.setVar("boxSize", form.protocol.radius.get() * 4)
            form.setVar("label", "x")

    protocol = FakeProtocol(radius=25, boxSize=None)
    reply = run(BoxSize, protocol)
    assert reply["status"] == "done"
    assert reply["paramUpdates"] == {"boxSize": 100, "label": "x"}
    # As on the desktop, setVar also updates the protocol the wizard reads.
    assert protocol.boxSize.get() == 100


def test_messages_are_reported_and_the_wizard_goes_on():
    from pyworkflow.gui import dialog

    class Warns:
        def show(self, form):
            dialog.showWarning("Empty input", "Select elements first", form.root)
            form.showError("Bad value")
            form.setVar("radius", 3)

    reply = run(Warns)
    assert reply["status"] == "done" and reply["paramUpdates"] == {"radius": 3}
    assert [(m["level"], m["text"]) for m in reply["messages"]] == [
        ("warning", "Select elements first"), ("error", "Bad value")]


class Confirm:
    def show(self, form):
        from pyworkflow.gui.dialog import askYesNo
        if askYesNo("Acquisition", "Use the acquisition found?", form.root):
            form.setVar("voltage", 300)


def test_a_dialog_stops_the_run_and_is_described_for_the_web():
    reply = run(Confirm)
    assert reply["status"] == "dialog" and reply["step"] == 0
    assert reply["dialog"] == {"type": "confirm", "title": "Acquisition",
                               "message": "Use the acquisition found?", "cancel": False}


def test_the_answers_replay_the_dialogs_and_the_plugin_sets_the_values():
    assert run(Confirm, answers=[{"accept": True, "value": True}])["paramUpdates"] == {"voltage": 300}
    assert run(Confirm, answers=[{"accept": True, "value": False}])["paramUpdates"] == {}
    assert run(Confirm, answers=[{"accept": False}])["paramUpdates"] == {}


class Item:
    def __init__(self, name):
        self.name = name

    def get(self):
        return self.name


class PickLane:
    def show(self, form):
        from pyworkflow.gui.dialog import ListDialog
        from pyworkflow.gui.tree import ListTreeProviderString
        from pyworkflow.object import String
        provider = ListTreeProviderString([String("default"), String("gpu")])
        dlg = ListDialog(form.root, "Lanes display", provider, allowSelect=True)
        form.setVar("lane", dlg.values[0].get())


def test_list_dialogs_show_their_rows_and_take_the_selection():
    reply = run(PickLane)
    assert reply["dialog"]["type"] == "list"
    assert [row["text"] for row in reply["dialog"]["rows"]] == ["default", "gpu"]
    assert run(PickLane, answers=[{"accept": True, "selected": [1]}])["paramUpdates"] == {"lane": "gpu"}


def test_a_cancelled_dialog_the_plugin_does_not_check_ends_as_cancelled():
    # The desktop raises too when the list is cancelled (dlg.values[0]).
    assert run(PickLane, answers=[{"accept": False}])["status"] == "cancelled"


def test_an_unknown_dialog_is_unsupported():
    from pyworkflow.gui.dialog import Dialog

    class PluginDialog(Dialog):
        def __init__(self, parent):
            Dialog.__init__(self, parent, "Custom")

    class Custom:
        def show(self, form):
            PluginDialog(form.root)

    reply = run(Custom)
    assert reply["status"] == "unsupported" and reply["detail"] == "PluginDialog"


class Particle:
    def __init__(self, index):
        self._index = index

    def getSamplingRate(self):
        return 2.0

    def getDim(self):
        return (64, 64, 1)

    def getIndex(self):
        return self._index

    def getLocation(self):
        return self._index, "particles.stk"

    def getFileName(self):
        return "particles.stk"

    def getObjId(self):
        return self._index


def maskWizard(unit=None):
    from pwem.wizards.wizard import MaskRadiusWizard
    from pyworkflow.gui.tree import ListTreeProvider

    class Wizard(MaskRadiusWizard):
        def _getProvider(self, protocol):
            return ListTreeProvider([Particle(1), Particle(2)])

        def show(self, form):
            MaskRadiusWizard.show(self, form, form.protocol.radius.get(), "radius",
                                  **({"units": unit} if unit else {}))

    return Wizard


def test_preview_dialogs_take_the_values_and_the_plugin_converts_them(monkeypatch):
    from pwem.constants import UNIT_ANGSTROM
    reply = run(maskWizard(), answers=[{"accept": True, "values": {"radius": 20}}])
    assert reply["paramUpdates"] == {"radius": 20}
    # In Angstroms the wizard itself converts the pixels (2 A/px).
    reply = run(maskWizard(UNIT_ANGSTROM), answers=[{"accept": True, "values": {"radius": 20}}])
    assert reply["paramUpdates"] == {"radius": 40}


def test_preview_dialogs_are_described_with_their_controls_and_images(monkeypatch):
    monkeypatch.setattr(runtime.PreviewAdapter, "_images",
                        lambda self, kind, instance, obj, values, args: [{"src": "png:%s" % obj._index}])
    reply = run(maskWizard(), FakeProtocol(radius=-1))
    dialog = reply["dialog"]
    assert dialog["type"] == "preview" and dialog["previewKind"] == "mask_radius"
    assert [item["index"] for item in dialog["items"]] == [0, 1]
    # As MaskPreviewDialog: -1 is half the box, the slider goes up to half the box.
    assert dialog["controls"] == [{"name": "radius", "label": "Mask radius", "min": 1, "max": 32,
                                   "step": 1, "value": 32.0, "display": "pixels"}]
    assert dialog["rings"] == [{"image": 0, "outer": "radius", "scale": 1 / 64}]
    assert dialog["images"] == [{"src": "png:1"}]
    preview = run(maskWizard(), preview={"step": 0, "item": 1, "values": {"radius": 5}})
    assert preview["status"] == "preview" and preview["images"] == [{"src": "png:2"}]


def test_file_browsers_list_their_folder_and_select_inside_it(tmp_path):
    (tmp_path / "mtfs").mkdir()
    (tmp_path / "mtfs" / "k2.star").write_text("x")
    (tmp_path / "secret.txt").write_text("x")

    class MtfSelector:
        def show(self, form):
            from pyworkflow.gui.browser import FileBrowserWindow

            def setPath(fileInfo):
                form.setVar("mtf", fileInfo.getPath())

            FileBrowserWindow("Select an MTF", form, str(tmp_path / "mtfs"), onSelect=setPath).show()

    reply = run(MtfSelector)
    assert reply["dialog"]["type"] == "file" and reply["dialog"]["entries"] == ["k2.star"]
    done = run(MtfSelector, answers=[{"accept": True, "path": "k2.star"}])
    assert done["paramUpdates"] == {"mtf": str(tmp_path / "mtfs" / "k2.star")}
    # Nothing outside the folder the wizard offers.
    assert run(MtfSelector, answers=[{"accept": True, "path": "../secret.txt"}])["paramUpdates"] == {}


def test_plots_a_wizard_shows_are_kept_for_the_web():
    class Plot:
        def show(self, form):
            from pyworkflow.gui.plotter import Plotter
            plotter = Plotter(windowTitle="Defocus groups")
            plotter.createSubPlot("", "defocus", "count")
            plotter.show()

    reply = run(Plot)
    assert reply["status"] == "done" and len(reply["views"]) == 1


def test_a_failing_wizard_reports_its_error():
    class Broken:
        def show(self, form):
            raise ValueError("no input")

    assert run(Broken) == {"status": "failed", "error": "no input", "messages": []}


def test_the_desktop_dialogs_are_restored_after_the_run():
    from pyworkflow.gui import dialog
    before = dialog.ListDialog.__dict__["__init__"]
    run(PickLane)
    assert dialog.ListDialog.__dict__["__init__"] is before


def test_set_values_are_sent_as_the_web_form_stores_them():
    import numpy as np
    assert runtime.jsonValue(np.float32(1.5)) == 1.5
    assert runtime.jsonValue(np.int64(3)) == 3
    assert runtime.jsonValue(Value("abc")) == "abc"
    assert runtime.jsonValue(float("nan")) is None
