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
"""Set-of-Sets output persistence: classic SQLite versus native PostgreSQL.

Both backends receive the same SetOfClasses2D workload, filled the way
pwem's ``SetOfClasses.classifyItems`` does it: particles are visited once,
appended to their (lazily created) class in interleaved order, and every class
is updated after the loop.

Run with, for example::

    SCIPIONAPI_RUN_BENCHMARKS=1 \\
    SCIPIONAPI_BENCHMARK_NESTED_SIZES=200x500000 \\
    SCIPIONAPI_BENCHMARK_PROFILE_DIR=/tmp/nested-profile \\
    pytest -s tests/benchmarks/db/test_nested_set_runtime_benchmark.py

``SCIPIONAPI_BENCHMARK_NESTED_SIZES`` takes ``<classes>x<particles>`` pairs.
``SCIPIONAPI_BENCHMARK_NESTED_MATERIALIZE=0`` skips SQLite materialization.
``SCIPIONAPI_BENCHMARK_QUERY_REPORT=1`` prints the costliest write statements.
``SCIPIONAPI_BENCHMARK_DUMP=<file>`` writes the stored classes Set as JSON, without database ids, times or
temporary paths, so two runs can be compared row by row (e.g. before and after a change of the write path).
"""
import cProfile
import io
import json
import os
import pstats
import re
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from pwem import objects as emobj

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory
from app.backend.runtime.postgresql_runtime_set_sqlite_materializer import PostgresqlRuntimeSetSqliteMaterializer


RUN_BENCHMARKS = os.getenv("SCIPIONAPI_RUN_BENCHMARKS") == "1"
PROFILE_DIR = (os.getenv("SCIPIONAPI_BENCHMARK_PROFILE_DIR") or "").strip()
MATERIALIZE = os.getenv("SCIPIONAPI_BENCHMARK_NESTED_MATERIALIZE", "1") != "0"
QUERY_REPORT = os.getenv("SCIPIONAPI_BENCHMARK_QUERY_REPORT") == "1"
DUMP_PATH = (os.getenv("SCIPIONAPI_BENCHMARK_DUMP") or "").strip()
# Bookkeeping that changes from run to run: reservation tokens, sync times, database ids
VOLATILE_PROPERTY_KEYS = {"lastSyncAt", "lastCheckedAt", "reservationToken", "provisionalOutputName",
                          "scipionObjId", "rootTableId", "setId", "tableId", "objectId"}
QUERY_METHODS = ("execute", "executeValues", "executeReturningOne", "fetchOne", "fetchAll")
SAMPLING_RATE = 1.25


def _getNestedSizes():
    value = os.getenv("SCIPIONAPI_BENCHMARK_NESTED_SIZES", "20x20000")
    sizes = []
    for pair in value.split(","):
        if not pair.strip():
            continue
        classesCount, particlesCount = (int(part) for part in pair.lower().split("x"))
        if classesCount <= 0 or particlesCount < classesCount:
            raise ValueError("SCIPIONAPI_BENCHMARK_NESTED_SIZES needs <classes>x<particles> with particles >= classes")
        sizes.append((classesCount, particlesCount))
    return sizes


pytestmark = pytest.mark.skipif(
    not RUN_BENCHMARKS,
    reason="Set SCIPIONAPI_RUN_BENCHMARKS=1 to run PostgreSQL benchmarks.",
)

CLASSES = {name: cls for name, cls in vars(emobj).items() if isinstance(cls, type)}


class ParentProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = int(protocolId)

    def getObjId(self):
        return self.protocolId


def _classIdFor(particleId, classesCount):
    # Deterministic scatter so consecutive particles land in different classes.
    return (particleId * 7919) % classesCount + 1


def _buildAcquisition():
    acquisition = emobj.Acquisition()
    acquisition.setVoltage(300.0)
    acquisition.setSphericalAberration(2.7)
    acquisition.setAmplitudeContrast(0.1)
    acquisition.setMagnification(50000)
    return acquisition


