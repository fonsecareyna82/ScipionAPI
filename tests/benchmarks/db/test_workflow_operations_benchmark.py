"""Reset from, Restart and Delete of a big workflow, through the services the web calls.

A synthetic workflow is stored as ScipionWeb stores one: protocols in PostgreSQL with their dependencies,
input refs and steps, every protocol with an output Set of particles written through the runtime Set
persistence, and a Runs folder with files. Each operation runs on a workflow of its own, built again, and
is checked afterwards, so a partial operation is never timed.

Run with, for example::

    SCIPIONAPI_RUN_BENCHMARKS=1 \\
    SCIPIONAPI_BENCHMARK_WORKFLOW=40x20000 \\
    SCIPIONAPI_BENCHMARK_PROFILE_DIR=/tmp/workflow-profile \\
    pytest -s tests/benchmarks/db/test_workflow_operations_benchmark.py

``SCIPIONAPI_BENCHMARK_WORKFLOW`` is ``<protocols>x<particles per output>``; ``..._STEPS`` the steps of each
protocol (default 300), ``..._FILES`` the files of each run folder (default 200, of ``..._FILE_KB`` KB).
"""
import cProfile
import io
import json
import os
import pstats
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from pwem import objects as emobj
from pwem.protocols import EMProtocol
from pyworkflow.protocol import STATUS_FINISHED, STATUS_SAVED, params

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory
from app.backend.utils import background_delete
from app.backend.utils.set_item_purge import purgePendingSetItems

RUN_BENCHMARKS = os.getenv("SCIPIONAPI_RUN_BENCHMARKS") == "1"
PROFILE_DIR = (os.getenv("SCIPIONAPI_BENCHMARK_PROFILE_DIR") or "").strip()
PROTOCOL_CLASS = "WorkflowBenchmarkProtocol"
SAMPLING_RATE = 1.25

pytestmark = pytest.mark.skipif(not RUN_BENCHMARKS, reason="Set SCIPIONAPI_RUN_BENCHMARKS=1 to run PostgreSQL benchmarks.")

CLASSES = {name: cls for name, cls in vars(emobj).items() if isinstance(cls, type)}


def _workflowSize():
    protocols, particles = (int(part) for part in os.getenv("SCIPIONAPI_BENCHMARK_WORKFLOW", "10x2000").lower().split("x"))
    return (protocols, particles, int(os.getenv("SCIPIONAPI_BENCHMARK_WORKFLOW_STEPS", "300")),
            int(os.getenv("SCIPIONAPI_BENCHMARK_WORKFLOW_FILES", "200")),
            int(os.getenv("SCIPIONAPI_BENCHMARK_WORKFLOW_FILE_KB", "64")))


class WorkflowBenchmarkProtocol(EMProtocol):
    """A protocol reading the output of the one before (and, every few, of two before)."""

    def _defineParams(self, form):
        form.addSection(label="Input")
        form.addParam("inputParticles", params.PointerParam, pointerClass="SetOfParticles", allowsNull=True)
        form.addParam("otherParticles", params.PointerParam, pointerClass="SetOfParticles", allowsNull=True)

    def _insertAllSteps(self):
        pass

    @classmethod
    def getClassDomain(cls):
        # A plugin protocol gets its domain from its package; this one lives in a test module
        import pwem
        return pwem.Domain


class ParentProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = int(protocolId)

    def getObjId(self):
        return self.protocolId


def _particle(particleId, stackPath):
    particle = emobj.Particle()
    particle.setObjId(particleId)
    particle.setLocation(particleId, stackPath)
    particle.setSamplingRate(SAMPLING_RATE)
    coordinate = emobj.Coordinate()
    coordinate.setPosition(particleId % 4096, (particleId * 3) % 4096)
    coordinate.setMicId(particleId % 500 + 1)
    particle.setCoordinate(coordinate)
    ctf = emobj.CTFModel()
    ctf.setStandardDefocus(12000.0, 11800.0, 45.0)
    particle.setCTF(ctf)
    return particle


