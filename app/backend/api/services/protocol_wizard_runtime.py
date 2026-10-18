"""Protocol form wizards run as on the desktop, with their dialogs on the web.

A desktop wizard is a ``Wizard.show(form)`` that reads the protocol, maybe
opens dialogs, and writes values with ``form.setVar(param, value)``. Here the
wizard's own ``show()`` runs with a form without a window (``HeadlessForm``)
and with the dialogs replaced by stand-ins (``capturedWizardUi``):

* ``setVar`` calls are recorded: they become the param updates of the web form.
* Message dialogs (showInfo/showWarning/showError) are recorded and continue.
* Any other dialog stops the run and is described to the web (pass 1). The web
  asks the user and runs the wizard again with the answers (pass 2): each dialog
  then takes its answer, so the plugin code reads the values and converts them
  (units, formats) itself, as on the desktop.

Dialogs block inside their constructor on the desktop, and plugins import the
dialog classes by name, so the constructors are replaced at class level.
"""
from __future__ import annotations

import base64
import inspect
import io
import os
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

MAX_LIST_ROWS = 2000
MAX_LIST_COLUMNS = 32
MAX_STRING = 2048
MAX_MESSAGES = 32
MAX_FILE_ENTRIES = 1000
PREVIEW_DIM = 256

# Dialog results, as pyworkflow.gui.dialog defines them.
RESULT_YES = 0
RESULT_NO = 1
RESULT_CANCEL = 2


class WizardStop(Exception):
    """Ends the wizard run with a reply for the web (a dialog to show, a preview...)."""

    def __init__(self, reply: Dict[str, Any]):
        super().__init__(reply.get("status"))
        self.reply = reply


def _text(value, limit=MAX_STRING) -> str:
    return "" if value is None else str(value)[:limit]


def jsonValue(value):
    """A setVar value as the web form stores it."""
    try:
        import numpy as np
        if isinstance(value, np.generic):
            value = value.item()
    except ImportError:
        pass
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    try:
        from pyworkflow.object import Pointer
        if isinstance(value, Pointer):
            parent = value.getObjValue()
            parentId = parent.getObjId() if parent is not None else None
            if parentId is None:
                return None
            extended = value.getExtended()
            return "%s.%s" % (parentId, extended) if extended else str(parentId)
    except ImportError:
        pass
    if hasattr(value, "get") and callable(value.get):
        return jsonValue(value.get())
    return str(value)


class _Var:
    """Stands in for a Tk variable or entry: ``get()`` returns the answer."""

    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Slider(_Var):
    """Stands in for pyworkflow's LabelSlider (``get()`` and ``slider.set()``)."""

    def __init__(self, value):
        super().__init__(value)
        self.slider = self

    def highlightLabel(self):
        pass

    def removeHighlightFromLabel(self):
        pass


class _FileInfo:
    """What FileBrowserWindow hands to its onSelect callback."""

    def __init__(self, path):
        self._path = path

    def getPath(self):
        return self._path

    def getFileName(self):
        return os.path.basename(self._path)

    def isDir(self):
        return os.path.isdir(self._path)


class WizardSession:
    """One run of a wizard: the answers so far, and what the run produced."""

    def __init__(self, answers: Optional[List[Any]] = None, preview: Optional[Dict[str, Any]] = None):
        self.answers = list(answers or [])
        self.preview = preview
        self.step = 0
        self.updates: Dict[str, Any] = {}
        self.messages: List[Dict[str, str]] = []
        self.views: List[Any] = []
        self.lastAnswerCancelled = False

    def addMessage(self, level, text, title=""):
        if len(self.messages) < MAX_MESSAGES:
            self.messages.append({"level": level, "title": _text(title, 160), "text": _text(text)})

    def ask(self, adapter, instance, params):
        """A dialog opens: answer it (pass 2) or stop to ask the web (pass 1)."""
        step = self.step
        self.step += 1
        if step < len(self.answers):
            answer = self.answers[step] if isinstance(self.answers[step], dict) else {}
            accepted = bool(answer.get("accept"))
            self.lastAnswerCancelled = not accepted
            instance.result = RESULT_CANCEL
            adapter.answer(instance, params, answer if accepted else None)
            return
        if self.preview is not None and self.preview.get("step") == step:
            raise WizardStop({"status": "preview", "step": step,
                              "images": adapter.preview(instance, params, self.preview)})
        raise WizardStop({"status": "dialog", "step": step,
                          "dialog": adapter.describe(instance, params)})