def _buildParticle(particleId, classId, stackPath):
    particle = emobj.Particle()
    particle.setObjId(particleId)
    particle.setLocation(particleId, stackPath)
    particle.setSamplingRate(SAMPLING_RATE)
    particle.setClassId(classId)
    particle.setAcquisition(_buildAcquisition())

    micId = particleId % 500 + 1
    coordinate = emobj.Coordinate()
    coordinate.setPosition(particleId % 4096, (particleId * 3) % 4096)
    coordinate.setMicId(micId)
    particle.setCoordinate(coordinate)
    particle.setMicId(micId)

    ctf = emobj.CTFModel()
    ctf.setStandardDefocus(12000.0 + micId, 11800.0 + micId, 45.0)
    particle.setCTF(ctf)

    matrix = np.eye(4)
    matrix[0, 3] = particleId % 7
    matrix[1, 3] = -(particleId % 5)
    particle.setTransform(emobj.Transform(matrix=matrix))
    return particle


class PhaseTimer:
    """Accumulate wall time and PostgreSQL query counts per fill operation."""

    def __init__(self, db=None):
        self.db = db
        self.phases = {}

    @contextmanager
    def __call__(self, name):
        before = self.db.getQueryStats() if self.db is not None else None
        startedAt = time.perf_counter()
        try:
            yield
        finally:
            phase = self.phases.setdefault(name, {"calls": 0, "seconds": 0.0, "queryCount": 0, "querySeconds": 0.0})
            phase["calls"] += 1
            phase["seconds"] += time.perf_counter() - startedAt
            if before is not None:
                after = self.db.getQueryStats()
                phase["queryCount"] += after["queryCount"] - before["queryCount"]
                phase["querySeconds"] += after["querySeconds"] - before["querySeconds"]


@contextmanager
def _profiled(label):
    if not PROFILE_DIR:
        yield
        return
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        yield
    finally:
        profiler.disable()
        Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(str(Path(PROFILE_DIR) / ("%s.prof" % label)))
        report = io.StringIO()
        pstats.Stats(profiler, stream=report).sort_stats("cumulative").print_stats(30)
        print("\nSCIPIONAPI_NESTED_PROFILE[%s]\n%s" % (label, report.getvalue()))


def _normalizeStatement(query):
    return re.sub(r"\s+", " ", str(query)).strip()[:220]


@contextmanager
def _queryReport(db, label):
    """Group statements by text; transaction commits are timed on exit."""
    if not QUERY_REPORT:
        yield
        return
    statements = {}

    def record(key, seconds):
        entry = statements.setdefault(key, {"calls": 0, "seconds": 0.0, "maxSeconds": 0.0})
        entry["calls"] += 1
        entry["seconds"] += seconds
        entry["maxSeconds"] = max(entry["maxSeconds"], seconds)

    def timed(method):
        def wrapper(query, *args, **kwargs):
            startedAt = time.perf_counter()
            try:
                return method(query, *args, **kwargs)
            finally:
                record(_normalizeStatement(query), time.perf_counter() - startedAt)
        return wrapper

    originalTransaction = db.transaction

    @contextmanager
    def timedTransaction(*args, **kwargs):
        context = originalTransaction(*args, **kwargs)
        context.__enter__()
        try:
            yield db
        except BaseException as error:
            if not context.__exit__(type(error), error, error.__traceback__):
                raise
        else:
            startedAt = time.perf_counter()
            context.__exit__(None, None, None)
            record("<transaction exit/commit>", time.perf_counter() - startedAt)

    for name in QUERY_METHODS:
        setattr(db, name, timed(getattr(db, name)))
    db.transaction = timedTransaction
    try:
        yield
    finally:
        for name in QUERY_METHODS + ("transaction",):
            db.__dict__.pop(name, None)
        top = sorted(statements.items(), key=lambda item: item[1]["seconds"], reverse=True)[:20]
        print("\nSCIPIONAPI_NESTED_QUERY_REPORT[%s]" % label)
        for statement, entry in top:
            print("  %8.2fs  calls=%-7d max=%6.3fs  %s" % (
                entry["seconds"], entry["calls"], entry["maxSeconds"], statement))


def _fillInputParticles(images, particlesCount, stackPath):
    for particleId in range(1, particlesCount + 1):
        images.append(_buildParticle(particleId, None, stackPath))
    images.write()


