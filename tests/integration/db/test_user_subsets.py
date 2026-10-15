"""Web id selections read stored inputs directly and keep their subset output."""
import os

import pytest
from pwem import objects as emobj

from tests.integration.db.test_stored_set_copies import (  # noqa: F401 (fixture)
    _Param, _acquisition, _particles, copyContext, SAMPLING_RATE)

STORED_COLUMNS = ("scipionItemId", "enabled", "label", "comment", "creation", "values")


def _rows(db, setId):
    return [tuple(row[key] for key in STORED_COLUMNS) for row in db.fetchAll(
        'SELECT * FROM scipion_set_items WHERE "setId" = %s ORDER BY "scipionItemId"', (setId,))]


def _childRows(db, setId):
    return [(row["parentItemId"],) + tuple(row[key] for key in STORED_COLUMNS) for row in db.fetchAll(
        'SELECT ti.* FROM scipion_set_table_items ti JOIN scipion_set_tables t ON t.id = ti."tableId" '
        'WHERE t."setId" = %s AND t."tableKind" = \'child\' ORDER BY ti."parentItemId", ti."scipionItemId"',
        (setId,))]


def _classes(ctx, particles, classesCount):
    classes = emobj.SetOfClasses2D()
    classes.setImages(particles)
    classes, info = ctx["reserve"](classes)

    def assign(item, row):
        item.setClassId(item.getObjId() % classesCount + 1)
        if item.getObjId() % 9 == 0:
            item.setEnabled(False)

    classes.classifyItems(updateItemCallback=assign)
    return ctx["finalize"](classes, info)


def _runSubset(ctx, tmp_path, inputSet, ids, outputClassName, prefix="", direct=True):
    from pwem.protocols.protocol_batch import ProtUserSubSet

    selection = tmp_path / ("selection_%s.txt" % ("direct" if direct else "file"))
    selection.write_text(" ".join(str(i) for i in ids) + " ")

    class SubsetRun:
        def __init__(self):
            self._selectedIds = None
            self._dbName = None
            self._selectionTxt = None
            self._storedInput = None
            self.inputObject = _Param(inputSet)
            self.other = _Param("")
            self.sqliteFile = _Param("%s,%s" % (selection, prefix))
            self.outputClassName = _Param(outputClassName)
            self.summaryVar = _Param("")
            self.summaryVar.set = lambda value: None
            self.outputs = {}
            self.messages = []

        def _getPath(self, *paths):
            return os.path.join(str(tmp_path), *paths)

        def info(self, message):
            self.messages.append(str(message))

        def _defineOutput(self, className, output):
            self.outputs[className] = output

        def _defineOutputs(self, **outputs):
            self.outputs.update(outputs)

        def _defineTransformRelation(self, *args):
            pass

        _defineSourceRelation = _defineCtfRelation = _defineTransformRelation

    for name, value in vars(ProtUserSubSet).items():
        if ((callable(value) or isinstance(value, (staticmethod, classmethod)))
                and name != "__init__" and name not in vars(SubsetRun)):
            setattr(SubsetRun, name, value)
    if not direct:
        SubsetRun._readsInputDirectly = lambda self: False

    for setClassName in ("SetOfParticles", "SetOfClasses2D", "SetOfAverages", "SetOfMicrographs", "SetOfCTF"):
        def create(self, _name=setClassName, **kwargs):
            output, info = ctx["reserve"](getattr(emobj, _name)())
            output._testInfo = info
            return output
        setattr(SubsetRun, "_create" + setClassName, create)

    run = SubsetRun()
    run.createSetStep()
    result = {}
    for name, output in run.outputs.items():
        output.write()
        result[name] = output
    return run, result


def _stored(db, outputs):
    return {name: (_rows(db, int(output._testInfo["setId"])), _childRows(db, int(output._testInfo["setId"])),
                   output.getSize())
            for name, output in outputs.items()}


@pytest.mark.parametrize("case", ["particles", "imagesFromClasses", "classesFromClasses",
                                  "averages", "particlesOfOneClass"])
def test_DirectSelectionMatchesTheFileCopyPath(copyContext, tmp_path, case):
    ctx = copyContext
    stack = str(tmp_path / "particles.mrcs")
    particles = _particles(ctx, range(1, 61), stack)
    if case == "particles":
        args = (particles, [3, 4, 8, 15, 16, 23, 42, 59], "SetOfParticles")
    else:
        classes = _classes(ctx, particles, 5)
        args = {
            "imagesFromClasses": (classes, [2, 4], "SetOfParticles"),
            "classesFromClasses": (classes, [1, 3, 5], "SetOfClasses2D"),
            "averages": (classes, [1, 2], "SetOfAverages"),
            "particlesOfOneClass": (classes, [1, 6, 11, 16, 26, 36, 51], "SetOfParticles"),
        }[case]
    prefix = "Class002" if case == "particlesOfOneClass" else ""
    direct, directOutputs = _runSubset(ctx, tmp_path, *args, prefix=prefix, direct=True)
    viaFile, fileOutputs = _runSubset(ctx, tmp_path, *args, prefix=prefix, direct=False)
    assert direct._storedInput is not None and viaFile._storedInput is None
    assert directOutputs and set(directOutputs) == set(fileOutputs)
    assert _stored(ctx["db"], directOutputs) == _stored(ctx["db"], fileOutputs)
    assert all(output.getSize() > 0 for output in directOutputs.values())
    copiedAtOnce = any("copied at once" in message for message in direct.messages)
    assert copiedAtOnce == (case in ("particles", "imagesFromClasses", "particlesOfOneClass"))
    assert not any("copied at once" in message for message in viaFile.messages)


def test_CtfSelectionMatchesTheFileCopyPath(copyContext, tmp_path):
    ctx = copyContext
    mics = emobj.SetOfMicrographs()
    mics.setSamplingRate(SAMPLING_RATE)
    mics.setAcquisition(_acquisition())
    mics, micsInfo = ctx["reserve"](mics)
    for itemId in range(1, 13):
        mic = emobj.Micrograph()
        mic.setObjId(itemId)
        mic.setFileName(str(tmp_path / ("mic%03d.mrc" % itemId)))
        mic.setMicName("mic%03d" % itemId)
        mic.setSamplingRate(SAMPLING_RATE)
        mics.append(mic)
    mics = ctx["finalize"](mics, micsInfo)
    ctfs = emobj.SetOfCTF()
    ctfs.setMicrographs(mics)
    ctfs, ctfsInfo = ctx["reserve"](ctfs)
    for mic in mics.iterItems(iterate=False):
        ctf = emobj.CTFModel()
        ctf.setObjId(mic.getObjId())
        ctf.setStandardDefocus(10000.0 + mic.getObjId(), 9800.0, 30.0)
        ctf.setMicrograph(mic)
        ctfs.append(ctf)
    ctfs = ctx["finalize"](ctfs, ctfsInfo)

    direct, directOutputs = _runSubset(ctx, tmp_path, ctfs, [2, 5, 6, 11], "SetOfMicrographs", direct=True)
    viaFile, fileOutputs = _runSubset(ctx, tmp_path, ctfs, [2, 5, 6, 11], "SetOfMicrographs", direct=False)
    assert direct._storedInput is not None and viaFile._storedInput is None
    assert set(directOutputs) == {"outputMicrographs", "outputCTF"} == set(fileOutputs)
    assert _stored(ctx["db"], directOutputs) == _stored(ctx["db"], fileOutputs)
    assert directOutputs["outputCTF"].getSize() == 4