class HeadlessForm:
    """The protocol form a wizard receives, without a window.

    Like the desktop FormWindow: ``protocol`` holds the current form values,
    and ``setVar`` writes both the form value and the protocol attribute, so
    the rest of ``show()`` reads what it just wrote.
    """

    def __init__(self, protocol, paramName: str, session: WizardSession):
        self.protocol = protocol
        self.wizParamName = paramName
        self.root = None
        self._session = session

    def setVar(self, paramName, value):
        self._session.updates[str(paramName)] = jsonValue(value)
        attribute = getattr(self.protocol, str(paramName), None)
        if attribute is None:
            return
        try:
            from pyworkflow.object import Pointer
            if isinstance(value, Pointer) and isinstance(attribute, Pointer):
                attribute.copy(value)
            elif hasattr(attribute, "set"):
                attribute.set(value)
        except Exception:
            pass  # The value still reaches the web form.

    def getRoot(self):
        return None

    def _message(level):
        def show(self, msg="", header="", *args, **kwargs):
            self._session.addMessage(level, msg, header or kwargs.get("title", ""))
        return show

    showInfo = _message("info")
    showWarning = _message("warning")
    showError = _message("error")
    del _message


# ------------------------------------------------------------------------------
# Images
# ------------------------------------------------------------------------------

def arrayToPng(data) -> str:
    """A 2D array as a PNG data URL, scaled to its range like matplotlib's imshow."""
    import numpy as np
    from PIL import Image

    array = np.squeeze(np.asarray(data, dtype=np.float64))
    while array.ndim > 2:
        array = array[array.shape[0] // 2]
    finite = array[np.isfinite(array)]
    low, high = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    scaled = np.zeros_like(array) if high <= low else (array - low) / (high - low)
    pixels = (np.nan_to_num(scaled) * 255).clip(0, 255).astype(np.uint8)
    # Images are shown with the origin at the bottom, as matplotlib's extent does.
    buffer = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(pixels[::-1])).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _xmippImage():
    from pwem.emlib.image import ImageHandler
    return ImageHandler()._img


def _itemFileName(obj) -> str:
    from pwem.emlib.image import ImageHandler
    fileName = ImageHandler.fixXmippVolumeFileName(obj)
    index = obj.getIndex()
    return "%03d@%s" % (index, fileName) if index else fileName


def itemPreview(obj, dim=PREVIEW_DIM):
    """The left image of the desktop preview dialogs (ImagePreviewDialog)."""
    image = _xmippImage()
    fileName = _itemFileName(obj)
    image.readPreview(fileName, dim)
    if fileName.endswith(".psd"):
        image.convertPSD()
    return image.getData()


# ------------------------------------------------------------------------------
# Dialog adapters: describe a dialog for the web, and answer it in pass 2
# ------------------------------------------------------------------------------

class DialogAdapter:
    kind = "unsupported"

    def describe(self, instance, params) -> Dict[str, Any]:
        return {"type": "unsupported", "dialogClass": type(instance).__name__,
                "title": _text(params.get("title"), 160)}

    def answer(self, instance, params, answer) -> None:
        pass

    def preview(self, instance, params, request) -> List[Dict[str, Any]]:
        return []


class UnsupportedDialogAdapter(DialogAdapter):
    def describe(self, instance, params):
        raise WizardStop({"status": "unsupported", "reason": "dialog",
                          "detail": type(instance).__name__})


class ConfirmAdapter(DialogAdapter):
    """YesNoDialog (askYesNo / askYesNoCancel)."""

    def describe(self, instance, params):
        return {"type": "confirm", "title": _text(params.get("title"), 160),
                "message": _text(params.get("msg")),
                "cancel": bool((params.get("kwargs") or {}).get("showCancel"))}

    def answer(self, instance, params, answer):
        if answer is None:
            instance.result = (RESULT_CANCEL if (params.get("kwargs") or {}).get("showCancel")
                               else RESULT_NO)
        else:
            instance.result = RESULT_YES if answer.get("value", True) else RESULT_NO


class ChoiceAdapter(DialogAdapter):
    """GenericDialog with its own buttons (e.g. askSingleAllCancel)."""

    def _buttons(self, params):
        kwargs = params.get("kwargs") or {}
        return [(str(label), value) for label, value in kwargs.get("buttons") or []]

    def describe(self, instance, params):
        return {"type": "choice", "title": _text(params.get("title"), 160),
                "message": _text(params.get("msg")),
                "buttons": [{"label": label, "value": index}
                            for index, (label, _) in enumerate(self._buttons(params))]}

    def answer(self, instance, params, answer):
        buttons = self._buttons(params)
        index = answer.get("value") if answer else None
        if isinstance(index, int) and 0 <= index < len(buttons):
            instance.result = buttons[index][1]