def _parentsOf(index):
    """Indexes of the protocols one reads: the one before, and every fifth also the one two before."""
    if index == 0:
        return []
    return [index - 1] + ([index - 2] if index % 5 == 0 and index >= 2 else [])


def _buildWorkflow(db, projectId, projectPath, size):
    """Store the workflow; returns the Scipion protocol ids in order."""
    protocolsCount, particlesCount, stepsCount, filesCount, fileKb = size
    flat = PostgresqlFlatMapper(db)
    setMapper = ScipionSetPostgresqlMapper(db)
    protocolIds = [index + 2 for index in range(protocolsCount)]
    children = {index: [] for index in range(protocolsCount)}
    for index in range(protocolsCount):
        for parent in _parentsOf(index):
            children[parent].append(index)
    dbIds = []
    for index, protocolId in enumerate(protocolIds):
        dbIds.append(flat.saveProtocol({
            "info": {"protocolId": protocolId, "projectId": projectId, "protocolClassName": PROTOCOL_CLASS,
                     "status": STATUS_FINISHED},
            "values": {"runName": "benchmark %d" % protocolId},
            "parentIds": [protocolIds[parent] for parent in _parentsOf(index)],
            "childIds": [protocolIds[child] for child in children[index]],
        }))
    payload = b"\0" * (fileKb * 1024)
    for index, (protocolId, dbId) in enumerate(zip(protocolIds, dbIds)):
        for parentPosition, parent in enumerate(_parentsOf(index)):
            db.execute('INSERT INTO protocol_dependencies ("projectId", "parentProtocolDbId", "childProtocolDbId") '
                       'VALUES (%s, %s, %s)', (projectId, dbIds[parent], dbId))
            db.execute("""INSERT INTO protocol_input_refs ("projectId", "protocolDbId", "protocolId", "inputName",
                              "itemIndex", "parentProtocolDbId", "parentProtocolId", "parentOutputName",
                              "objectClassName", "objectId")
                          VALUES (%s, %s, %s, %s, 0, %s, %s, 'outputParticles', 'SetOfParticles', %s)""",
                       (projectId, dbId, str(protocolId), ("inputParticles", "otherParticles")[parentPosition],
                        dbIds[parent], str(protocolIds[parent]), str(3_000_000 + protocolIds[parent])))
        flat.replaceProtocolSteps(projectId=projectId, protocolDbId=dbId, protocolId=protocolId, steps=[
            {"index": step, "stepClassName": "FunctionStep", "name": "processStep", "status": STATUS_FINISHED,
             "prerequisites": [], "args": [step], "argsText": str(step), "resultFiles": [], "needsGpu": False,
             "schemaVersion": 2} for step in range(stepsCount)])
        runFolder = Path(projectPath) / "Runs" / ("%06d_%s" % (protocolId, PROTOCOL_CLASS)) / "extra"
        runFolder.mkdir(parents=True, exist_ok=True)
        for fileIndex in range(filesCount):
            (runFolder / ("file_%04d.mrc" % fileIndex)).write_bytes(payload)
        stackPath = str(runFolder / "particles.mrcs")
        particles = emobj.SetOfParticles()
        particles.setSamplingRate(SAMPLING_RATE)
        particles.setObjId(3_000_000 + protocolId)
        info = setMapper.reserveRuntimeSet(projectId=projectId, protocolDbId=dbId, outputName="outputParticles",
                                           scipionSet=particles)
        output = PostgresqlRuntimeSetFactory().build(db=db, parent=ParentProtocolStub(protocolId),
                                                     outputName="outputParticles", outputInfo=info,
                                                     classes=CLASSES, cache=False)
        output.enablePostgresqlWrite()
        for particleId in range(1, particlesCount + 1):
            output.append(_particle(particleId, stackPath))
        output.write()
        setMapper.finalizeRuntimeSetOutput(projectId=projectId, protocolDbId=dbId, outputName="outputParticles",
                                           scipionSet=output)
        output.close()
    return protocolIds