def _classifyLikeCryosparc(classes, classesCount, stackPath, timer):
    """Mirror cryoSPARC 2D createOutputStep: classifyItems over the inputs."""
    def updateParticle(item, row):
        particleId = item.getObjId()
        item.setClassId(_classIdFor(particleId, classesCount))
        matrix = np.eye(4)
        matrix[0, 3] = particleId % 7
        matrix[1, 3] = -(particleId % 5)
        item.setTransform(emobj.Transform(matrix=matrix))

    def updateClass(classItem):
        classItem.setAlignment2D()
        representative = classItem.getRepresentative()
        representative.setLocation(classItem.getObjId(), stackPath + ".averages")
        representative.setSamplingRate(classItem.getSamplingRate())

    with timer("classifyItems"):
        classes.classifyItems(updateItemCallback=updateParticle, updateClassCallback=updateClass)
    with timer("write"):
        classes.write()


def _expectedTotals(classesCount, particlesCount):
    sizes = {}
    for particleId in range(1, particlesCount + 1):
        classId = _classIdFor(particleId, classesCount)
        sizes[classId] = sizes.get(classId, 0) + 1
    return sizes


def _verifyClasses(classes, classesCount, particlesCount):
    expectedSizes = _expectedTotals(classesCount, particlesCount)
    seenSizes = {}
    idsSum = 0
    for classItem in classes.iterItems(orderBy="id", direction="ASC"):
        classId = classItem.getObjId()
        assert classItem.getSize() == expectedSizes[classId]
        count = 0
        for particle in classItem.iterItems(orderBy="id", direction="ASC"):
            particleId = particle.getObjId()
            assert particle.getClassId() == classId
            assert particle.getTransform().getMatrix()[0, 3] == particleId % 7
            count += 1
            idsSum += particleId
        seenSizes[classId] = count
    assert seenSizes == expectedSizes
    assert idsSum == particlesCount * (particlesCount + 1) // 2


def _phaseSummary(timer):
    return {name: dict(phase) for name, phase in timer.phases.items()}


def _runSqlite(tmp_path, classesCount, particlesCount, stackPath):
    imagesPath = tmp_path / "sqlite-particles.sqlite"
    classesPath = tmp_path / "sqlite-classes.sqlite"

    inputStartedAt = time.perf_counter()
    images = emobj.SetOfParticles(filename=str(imagesPath))
    images.setSamplingRate(SAMPLING_RATE)
    images.setAcquisition(_buildAcquisition())
    with _profiled("sqlite-input-%s" % particlesCount):
        _fillInputParticles(images, particlesCount, stackPath)
    inputSeconds = time.perf_counter() - inputStartedAt

    timer = PhaseTimer()
    startedAt = time.perf_counter()
    classes = emobj.SetOfClasses2D(filename=str(classesPath))
    classes.setImages(images)
    with _profiled("sqlite-classify-%sx%s" % (classesCount, particlesCount)):
        _classifyLikeCryosparc(classes, classesCount, stackPath, timer)
    totalSeconds = time.perf_counter() - startedAt
    classes.close()
    images.close()

    reopened = emobj.SetOfClasses2D(filename=str(classesPath))
    try:
        readStartedAt = time.perf_counter()
        _verifyClasses(reopened, classesCount, particlesCount)
        readSeconds = time.perf_counter() - readStartedAt
    finally:
        reopened.close()

    return {
        "inputWriteSeconds": inputSeconds,
        "totalWriteSeconds": totalSeconds,
        "readVerifySeconds": readSeconds,
        "phases": _phaseSummary(timer),
        "fileBytes": classesPath.stat().st_size,
    }