class EntryAdapter(DialogAdapter):
    """EntryDialog (askString)."""

    def describe(self, instance, params):
        return {"type": "form", "title": _text(params.get("title"), 160),
                "message": _text(params.get("headerLabel")),
                "fields": [{"name": "value", "label": _text(params.get("entryLabel"), 160),
                            "kind": "text", "value": _text(params.get("defaultValue"))}]}

    def answer(self, instance, params, answer):
        instance.value = None
        if answer is not None:
            instance.value = str((answer.get("values") or {}).get("value", ""))
            instance.result = RESULT_YES


def _serializeTree(provider, limit=MAX_LIST_ROWS):
    """A TreeProvider's columns and rows, as its tree would show them."""
    columns = [_text(column[0] if isinstance(column, (list, tuple)) else column, 160)
               for column in (provider.getColumns() or [])][:MAX_LIST_COLUMNS]
    objects = list(provider.getObjects() or [])
    rows = []
    for index, obj in enumerate(objects[:limit]):
        info = provider.getObjectInfo(obj) or {}
        values = [_text(value, 256) for value in (info.get("values") or ())]
        rows.append({"index": index, "text": _text(info.get("text"), 256),
                     "values": values[:MAX_LIST_COLUMNS]})
    return columns, rows, objects


class ListAdapter(DialogAdapter):
    """ListDialog / ToolbarListDialog with a TreeProvider."""

    def describe(self, instance, params):
        kwargs = params.get("kwargs") or {}
        columns, rows, objects = _serializeTree(params["provider"])
        return {"type": "list", "title": _text(params.get("title"), 160),
                "message": _text(params.get("message")),
                "columns": columns, "rows": rows, "truncated": len(objects) > len(rows),
                "multiple": kwargs.get("selectmode", "extended") == "extended",
                "allowEmpty": bool(kwargs.get("allowsEmptySelection", False))}

    def answer(self, instance, params, answer):
        instance.values = []
        if answer is None:
            return
        objects = list(params["provider"].getObjects() or [])
        selected = [index for index in answer.get("selected") or []
                    if isinstance(index, int) and 0 <= index < len(objects)]
        instance.values = [objects[index] for index in selected]
        instance.result = RESULT_YES


class ColorScaleAdapter(DialogAdapter):
    def describe(self, instance, params):
        try:
            import matplotlib.pyplot as plt
            palettes = sorted(plt.colormaps())
        except Exception:
            palettes = []
        return {"type": "form", "title": "Color scale wizard", "message": "",
                "fields": [
                    {"name": "lowest", "label": "Lowest", "kind": "number", "value": params.get("lowest")},
                    {"name": "highest", "label": "Highest", "kind": "number", "value": params.get("highest")},
                    {"name": "intervals", "label": "Intervals", "kind": "number", "step": 1,
                     "value": params.get("intervals")},
                    {"name": "colorPalette", "label": "Color set", "kind": "select",
                     "value": params.get("colorPalette"), "options": palettes},
                ]}

    def answer(self, instance, params, answer):
        values = (answer or {}).get("values") or {}
        for name in ("lowest", "highest", "intervals", "colorPalette"):
            setattr(instance, name, _Var(values.get(name, params.get(name))))
        if answer is not None:
            instance.result = RESULT_YES


class FormulaAdapter(DialogAdapter):
    def describe(self, instance, params):
        attributes = []
        try:
            item = params["set"].getFirstItem()
            for name, _ in item.getAttributesToStore():
                attributes.append("item." + name)
        except Exception:
            pass
        return {"type": "form", "title": "Formula wizard",
                "message": "Write a Python expression; 'item' is each element of the set.",
                "fields": [{"name": "formula", "label": "Formula", "kind": "text",
                            "value": _text(params.get("formula")), "suggestions": attributes[:200]}]}

    def answer(self, instance, params, answer):
        values = (answer or {}).get("values") or {}
        instance.formula = _Var(str(values.get("formula", params.get("formula") or "")))
        instance.set = params.get("set")
        try:
            instance.item = params["set"].getFirstItem()
        except Exception:
            instance.item = None
        if answer is not None:
            instance.result = RESULT_YES


