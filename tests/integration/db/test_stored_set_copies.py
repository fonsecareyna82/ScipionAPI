"""Whole-Set database copies store exactly what one-by-one appends store."""
from uuid import uuid4

import numpy as np
import pytest
from pwem import objects as emobj
from pyworkflow.object import Float, Object

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory

CLASSES = {name: cls for name, cls in vars(emobj).items() if isinstance(cls, type)}
SAMPLING_RATE = 1.25


@pytest.fixture
def copyContext(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    userId = flat.insertUser(
        email="set-copies-%s@example.com" % uuid4().hex, hashedPassword="test-password",
        firstName="Set", lastName="Copies", institution=None, role="user",
        isActive=True, isVerified=True, verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name="Set copies", description="Test")
    protocolDbId = flat.saveProtocol({"info": dict(protocolId=2, projectId=projectId,
        protocolClassName="SetCopiesTestProtocol", status="running"),
        "values": {}, "parentIds": [], "childIds": []})
    parent = Object()
    parent.setObjId(2)
    opened = []
    mapper = ScipionSetPostgresqlMapper(db)
    counter = iter(range(1_000_201, 1_000_999))

    def build(info, writable=False):
        result = PostgresqlRuntimeSetFactory().build(
            db=db, parent=parent, outputName=info["outputName"],
            outputInfo=info, classes=CLASSES, cache=False)
        opened.append(result)
        if writable:
            result.enablePostgresqlWrite()
        return result

    def reserve(nativeSet):
        name = "output%d" % next(counter)
        nativeSet.setObjId(int(name[6:]))
        info = mapper.reserveRuntimeSet(projectId=projectId, protocolDbId=protocolDbId,
                                        outputName=name, scipionSet=nativeSet)
        return build(info, writable=True), info

    def finalize(runtimeSet, info):
        runtimeSet.write()
        report = mapper.finalizeRuntimeSetOutput(projectId=projectId, protocolDbId=protocolDbId,
                                                 outputName=info["outputName"], scipionSet=runtimeSet)
        return build(dict(info, properties=report["properties"]))

    try:
        yield dict(db=db, reserve=reserve, finalize=finalize)
    finally:
        for output in reversed(opened):
            output.close()
        flat.deleteProject(projectId=projectId, ownerId=userId)
        db.execute("DELETE FROM users WHERE id = %s", (userId,))


def _acquisition():
    acquisition = emobj.Acquisition()
    acquisition.setVoltage(300.0)
    acquisition.setSphericalAberration(2.7)
    acquisition.setAmplitudeContrast(0.1)
    acquisition.setMagnification(50000)
    return acquisition


def _particle(itemId, stack, samplingRate=SAMPLING_RATE, extra=False, acquisition=True, align=True):
    particle = emobj.Particle()
    particle.setObjId(itemId)
    particle.setLocation(itemId, stack)
    particle.setSamplingRate(samplingRate)
    particle.setAcquisition(_acquisition() if acquisition else emobj.Acquisition())
    coordinate = emobj.Coordinate()
    coordinate.setPosition(itemId % 4096, (itemId * 3) % 4096)
    coordinate.setMicId(itemId % 7 + 1)
    particle.setCoordinate(coordinate)
    ctf = emobj.CTFModel()
    ctf.setStandardDefocus(12000.0 + itemId, 11800.0 + itemId, 45.0)
    particle.setCTF(ctf)
    if align:
        matrix = np.eye(4)
        matrix[0, 3] = itemId % 5
        particle.setTransform(emobj.Transform(matrix=matrix))
    if extra:
        particle._score = Float(itemId / 7.0)
    return particle


def _particles(ctx, ids, stack, **kwargs):
    particles = emobj.SetOfParticles()
    particles.setSamplingRate(kwargs.pop("setSamplingRate", SAMPLING_RATE))
    particles.setAcquisition(_acquisition() if kwargs.get("acquisition", True) else emobj.Acquisition())
    particles, info = ctx["reserve"](particles)
    for itemId in ids:
        particles.append(_particle(itemId, stack, **kwargs))
    return ctx["finalize"](particles, info)


def _commonPaths(sources):
    common = None
    for source in sources:
        keys = set(source.getFirstItem().getObjDict().keys())
        common = keys if common is None else common & keys
    return sorted(common)


def _cleanExtra(item, paths, prefix=""):
    for name, value in item.getAttributesToStore():
        path = prefix + name
        if path not in paths:
            value._objDoStore = False
        else:
            _cleanExtra(value, paths, path + ".")


def _builder(itemType, paths):
    topLevel = [path for path in paths if "." not in path]

    def buildItem(source):
        item = itemType()
        item.copyAttributes(source, *topLevel)
        _cleanExtra(item, paths)
        return item
    return buildItem


def _appendOneByOne(output, sources, buildItem, renumberAll, renumberAfterFirst, skipDuplicateIds):
    """The ProtUnionSet loop: Set order, ascending ids, the same id rules."""
    seen = set()
    for setNumber, source in enumerate(sources, 1):
        for sourceItem in source.iterItems(iterate=False):
            sourceId = sourceItem.getObjId()
            if skipDuplicateIds:
                if sourceId in seen:
                    continue
                seen.add(sourceId)
            item = buildItem(sourceItem)
            if not renumberAll and not (renumberAfterFirst and setNumber > 1):
                item.setObjId(sourceId)
            output.append(item)


def _union(ctx, sources, fast, itemType=emobj.Particle, setType=emobj.SetOfParticles, **policy):
    output = setType()
    output, info = ctx["reserve"](output)
    output.copyInfo(sources[0])
    paths = _commonPaths(sources)
    buildItem = _builder(itemType, paths)
    copied = fast and output.appendFromStoredSets(sources, buildItem, paths, **policy)
    if not copied:
        _appendOneByOne(output, sources, buildItem, **policy)
    output.write()
    return output, info, copied


def _stored(db, info, output):
    setId = int(info["setId"])
    rows = db.fetchAll('SELECT "scipionItemId", enabled, label, comment, creation, "values" '
                       'FROM scipion_set_items WHERE "setId" = %s ORDER BY "scipionItemId"', (setId,))
    rootCopy = db.fetchAll('SELECT "scipionItemId", enabled, label, comment, creation, "values" '
                           'FROM scipion_set_table_items WHERE "tableId" = %s ORDER BY "scipionItemId"',
                           (int(info["rootTableId"]),))
    columns = db.fetchAll('SELECT "labelProperty", "columnName", "className", "valueType", position, indexed '
                          'FROM scipion_set_columns WHERE "setId" = %s ORDER BY position', (setId,))
    tableColumns = db.fetchAll('SELECT "labelProperty", "columnName", "className", "valueType", position '
                               'FROM scipion_set_table_columns WHERE "tableId" = %s ORDER BY position',
                               (int(info["rootTableId"]),))
    itemClass = db.fetchOne('SELECT "itemClassName" FROM scipion_sets WHERE id = %s', (setId,))
    state = (output.getSize(), output._idCount, output.getDim() if hasattr(output, "getDim") else None,
             output.hasAlignment() if hasattr(output, "hasAlignment") else None)
    return ([dict(r) for r in rows], [dict(r) for r in rootCopy], [dict(r) for r in columns],
            [dict(r) for r in tableColumns], dict(itemClass), state)


POLICIES = [
    dict(renumberAll=False, renumberAfterFirst=True, skipDuplicateIds=False),
    dict(renumberAll=True, renumberAfterFirst=False, skipDuplicateIds=False),
    dict(renumberAll=False, renumberAfterFirst=False, skipDuplicateIds=True),
    dict(renumberAll=True, renumberAfterFirst=False, skipDuplicateIds=True),
]


@pytest.mark.parametrize("policy", POLICIES)
def test_CopyMatchesOneByOneAppendsForEachIdPolicy(copyContext, tmp_path, policy):
    stack = str(tmp_path / "particles.mrcs")
    sources = [_particles(copyContext, range(1, 41), stack),
               _particles(copyContext, range(25, 61), stack),
               _particles(copyContext, [3, 70, 71], stack)]
    fast, fastInfo, copied = _union(copyContext, sources, True, **policy)
    slow, slowInfo, _ = _union(copyContext, sources, False, **policy)
    assert copied
    assert _stored(copyContext["db"], fastInfo, fast) == _stored(copyContext["db"], slowInfo, slow)


def test_DisjointIdsAreKept(copyContext, tmp_path):
    stack = str(tmp_path / "particles.mrcs")
    sources = [_particles(copyContext, range(1, 21), stack), _particles(copyContext, range(21, 31), stack)]
    policy = dict(renumberAll=False, renumberAfterFirst=False, skipDuplicateIds=False)
    fast, fastInfo, copied = _union(copyContext, sources, True, **policy)
    slow, slowInfo, _ = _union(copyContext, sources, False, **policy)
    assert copied
    stored = _stored(copyContext["db"], fastInfo, fast)
    assert stored == _stored(copyContext["db"], slowInfo, slow)
    assert [row["scipionItemId"] for row in stored[0]] == list(range(1, 31))


def test_RepeatedSourceIsAppendedPerOccurrence(copyContext, tmp_path):
    first = _particles(copyContext, range(1, 6), str(tmp_path / "particles.mrcs"))
    policy = dict(renumberAll=False, renumberAfterFirst=True, skipDuplicateIds=False)
    fast, fastInfo, copied = _union(copyContext, [first, first], True, **policy)
    slow, slowInfo, _ = _union(copyContext, [first, first], False, **policy)
    assert not copied
    stored = _stored(copyContext["db"], fastInfo, fast)
    assert stored == _stored(copyContext["db"], slowInfo, slow)
    assert len(stored[0]) == 10


@pytest.mark.parametrize("case", ["samplingRate", "otherPaths", "missingAcquisition"])
def test_CopyRefusesWhenAppendWouldChangeItems(copyContext, tmp_path, case):
    stack = str(tmp_path / "particles.mrcs")
    first = _particles(copyContext, range(1, 6), stack)
    if case == "samplingRate":
        second = _particles(copyContext, range(6, 11), stack, samplingRate=2.5, setSamplingRate=2.5)
    elif case == "otherPaths":
        second = _particles(copyContext, range(6, 11), stack, extra=True)
        # Common paths exclude the extra score, which the second Set stores.
    else:
        # Stored with empty acquisition values, which append() would fill.
        second = _particles(copyContext, range(6, 11), stack, acquisition=False)
    policy = dict(renumberAll=False, renumberAfterFirst=False, skipDuplicateIds=False)
    fast, fastInfo, copied = _union(copyContext, [first, second], True, **policy)
    slow, slowInfo, _ = _union(copyContext, [first, second], False, **policy)
    assert not copied
    assert _stored(copyContext["db"], fastInfo, fast) == _stored(copyContext["db"], slowInfo, slow)


def test_MicrographsCopyLikeParticles(copyContext, tmp_path):
    def micrographs(ids):
        mics = emobj.SetOfMicrographs()
        mics.setSamplingRate(SAMPLING_RATE)
        mics.setAcquisition(_acquisition())
        mics, info = copyContext["reserve"](mics)
        for itemId in ids:
            mic = emobj.Micrograph()
            mic.setObjId(itemId)
            mic.setFileName(str(tmp_path / ("mic%03d.mrc" % itemId)))
            mic.setMicName("mic%03d" % itemId)
            mic.setSamplingRate(SAMPLING_RATE)
            mic.setAcquisition(_acquisition())
            mics.append(mic)
        return copyContext["finalize"](mics, info)

    sources = [micrographs(range(1, 9)), micrographs(range(5, 12))]
    policy = dict(renumberAll=False, renumberAfterFirst=True, skipDuplicateIds=False)
    kwargs = dict(itemType=emobj.Micrograph, setType=emobj.SetOfMicrographs, **policy)
    fast, fastInfo, copied = _union(copyContext, sources, True, **kwargs)
    slow, slowInfo, _ = _union(copyContext, sources, False, **kwargs)
    assert copied
    assert _stored(copyContext["db"], fastInfo, fast) == _stored(copyContext["db"], slowInfo, slow)


class _Param:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


def _runRealUnion(ctx, sources, allowCopy, renumber=False, ignoreDuplicates=False):
    """Run pwem's own ProtUnionSet.createOutputStep against stored Sets."""
    from pwem.protocols.protocol_sets import ProtSets, ProtUnionSet

    class UnionRun:
        createOutputStep = ProtUnionSet.createOutputStep
        _appendAllAtOnce = ProtUnionSet._appendAllAtOnce
        cleanExtraAttributes = ProtUnionSet.cleanExtraAttributes
        duplicatedIds = ProtUnionSet.duplicatedIds
        getAllSetsAttributes = ProtUnionSet.getAllSetsAttributes
        commonAttributes = ProtUnionSet.commonAttributes
        _getHeterogeneityWarning = ProtUnionSet._getHeterogeneityWarning
        _append = ProtSets._append

        def __init__(self):
            self.inputSets = [_Param(source) for source in sources]
            self.renumber = _Param(renumber)
            self.ignoreDuplicates = _Param(ignoreDuplicates)
            self.messages = []

        def _createSetOfParticles(self):
            output, self.outputInfo = ctx["reserve"](emobj.SetOfParticles())
            if not allowCopy:
                output.appendFromStoredSets = None
            return output

        def info(self, message):
            self.messages.append(str(message))

        def _defineOutputs(self, **outputs):
            self.outputs = outputs

        def _defineSourceRelation(self, *args):
            pass

    run = UnionRun()
    run.createOutputStep()
    output = run.outputs["outputSet"]
    output.write()
    return output, run.outputInfo, any("copied at once" in m for m in run.messages)


@pytest.mark.parametrize("options", [dict(), dict(renumber=True), dict(ignoreDuplicates=True)])
def test_RealUnionProtocolCopiesWhatItsLoopAppends(copyContext, tmp_path, options):
    stack = str(tmp_path / "particles.mrcs")
    sources = [_particles(copyContext, range(1, 31), stack), _particles(copyContext, range(20, 45), stack)]
    fast, fastInfo, copied = _runRealUnion(copyContext, sources, True, **options)
    slow, slowInfo, slowCopied = _runRealUnion(copyContext, sources, False, **options)
    assert copied and not slowCopied
    assert _stored(copyContext["db"], fastInfo, fast) == _stored(copyContext["db"], slowInfo, slow)


def _particlesWithRawCoordinates(ctx, ids, stack, rawValue):
    """Stored Integer coordinates holding raw values, as rescaled extractions leave them."""
    particles = emobj.SetOfParticles()
    particles.setSamplingRate(SAMPLING_RATE)
    particles.setAcquisition(_acquisition())
    particles, info = ctx["reserve"](particles)
    for itemId in ids:
        particle = _particle(itemId, stack)
        particle.getCoordinate()._x._objValue = rawValue(itemId)
        particles.append(particle)
    return ctx["finalize"](particles, info)


def test_CopyTruncatesIntegerPathsLikeNewObjects(copyContext, tmp_path):
    stack = str(tmp_path / "particles.mrcs")
    raw = lambda itemId: (itemId * 7.75) * (-1 if itemId % 3 == 0 else 1)
    sources = [_particlesWithRawCoordinates(copyContext, range(1, 21), stack, raw),
               _particlesWithRawCoordinates(copyContext, range(15, 31), stack, raw)]
    stored = copyContext["db"].fetchOne(
        """SELECT "values"->'_coordinate._x' AS x FROM scipion_set_items
            WHERE "setId" = %s AND "scipionItemId" = 3""",
        (int(sources[0].getPostgresqlRuntimeInfo()["setId"]),))
    assert stored["x"] == -23.25
    policy = dict(renumberAll=True, renumberAfterFirst=False, skipDuplicateIds=False)
    fast, fastInfo, copied = _union(copyContext, sources, True, **policy)
    slow, slowInfo, _ = _union(copyContext, sources, False, **policy)
    assert copied
    result = _stored(copyContext["db"], fastInfo, fast)
    assert result == _stored(copyContext["db"], slowInfo, slow)
    assert [row["values"]["_coordinate._x"] for row in result[0][:3]] == [7, 15, -23]


def test_CopyRefusesIntegerPathsHoldingText(copyContext, tmp_path):
    stack = str(tmp_path / "particles.mrcs")
    sources = [_particles(copyContext, range(1, 6), stack),
               _particlesWithRawCoordinates(copyContext, range(6, 11), stack, lambda itemId: "12")]
    policy = dict(renumberAll=False, renumberAfterFirst=False, skipDuplicateIds=False)
    fast, fastInfo, copied = _union(copyContext, sources, True, **policy)
    slow, slowInfo, _ = _union(copyContext, sources, False, **policy)
    assert not copied
    assert _stored(copyContext["db"], fastInfo, fast) == _stored(copyContext["db"], slowInfo, slow)


def _labelledParticles(ctx, ids, stack):
    particles = emobj.SetOfParticles()
    particles.setSamplingRate(SAMPLING_RATE)
    particles.setAcquisition(_acquisition())
    particles, info = ctx["reserve"](particles)
    for itemId in ids:
        particle = _particle(itemId, stack)
        if itemId % 4 == 0:
            particle.setObjLabel("label-%d" % itemId)
        if itemId % 6 == 0:
            particle.setObjComment("comment %d" % itemId)
        if itemId % 5 == 0:
            particle.setEnabled(False)
        particles.append(particle)
    return ctx["finalize"](particles, info)


def _copyInto(ctx, source, allowCopy, **kwargs):
    output, info = ctx["reserve"](emobj.SetOfParticles())
    output.copyInfo(source)
    if not allowCopy:
        output.appendFromStoredSets = None
    output.copyItems(source, **kwargs)
    output.write()
    return output, info


@pytest.mark.parametrize("options", [dict(), dict(doClone=False), dict(copyDisabled=True),
                                     dict(doClone=False, copyDisabled=True)])
def test_CopyItemsMatchesItsLoop(copyContext, tmp_path, options, monkeypatch):
    from app.backend.runtime import postgresql_runtime_set_factory as factoryModule
    calls = []
    original = factoryModule.PostgresqlRuntimeSetMixin.appendFromStoredSets

    def tracked(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        calls.append(result)
        return result

    monkeypatch.setattr(factoryModule.PostgresqlRuntimeSetMixin, "appendFromStoredSets", tracked)
    source = _labelledParticles(copyContext, range(1, 41), str(tmp_path / "particles.mrcs"))
    fast, fastInfo = _copyInto(copyContext, source, True, **options)
    slow, slowInfo = _copyInto(copyContext, source, False, **options)
    assert calls == [True]
    stored = _stored(copyContext["db"], fastInfo, fast)
    assert stored == _stored(copyContext["db"], slowInfo, slow)
    rows = stored[0]
    assert len(rows) == (40 if options.get("copyDisabled") else 32)
    assert any(row["label"] == "label-4" for row in rows)


@pytest.mark.parametrize("options", [dict(updateItemCallback=lambda item, row: item.setClassId(3)),
                                     dict(itemSelectedCallback=lambda item: item.getObjId() < 10),
                                     dict(orderBy="id", direction="DESC")])
def test_CopyItemsKeepsItsLoopForCallbacksAndOrders(copyContext, tmp_path, options, monkeypatch):
    from app.backend.runtime import postgresql_runtime_set_factory as factoryModule
    monkeypatch.setattr(factoryModule.PostgresqlRuntimeSetMixin, "appendFromStoredSets",
                        lambda *args, **kwargs: pytest.fail("callbacks need the item loop"))
    source = _labelledParticles(copyContext, range(1, 21), str(tmp_path / "particles.mrcs"))
    output, info = copyContext["reserve"](emobj.SetOfParticles())
    output.copyInfo(source)
    output.copyItems(source, **options)
    output.write()
    assert output.getSize() > 0


def test_CopyItemsIntoANonEmptySetAppendsOneByOne(copyContext, tmp_path):
    stack = str(tmp_path / "particles.mrcs")
    first = _labelledParticles(copyContext, range(1, 11), stack)
    second = _labelledParticles(copyContext, range(11, 21), stack)
    fast, fastInfo = copyContext["reserve"](emobj.SetOfParticles())
    slow, slowInfo = copyContext["reserve"](emobj.SetOfParticles())
    slow.appendFromStoredSets = None
    for output in (fast, slow):
        output.copyInfo(first)
        output.copyItems(first)
        output.copyItems(second)
        output.write()
    assert _stored(copyContext["db"], fastInfo, fast) == _stored(copyContext["db"], slowInfo, slow)
    assert fast.getSize() == 16


def test_CreateCopyOfAStoredSetDoesNotMaterializeIt(copyContext, tmp_path, monkeypatch):
    source = _labelledParticles(copyContext, range(1, 6), str(tmp_path / "particles.mrcs"))
    monkeypatch.setattr(type(source), "getFileName",
                        lambda self: pytest.fail("createCopy must not materialize its source"))
    copy = source.createCopy(str(tmp_path), copyInfo=True)
    assert copy.getFileName().endswith(".sqlite")