def _projectState(db, projectId):
    def scalar(sql):
        return int((db.fetchOne(sql, (projectId,)) or {}).get("n") or 0)
    return {
        "protocols": scalar('SELECT COUNT(*) AS n FROM protocols WHERE "projectId" = %s'),
        "saved": scalar('SELECT COUNT(*) AS n FROM protocols WHERE "projectId" = %s AND status = \'saved\''),
        "sets": scalar('SELECT COUNT(*) AS n FROM scipion_sets WHERE "projectId" = %s'),
        "items": scalar('SELECT COUNT(*) AS n FROM scipion_set_items i JOIN scipion_sets s ON s.id = i."setId" '
                        'WHERE s."projectId" = %s')
        + scalar('SELECT COUNT(*) AS n FROM scipion_set_table_items i JOIN scipion_set_tables t ON t.id = i."tableId" JOIN scipion_sets s ON s.id = t."setId" '
                 'WHERE s."projectId" = %s'),
        "steps": scalar('SELECT COUNT(*) AS n FROM protocol_steps WHERE "projectId" = %s'),
    }


@contextmanager
def _profiled(label):
    if not PROFILE_DIR:
        yield None
        return
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        yield profiler
    finally:
        profiler.disable()
        Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(str(Path(PROFILE_DIR) / ("%s.prof" % label)))
        out = io.StringIO()
        pstats.Stats(profiler, stream=out).sort_stats("cumulative").print_stats(45)
        (Path(PROFILE_DIR) / ("%s.txt" % label)).write_text(out.getvalue())


@pytest.fixture
def workflowProject(postgresqlIntegrationDb, postgresqlMigratedEnv, tmp_path, monkeypatch):
    """A project of its own, with the benchmark protocol class known to the runtime."""
    original = PostgresqlRuntimeMapper._resolveProtocolClass

    def resolve(runtimeMapper, className):
        return WorkflowBenchmarkProtocol if className == PROTOCOL_CLASS else original(runtimeMapper, className)

    monkeypatch.setattr(PostgresqlRuntimeMapper, "_resolveProtocolClass", resolve)
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    suffix = uuid4().hex
    userId = flat.insertUser(email="workflow-benchmark-%s@example.com" % suffix, hashedPassword="benchmark",
                             firstName="Workflow", lastName="Benchmark", institution=None, role="user",
                             isActive=True, isVerified=True, verificationCode="")
    created = []

    def create(label):
        projectPath = tmp_path / ("%s-%s" % (label, uuid4().hex[:8]))
        (projectPath / "Runs").mkdir(parents=True)
        projectId = flat.insertProject(ownerId=userId, name=str(projectPath), description="Workflow benchmark")
        created.append(projectId)
        return projectId, projectPath

    try:
        yield dict(db=db, flat=flat, create=create)
    finally:
        background_delete.waitForBackgroundDeletes(timeout=600)
        for projectId in created:
            try:
                flat.deleteProject(projectId=projectId, ownerId=userId)
            except Exception:
                pass
        db.execute("DELETE FROM users WHERE id = %s", (userId,))


def _service(flat, projectId, projectPath):
    from app.backend.api.services.project_service import ProjectService
    service = ProjectService()
    service._loadPostgresqlRuntimeProject(mapper=flat, projectId=projectId, projectPath=str(projectPath))
    return service


def _timed(db, label, operation):
    db.resetQueryStats()
    startedAt = time.perf_counter()
    with _profiled(label):
        result = operation()
    seconds = time.perf_counter() - startedAt
    stats = db.getQueryStats()
    return result, {"seconds": round(seconds, 3), "queries": stats.get("queryCount"),
                    "querySeconds": round(float(stats.get("querySeconds") or 0), 3)}