# --- Preview dialogs (pwem.wizards.wizard.PreviewDialog and subclasses) --------

PREVIEW_KINDS = (
    # Most specific first: the first class name in a dialog's MRO wins.
    ("MaskRadiiPreviewDialog", "mask_radii"),
    ("MaskPreviewDialog", "mask_radius"),
    ("CtfDownsampleDialog", "ctf_downsample"),
    ("CtfDialog", "ctf"),
    ("GaussianFilterDialog", "gaussian"),
    ("BandPassFilterDialog", "band_pass"),
    ("DownsampleDialog", "downsample"),
    ("ImagePreviewDialog", "image"),
)


def previewKind(instance) -> Optional[str]:
    names = [cls.__name__ for cls in type(instance).__mro__]
    for className, kind in PREVIEW_KINDS:
        if className in names:
            return kind
    return None


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if number == number else default
    except (TypeError, ValueError):
        return default


class PreviewAdapter(DialogAdapter):
    """Item list, preview images and controls, as the desktop preview dialogs.

    Initial values and ranges follow the desktop dialogs; images come from the
    same Xmipp functions (readPreview, fastEstimateEnhancedPSD, bandPassFilter,
    gaussianFilter).
    """

    def _setup(self, instance, params):
        args = dict(params.get("args") or {})
        for key, value in args.items():
            setattr(instance, key, value)
        provider = params["provider"]
        instance.provider = provider
        objects = list(provider.getObjects() or [])
        instance.firstItem = objects[0] if objects else None
        return args, objects

    def _controls(self, kind, instance, args) -> Dict[str, Any]:
        """Initial values, ranges and overlays of each kind of dialog."""
        first = instance.firstItem
        unit = args.get("unit")
        controls: List[Dict[str, Any]] = []
        rings: List[Dict[str, Any]] = []
        samplingRate = _number(first.getSamplingRate(), 1.0) if first is not None else 1.0
        dim = int(first.getDim()[0]) if first is not None and first.getDim() else 1
        angstrom = unit == _angstromUnit()
        if kind in ("mask_radius", "mask_radii"):
            maximum = max(1, int(dim / 2))
            if kind == "mask_radius":
                radius = args.get("maskRadius", -1)
                radius = dim / 2 if radius == -1 else _number(radius, dim / 2)
                if angstrom:
                    radius = radius / samplingRate
                controls.append({"name": "radius", "label": "Mask radius", "min": 1, "max": maximum,
                                 "step": 1, "value": radius, "display": "pixels"})
                rings.append({"image": 0, "outer": "radius", "scale": 1.0 / dim})
            else:
                inner, outer = args.get("innerRadius"), args.get("outerRadius")
                inner = 1 if inner is None else _number(inner, 1)
                if outer is None or outer == -1 or outer > dim / 2:
                    outer = maximum
                if angstrom:
                    inner, outer = inner / samplingRate, _number(outer) / samplingRate
                controls += [
                    {"name": "outerRadius", "label": "Outer radius", "min": 1, "max": maximum,
                     "step": 1, "value": outer, "display": "pixels"},
                    {"name": "innerRadius", "label": "Inner radius", "min": 1, "max": maximum,
                     "step": 1, "value": inner, "display": "pixels"},
                ]
                rings.append({"image": 0, "outer": "outerRadius", "inner": "innerRadius",
                              "scale": 1.0 / dim})
        if kind in ("downsample", "ctf_downsample"):
            controls.append({"name": "downsample", "label": "Downsample", "kind": "number",
                             "value": _number(args.get("downsample", 1), 1), "refresh": True})
        if kind in ("ctf", "ctf_downsample"):
            controls += [
                {"name": "lowFreq", "label": "Low freq", "min": 0.01, "max": 0.5, "step": 0.01,
                 "value": _number(args.get("lf"), 0.01), "display": "frequency"},
                {"name": "highFreq", "label": "High freq", "min": 0.01, "max": 0.5, "step": 0.01,
                 "value": _number(args.get("hf"), 0.5), "display": "frequency"},
            ]
            rings.append({"image": 1, "outer": "highFreq", "inner": "lowFreq", "scale": 1.0})
        if kind == "band_pass":
            low, high = 0.01, 0.5
            if angstrom:
                low, high = 2.0 * samplingRate, 2.0 * dim * samplingRate
            step = high / 1000
            for name, label, flag, key in (("lowFreq", "Low freq", "showLowFreq", "lowFreq"),
                                           ("highFreq", "High freq", "showHighFreq", "highFreq"),
                                           ("freqDecay", "Decay", "showDecay", "freqDecay")):
                if args.get(flag, True):
                    single = not (args.get("showLowFreq", True) and args.get("showHighFreq", True))
                    controls.append({"name": name, "label": "Freq" if single and name != "freqDecay" else label,
                                     "min": low, "max": high, "step": step, "refresh": True,
                                     "value": _number(args.get(key), low),
                                     # In Angstroms the desktop slider runs from high to low.
                                     "reversed": angstrom,
                                     "display": "angstrom" if angstrom else "frequency"})
        if kind == "gaussian":
            controls.append({"name": "freqSigma", "label": "Frequency sigma", "kind": "number",
                             "value": _number(args.get("freqSigma", 1), 1), "refresh": True})
        return {"controls": controls, "rings": rings, "samplingRate": samplingRate,
                "itemDim": dim, "unit": _text(unit, 32)}

    def describe(self, instance, params):
        kind = previewKind(instance)
        args, objects = self._setup(instance, params)
        if not objects:
            raise WizardStop({"status": "unsupported", "reason": "empty_input"})
        columns, rows, _ = _serializeTree(params["provider"])
        layout = self._controls(kind, instance, args)
        values = {control["name"]: control["value"] for control in layout["controls"]}
        labels = {"downsample": ["Micrograph", "PSD"], "ctf": ["Micrograph", "PSD"],
                  "ctf_downsample": ["Micrograph", "PSD"], "band_pass": ["Image", "Filtered"],
                  "gaussian": ["Image", "Filtered"]}.get(kind, ["Central slice" if kind and kind.startswith("mask")
                                                                else "Image"])
        try:
            images = self._images(kind, instance, objects[0], values, args)
        except Exception as exc:
            images = []
            layout["previewError"] = _text(exc, 300)
        return {"type": "preview", "previewKind": kind, "dialogClass": type(instance).__name__,
                "title": "Wizard", "columns": columns, "items": rows,
                "imageLabels": labels, "images": images, **layout}

    def _images(self, kind, instance, obj, values, args) -> List[Dict[str, Any]]:
        from pwem import emlib
        left = itemPreview(obj)
        images = [{"src": arrayToPng(left), "width": int(left.shape[-1]), "height": int(left.shape[-2])}]
        right = None
        if kind in ("downsample", "ctf_downsample", "ctf"):
            right = _xmippImage()
            downsample = 1.0 if kind == "ctf" else _number(values.get("downsample"), 1.0)
            emlib.fastEstimateEnhancedPSD(right, obj.getFileName(), downsample, PREVIEW_DIM, 2)
        elif kind == "band_pass":
            right = _xmippImage()
            low, high, decay = self._bandPassFrequencies(instance, values, args)
            emlib.bandPassFilter(right, _location(obj), low, high, decay, PREVIEW_DIM)
        elif kind == "gaussian":
            right = _xmippImage()
            emlib.gaussianFilter(right, _location(obj), _number(values.get("freqSigma"), 1.0), PREVIEW_DIM)
        if right is not None:
            data = right.getData()
            images.append({"src": arrayToPng(data), "width": int(data.shape[-1]),
                           "height": int(data.shape[-2])})
        return images

    def _bandPassFrequencies(self, instance, values, args):
        """Digital frequencies, as BandPassFilterDialog.getLowFreq... return them."""
        angstrom = args.get("unit") == _angstromUnit()
        samplingRate = _number(instance.firstItem.getSamplingRate(), 1.0) if angstrom else 1.0

        def frequency(name, flag, default):
            if not args.get(flag, True):
                return default
            value = _number(values.get(name), default)
            return samplingRate / value if angstrom and value else value

        return (frequency("lowFreq", "showLowFreq", 0.01), frequency("highFreq", "showHighFreq", 1.0),
                frequency("freqDecay", "showDecay", 0.01))

    def preview(self, instance, params, request):
        kind = previewKind(instance)
        args, objects = self._setup(instance, params)
        index = request.get("item", 0)
        if not isinstance(index, int) or not 0 <= index < len(objects):
            index = 0
        values = request.get("values") if isinstance(request.get("values"), dict) else {}
        return self._images(kind, instance, objects[index], values, args)

    def answer(self, instance, params, answer):
        kind = previewKind(instance)
        args, objects = self._setup(instance, params)
        layout = self._controls(kind, instance, args)
        values = {control["name"]: control["value"] for control in layout["controls"]}
        if answer is not None:
            for name, value in (answer.get("values") or {}).items():
                if name in values:
                    values[name] = _number(value, values[name])
        # What the desktop dialogs' getters read.
        instance.samplingRate = layout["samplingRate"] if kind != "band_pass" else (
            layout["samplingRate"] if args.get("unit") == _angstromUnit() else 1.0)
        instance.radiusSlider = _Slider(values.get("radius", 1))
        instance.radiusSliderIn = _Slider(values.get("innerRadius", 1))
        instance.radiusSliderOut = _Slider(values.get("outerRadius", 1))
        instance.downVar = _Var(str(values.get("downsample", args.get("downsample", 1))))
        instance.lfSlider = _Slider(values.get("lowFreq", 0.01))
        instance.hfSlider = _Slider(values.get("highFreq", 0.5))
        instance.freqDecaySlider = _Slider(values.get("freqDecay", 0.01))
        instance.freqVar = _Var(str(values.get("freqSigma", args.get("freqSigma", 1))))
        instance.lf, instance.hf = values.get("lowFreq", 0.01), values.get("highFreq", 0.5)
        instance.showLowFreq = args.get("showLowFreq", True)
        instance.showHighFreq = args.get("showHighFreq", True)
        instance.showDecay = args.get("showDecay", True)
        if answer is not None:
            instance.result = RESULT_YES