@pytest.fixture
def nestedBenchmarkContext(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    suffix = uuid4().hex
    userId = flat.insertUser(
        email="nested-benchmark-%s@example.com" % suffix, hashedPassword="benchmark",
        firstName="Nested", lastName="Benchmark", institution=None, role="user",
        isActive=True, isVerified=True, verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name="Nested benchmark %s" % suffix,
                                   description="Set-of-Sets persistence benchmark")
    protocolDbId = flat.saveProtocol({"info": dict(protocolId=2, projectId=projectId,
        protocolClassName="NestedBenchmarkProtocol", status="running"),
        "values": {}, "parentIds": [], "childIds": []})
    opened = []

    def build(targetDb, info, writable=False):
        result = PostgresqlRuntimeSetFactory().build(
            db=targetDb, parent=ParentProtocolStub(2), outputName=info["outputName"],
            outputInfo=info, classes=CLASSES, cache=False)
        opened.append(result)
        if writable:
            result.enablePostgresqlWrite()
        return result

    def reserve(nativeSet, name, objectId):
        nativeSet.setObjId(objectId)
        info = ScipionSetPostgresqlMapper(db).reserveRuntimeSet(
            projectId=projectId, protocolDbId=protocolDbId, outputName=name, scipionSet=nativeSet)
        return build(db, info, writable=True), info

    try:
        yield dict(db=db, projectId=projectId, protocolDbId=protocolDbId,
                   env=postgresqlMigratedEnv, reserve=reserve, build=build)
    finally:
        for output in reversed(opened):
            try:
                output.close()
            except Exception:
                pass
        flat.deleteProject(projectId=projectId, ownerId=userId)
        db.execute("DELETE FROM users WHERE id = %s", (userId,))


def _runPostgresql(ctx, classesCount, particlesCount, stackPath):
    db = ctx["db"]
    mapper = ScipionSetPostgresqlMapper(db)
    sizeLabel = "%sx%s" % (classesCount, particlesCount)

    # The input particles belong to an upstream protocol; time them apart.
    db.resetQueryStats()
    inputStartedAt = time.perf_counter()
    with _queryReport(db, "input-%s" % particlesCount), _profiled("postgresql-input-%s" % particlesCount):
        images = emobj.SetOfParticles()
        images.setSamplingRate(SAMPLING_RATE)
        images.setAcquisition(_buildAcquisition())
        images, imagesInfo = ctx["reserve"](images, "inputParticles", 2_000_001)
        _fillInputParticles(images, particlesCount, stackPath)
        imagesReport = mapper.finalizeRuntimeSetOutput(
            projectId=ctx["projectId"], protocolDbId=ctx["protocolDbId"],
            outputName="inputParticles", scipionSet=images)
    inputSeconds = time.perf_counter() - inputStartedAt
    inputQueryStats = db.getQueryStats()
    images = ctx["build"](db, dict(imagesInfo, properties=imagesReport["properties"]))

    db.resetQueryStats()
    timer = PhaseTimer(db)
    startedAt = time.perf_counter()
    with timer("reserve"):
        native = emobj.SetOfClasses2D()
        native.setImages(images)
        output, info = ctx["reserve"](native, "outputClasses", 2_000_002)

    with _queryReport(db, "classify-finalize-%s" % sizeLabel):
        with _profiled("postgresql-classify-%s" % sizeLabel):
            _classifyLikeCryosparc(output, classesCount, stackPath, timer)
        classifySeconds = time.perf_counter() - startedAt

        with _profiled("postgresql-finalize-%s" % sizeLabel):
            with timer("finalize"):
                mapper.finalizeRuntimeSetOutput(
                    projectId=ctx["projectId"], protocolDbId=ctx["protocolDbId"],
                    outputName="outputClasses", scipionSet=output)
        totalSeconds = time.perf_counter() - startedAt

    env = ctx["env"]
    reader = PostgresqlDb(dbName=env["databaseName"], user=env["databaseUser"],
                          password=env["databasePass"], host=env["postgresHost"], port=env["postgresPort"])
    result = {
        "inputWriteSeconds": inputSeconds,
        "inputQueryStats": inputQueryStats,
        "classifyAndWriteSeconds": classifySeconds,
        "totalWriteSeconds": totalSeconds,
        "queryStats": db.getQueryStats(),
        "phases": _phaseSummary(timer),
    }
    if DUMP_PATH:
        _dumpStoredSet(reader, ctx["projectId"], ctx["protocolDbId"], "outputClasses", str(Path(stackPath).parent),
                       DUMP_PATH)
    try:
        stored = ScipionSetPostgresqlMapper(reader).getStoredSet(
            projectId=ctx["projectId"], protocolDbId=ctx["protocolDbId"], outputName="outputClasses")
        reopenStartedAt = time.perf_counter()
        reopened = ctx["build"](reader, dict(info, properties=stored["properties"]))
        result["reopenSeconds"] = time.perf_counter() - reopenStartedAt

        reader.resetQueryStats()
        readStartedAt = time.perf_counter()
        with _profiled("postgresql-read-%s" % sizeLabel):
            _verifyClasses(reopened, classesCount, particlesCount)
        result["readVerifySeconds"] = time.perf_counter() - readStartedAt
        result["readQueryStats"] = reader.getQueryStats()

        if MATERIALIZE:
            with _profiled("postgresql-materialize-%s" % sizeLabel):
                materializeStartedAt = time.perf_counter()
                path = PostgresqlRuntimeSetSqliteMaterializer().materialize(reopened)
                result["materializeSeconds"] = time.perf_counter() - materializeStartedAt
            materialized = emobj.SetOfClasses2D(filename=path)
            try:
                assert materialized.getSize() == classesCount
            finally:
                materialized.close()
            result["materializedBytes"] = Path(path).stat().st_size
    finally:
        reader.close()
    return result


def _dumpStoredSet(db, projectId, protocolDbId, outputName, tmpPath, path):
    """The Set as stored: its properties, columns, tables and items, keyed by Scipion ids."""
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in sorted(value.items()) if key not in VOLATILE_PROPERTY_KEYS}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str):
            return value.replace(tmpPath, "<tmp>")
        return value

    stored = db.fetchOne('SELECT id, "setClassName", "itemClassName", properties FROM scipion_sets '
                         'WHERE "projectId" = %s AND "protocolDbId" = %s AND "outputName" = %s',
                         (projectId, protocolDbId, outputName))
    setId = stored["id"]
    tables = db.fetchAll('SELECT id, name, alias, "tableKind", "parentItemId", "itemClassName", properties '
                         'FROM scipion_set_tables WHERE "setId" = %s', (setId,))
    itemColumns = 'enabled, label, comment, "values"'
    dump = {
        "set": clean({"setClassName": stored["setClassName"], "itemClassName": stored["itemClassName"],
                      "properties": stored["properties"]}),
        "setProperties": clean({row["key"]: row["value"] for row in db.fetchAll(
            'SELECT key, value FROM scipion_set_properties WHERE "setId" = %s', (setId,))}),
        "setColumns": clean(db.fetchAll(
            'SELECT "labelProperty", "columnName", "className", "valueType", position, indexed '
            'FROM scipion_set_columns WHERE "setId" = %s ORDER BY position', (setId,))),
        "items": clean({str(row["scipionItemId"]): row for row in db.fetchAll(
            'SELECT "scipionItemId", %s FROM scipion_set_items WHERE "setId" = %%s' % itemColumns, (setId,))}),
        "tables": {},
    }
    for table in tables:
        key = "%s:%s" % (table["tableKind"], table["parentItemId"])
        dump["tables"][key] = clean({
            "name": table["name"], "alias": table["alias"], "itemClassName": table["itemClassName"],
            "properties": table["properties"],
            "columns": db.fetchAll(
                'SELECT "labelProperty", "columnName", "className", "valueType", position, indexed, properties '
                'FROM scipion_set_table_columns WHERE "tableId" = %s ORDER BY position', (table["id"],)),
            "items": {str(row["scipionItemId"]): row for row in db.fetchAll(
                'SELECT "scipionItemId", "parentItemId", %s FROM scipion_set_table_items WHERE "tableId" = %%s'
                % itemColumns, (table["id"],))},
        })
    Path(path).write_text(json.dumps(dump, sort_keys=True, indent=1, default=str))


@pytest.mark.parametrize("classesCount,particlesCount", _getNestedSizes())
def test_NestedClassesOutputPersistenceBenchmark(nestedBenchmarkContext, tmp_path, classesCount, particlesCount):
    stackPath = str(tmp_path / "particles.mrcs")

    sqliteResult = _runSqlite(tmp_path, classesCount, particlesCount, stackPath)
    postgresqlResult = _runPostgresql(nestedBenchmarkContext, classesCount, particlesCount, stackPath)

    result = {
        "classesCount": classesCount,
        "particlesCount": particlesCount,
        "sqlite": sqliteResult,
        "postgresql": postgresqlResult,
        "writeVsSqliteRatio": (postgresqlResult["totalWriteSeconds"] / sqliteResult["totalWriteSeconds"]
                               if sqliteResult["totalWriteSeconds"] > 0 else None),
    }
    print("\nSCIPIONAPI_NESTED_SET_BENCHMARK=%s" % json.dumps(result, sort_keys=True, default=str))