def _purgeDeletedItems(db):
    """What the server's purge thread does after the operation: time it, and check nothing is left behind."""
    startedAt = time.perf_counter()
    purged = purgePendingSetItems(db)
    seconds = round(time.perf_counter() - startedAt, 3)
    left = db.fetchOne("""
        SELECT (SELECT COUNT(*) FROM scipion_set_item_purges) AS queued,
               (SELECT COUNT(*) FROM scipion_set_items i
                 WHERE NOT EXISTS (SELECT 1 FROM scipion_sets s WHERE s.id = i."setId")) AS "setItems",
               (SELECT COUNT(*) FROM scipion_set_table_items i
                 WHERE NOT EXISTS (SELECT 1 FROM scipion_set_tables t WHERE t.id = i."tableId")) AS "tableItems"
    """)
    assert int(left["queued"]) == 0 and int(left["setItems"]) == 0 and int(left["tableItems"]) == 0, left
    return {"purgedItems": purged, "purgeSecondsAfter": seconds}


def _report(label, size, measured, before, after, extra=None):
    print("\n[workflow-benchmark] %s" % json.dumps(dict(
        operation=label, protocols=size[0], particlesPerOutput=size[1], stepsPerProtocol=size[2],
        filesPerRun=size[3], **measured, before=before, after=after, **(extra or {}))))


def test_reset_from_the_root_of_a_big_workflow(workflowProject):
    size = _workflowSize()
    projectId, projectPath = workflowProject["create"]("reset")
    db, flat = workflowProject["db"], workflowProject["flat"]
    protocolIds = _buildWorkflow(db, projectId, projectPath, size)
    before = _projectState(db, projectId)
    service = _service(flat, projectId, projectPath)

    result, measured = _timed(db, "reset-from", lambda: service.resetProtocolFrom(flat, projectId, protocolIds[0]))

    background_delete.waitForBackgroundDeletes(timeout=600)
    after = _projectState(db, projectId)
    assert not result.get("errors"), result.get("errors")
    assert after["saved"] == size[0] and after["sets"] == 0 and after["items"] == 0 and after["steps"] == 0
    _report("reset-from", size, measured, before, after, _purgeDeletedItems(db))


def test_restart_of_a_big_workflow_without_running_it(workflowProject, monkeypatch):
    size = _workflowSize()
    projectId, projectPath = workflowProject["create"]("restart")
    db, flat = workflowProject["db"], workflowProject["flat"]
    protocolIds = _buildWorkflow(db, projectId, projectPath, size)
    before = _projectState(db, projectId)
    service = _service(flat, projectId, projectPath)
    enqueued = []
    # Everything a restart does but sending the protocols to the workers
    monkeypatch.setattr(type(service.currentProject), "_enqueuePostgresqlProtocolTask",
                        lambda project, *args, **kwargs: enqueued.append(args) or "benchmark-task", raising=False)

    result, measured = _timed(db, "restart", lambda: service.restartProtocolAll(flat, projectId, protocolIds[0]))

    background_delete.waitForBackgroundDeletes(timeout=600)
    after = _projectState(db, projectId)
    assert not result.get("errors"), result.get("errors")
    assert after["sets"] == 0 and after["items"] == 0
    _report("restart", size, measured, before, after, dict(enqueued=len(enqueued), **_purgeDeletedItems(db)))


def test_delete_of_a_big_workflow(workflowProject):
    size = _workflowSize()
    projectId, projectPath = workflowProject["create"]("delete")
    db, flat = workflowProject["db"], workflowProject["flat"]
    protocolIds = _buildWorkflow(db, projectId, projectPath, size)
    before = _projectState(db, projectId)
    service = _service(flat, projectId, projectPath)

    result, measured = _timed(db, "delete", lambda: service.deleteProtocol(
        flat, projectId, [str(protocolId) for protocolId in protocolIds], protocolIdIsScipionId=True))

    startedAt = time.perf_counter()
    background_delete.waitForBackgroundDeletes(timeout=600)
    backgroundSeconds = round(time.perf_counter() - startedAt, 3)
    after = _projectState(db, projectId)
    assert not result.get("errors"), result.get("errors")
    assert after["protocols"] == 0 and after["sets"] == 0 and after["items"] == 0
    _report("delete", size, measured, before, after,
            dict(backgroundSecondsAfter=backgroundSeconds, **_purgeDeletedItems(db)))