def _angstromUnit():
    try:
        from pwem.constants import UNIT_ANGSTROM
        return UNIT_ANGSTROM
    except ImportError:
        return "Å"


def _location(obj):
    from pwem.emlib.image import ImageHandler
    return ImageHandler.locationToXmipp(obj)


# --- Windows that are not dialogs ---------------------------------------------

def _listFiles(root: str):
    entries = []
    for folder, dirs, files in os.walk(root):
        dirs.sort()
        relative = os.path.relpath(folder, root)
        depth = 0 if relative == "." else relative.count(os.sep) + 1
        if depth >= 3:
            dirs[:] = []
        for name in sorted(files):
            if len(entries) >= MAX_FILE_ENTRIES:
                return entries, True
            entries.append(os.path.normpath(os.path.join(relative, name)))
    return entries, False


def fileInRoot(root: str, relative) -> Optional[str]:
    if not isinstance(relative, str) or not relative:
        return None
    path = os.path.realpath(os.path.join(root, relative))
    base = os.path.realpath(root)
    return path if path.startswith(base + os.sep) and os.path.exists(path) else None


def _volumePreviewUint8(volume, maxDim=64):
    """The volume binned to at most maxDim per side, 1-99 percentiles as 0-255."""
    import numpy as np
    factor = int(np.ceil(max(volume.shape) / float(maxDim)))
    if factor > 1:
        z, y, x = (size // factor * factor for size in volume.shape)
        volume = volume[:z, :y, :x].reshape(z // factor, factor, y // factor, factor,
                                            x // factor, factor).mean(axis=(1, 3, 5))
    finite = volume[np.isfinite(volume)]
    if not finite.size:
        return np.zeros(volume.shape, dtype=np.uint8)
    low, high = float(np.percentile(finite, 1.0)), float(np.percentile(finite, 99.0))
    if high <= low:
        low, high = float(finite.min()), float(finite.max())
    if high <= low:
        return np.zeros(volume.shape, dtype=np.uint8)
    return (255.0 * (np.clip(np.nan_to_num(volume, nan=low), low, high) - low) / (high - low)).astype(np.uint8)


def describeVolumePoint(fileName: str, point) -> Dict[str, Any]:
    """The 3D point picker (pwem's MaskVolumeWizard) as the web's point dialog reads it.

    The point is relative to the volume center, (z, y, x) as MaskVolumeWizard.origin.
    """
    import numpy as np
    from pwem.emlib.image import ImageHandler

    volume = np.squeeze(np.asarray(ImageHandler().read(fileName).getData(), dtype=np.float32))
    dims = [int(size) for size in volume.shape]
    preview = _volumePreviewUint8(volume)
    current = {"x": float(point[2]), "y": float(point[1]), "z": float(point[0])}
    voxel = {axis: min(max(current[axis] + 0.5 * dims[index], 0.0), float(dims[index] - 1))
             for axis, index in (("x", 2), ("y", 1), ("z", 0))}
    return {
        "type": "point_in_volume", "title": "Select a point in the volume",
        "dims": dims, "previewDims": [int(size) for size in preview.shape],
        "previewValues": preview.ravel(order="C").astype(np.uint8).tolist(),
        "axisOrder": ["z", "y", "x"], "point": current, "pointVoxel": voxel,
        "bounds": {"xMin": -0.5 * dims[2], "xMax": 0.5 * dims[2], "yMin": -0.5 * dims[1],
                   "yMax": 0.5 * dims[1], "zMin": -0.5 * dims[0], "zMax": 0.5 * dims[0]},
    }


# ------------------------------------------------------------------------------
# Capture
# ------------------------------------------------------------------------------

def _all_subclasses(cls):
    seen, pending = [], [cls]
    while pending:
        current = pending.pop()
        for sub in current.__subclasses__():
            if sub not in seen:
                seen.append(sub)
                pending.append(sub)
    return seen


def _adapterFor(instance):
    names = [cls.__name__ for cls in type(instance).__mro__]
    if previewKind(instance) is not None:
        return PreviewAdapter()
    for className, adapter in (("ColorScaleDialog", ColorScaleAdapter), ("FormulaDialog", FormulaAdapter),
                               ("ListDialog", ListAdapter), ("YesNoDialog", ConfirmAdapter),
                               ("EntryDialog", EntryAdapter), ("GenericDialog", ChoiceAdapter)):
        if className in names:
            return adapter()
    return UnsupportedDialogAdapter()


def _messageLevel(instance, params) -> Optional[str]:
    names = [cls.__name__ for cls in type(instance).__mro__]
    if "YesNoDialog" in names:
        return None
    if "ExceptionDialog" in names:
        return "error"
    if "MessageDialog" in names:
        icon = str(params.get("iconPath") or "").lower()
        return "warning" if "alert" in icon or "warn" in icon else ("error" if "error" in icon else "info")
    return None


def _isDisplayView(cls, viewBase) -> bool:
    """Views that only display (plots, data, text) are captured; a plugin's own
    View subclass may open a dialog in show() (e.g. cryoSPARC's lanes list)."""
    for klass in cls.__mro__:
        if klass is viewBase:
            return False
        module = getattr(klass, "__module__", "") or ""
        if module.startswith(("pyworkflow.", "pwem.")):
            return True
    return False


@contextmanager
def capturedWizardUi(session: WizardSession):
    """Replace the desktop dialogs and windows by the session's stand-ins."""
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from pyworkflow.gui import dialog as dialogModule
    from pyworkflow.viewer import View

    patched = []

    def patch(cls, name, value):
        patched.append((cls, name, cls.__dict__.get(name)))
        setattr(cls, name, value)

    originals = {}
    for cls in [dialogModule.Dialog] + _all_subclasses(dialogModule.Dialog):
        if "__init__" in cls.__dict__:
            originals[cls] = cls.__dict__["__init__"]

    def _hasPositionalCatchAll(function):
        return any(parameter.kind == parameter.VAR_POSITIONAL
                   for parameter in inspect.signature(function).parameters.values())

    def dialogInit(instance, *args, **kwargs):
        # The constructor the call was meant for; one taking just (*args,
        # **kwargs) (e.g. ExceptionDialog) passes them on to its parent's.
        owners = [cls for cls in type(instance).__mro__ if cls in originals]
        owner = next((cls for cls in owners if not _hasPositionalCatchAll(originals[cls])), owners[0])
        try:
            bound = inspect.signature(originals[owner]).bind(instance, *args, **kwargs)
            params = dict(bound.arguments)
        except TypeError:
            params = {"args": args, "kwargs": kwargs}
        for name, parameter in inspect.signature(originals[owner]).parameters.items():
            if parameter.kind == parameter.VAR_KEYWORD:
                params.setdefault(name, {})
        params.setdefault("kwargs", params.get("args") if isinstance(params.get("args"), dict) else {})
        instance.result = RESULT_YES
        level = _messageLevel(instance, params)
        if level is not None:
            session.addMessage(level, params.get("msg"), params.get("title"))
            return
        session.ask(_adapterFor(instance), instance, params)

    for cls in originals:
        patch(cls, "__init__", dialogInit)

    # The message helpers too (they may have been replaced in this process).
    moduleFunctions = []
    for name, level in (("showInfo", "info"), ("showWarning", "warning"), ("showError", "error")):
        def showMessage(title="", msg="", *args, _level=level, **kwargs):
            session.addMessage(_level, msg, title)
        moduleFunctions.append((name, getattr(dialogModule, name)))
        setattr(dialogModule, name, showMessage)

    # Views that display results (plots, data...) are kept for the web.
    def captureView(view, *args, **kwargs):
        session.views.append(view)

    for cls in _all_subclasses(View):
        if "show" in cls.__dict__ and _isDisplayView(cls, View):
            patch(cls, "show", captureView)
    originalPltShow = plt.show

    def pltShow(*args, **kwargs):
        for number in plt.get_fignums():
            session.views.append(plt.figure(number))

    plt.show = pltShow

    # The file browser window (e.g. Relion's MTF selector, askPath).
    try:
        from pyworkflow.gui.browser import FileBrowserWindow
    except Exception:
        FileBrowserWindow = None
    if FileBrowserWindow is not None:
        def browserInit(window, title, master=None, path=None, onSelect=None, shortCuts=None, **kwargs):
            window._webTitle, window._webRoot, window._webOnSelect = title, path or ".", onSelect
            window._webOnlyFolders = bool(kwargs.get("onlyFolders"))
            window._webSelection = None

        def browserShow(window, *args, **kwargs):
            session.ask(FileBrowserAdapter(), window, {})

        def browserSelection(window):
            return window._webSelection

        patch(FileBrowserWindow, "__init__", browserInit)
        patch(FileBrowserWindow, "show", browserShow)
        patch(FileBrowserWindow, "getLastSelection", browserSelection)

    # The 3D point picker of pwem (MaskVolumeWizard).
    try:
        from pwem.wizards.wizards_3d.mask_volume_wizard import MaskVolumeWizard
    except Exception:
        MaskVolumeWizard = None
    if MaskVolumeWizard is not None:
        def volumeInit(window, filename):
            import numpy as np
            window._webFileName = filename
            window.origin = np.array((0, 0, 0))

        def volumePlot(window, *args, **kwargs):
            session.ask(VolumePointAdapter(), window, {})

        patch(MaskVolumeWizard, "__init__", volumeInit)
        patch(MaskVolumeWizard, "initializePlot", volumePlot)
    try:
        yield session
    finally:
        plt.show = originalPltShow
        for name, function in moduleFunctions:
            setattr(dialogModule, name, function)
        for cls, name, original in reversed(patched):
            if original is None:
                try:
                    delattr(cls, name)
                except AttributeError:
                    pass
            else:
                setattr(cls, name, original)


class FileBrowserAdapter(DialogAdapter):
    def describe(self, window, params):
        root = window._webRoot
        entries, truncated = _listFiles(root) if os.path.isdir(root) else ([], False)
        return {"type": "file", "title": _text(window._webTitle, 160), "root": os.path.basename(root),
                "entries": entries, "truncated": truncated, "onlyFolders": window._webOnlyFolders}

    def answer(self, window, params, answer):
        path = fileInRoot(window._webRoot, (answer or {}).get("path"))
        if path is None:
            return
        window._webSelection = path
        if window._webOnSelect is not None:
            window._webOnSelect(_FileInfo(path))


class VolumePointAdapter(DialogAdapter):
    def describe(self, window, params):
        return describeVolumePoint(window._webFileName, window.origin)

    def answer(self, window, params, answer):
        import numpy as np
        point = (answer or {}).get("point") or {}
        if answer is not None:
            window.origin = np.array((_number(point.get("z")), _number(point.get("y")),
                                      _number(point.get("x"))))


def runWizard(wizardClass, protocol, paramName: str, answers=None, preview=None) -> Dict[str, Any]:
    """Run the wizard's own show() and return what it did, or what it asks."""
    session = WizardSession(answers, preview)
    form = HeadlessForm(protocol, paramName, session)
    try:
        with capturedWizardUi(session):
            wizard = wizardClass()
            try:
                wizard.show(form)
            except WizardStop:
                raise
            except Exception as exc:
                if session.lastAnswerCancelled and not session.updates:
                    # e.g. a cancelled list read as dlg.values[0], as on the desktop.
                    return {"status": "cancelled", "messages": session.messages}
                import sys
                import traceback
                traceback.print_exc(file=sys.stderr)
                return {"status": "failed", "error": _text(exc) or type(exc).__name__,
                        "messages": session.messages}
    except WizardStop as stop:
        reply = dict(stop.reply)
        reply.setdefault("messages", session.messages)
        return reply
    return {"status": "done", "paramUpdates": session.updates, "messages": session.messages,
            "views": session.views}
