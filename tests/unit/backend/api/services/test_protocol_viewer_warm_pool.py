"""The warm viewer worker forks fresh workers and restarts when stale."""
import json
import os
import time
from pathlib import Path

import pytest

from app.backend.api.services import protocol_viewer_warm_pool as pool
from app.backend.api.services import protocol_viewer_warm_worker as warmWorker

FAKE = 'tests.unit.backend.api.services.fake_viewer_worker'
REPO = Path(__file__).resolve().parents[5]


@pytest.fixture
def env(monkeypatch):
    pool.stopWarmWorker()
    monkeypatch.setenv(pool.WARM_SWITCH, '1')
    monkeypatch.setattr(pool, 'currentRevision', lambda: 'r1')
    environment = dict(os.environ, PYTHONPATH=str(REPO),
                       SCIPION_VIEWER_WARM_PRELOAD='0',
                       SCIPION_VIEWER_WARM_TEST_MODULES='tests.unit.backend.api.services.')
    yield environment
    pool.stopWarmWorker()


def paths(tmp_path, request):
    files = {name: str(tmp_path / name) for name in ('stdin', 'stdout', 'stderr')}
    Path(files['stdin']).write_text(json.dumps(request))
    for name in ('stdout', 'stderr'):
        Path(files[name]).write_text('')
    return files


def reply(files):
    lines = Path(files['stdout']).read_bytes().splitlines()
    return [json.loads(line[len(b'__FAKE__:'):]) for line in lines if line.startswith(b'__FAKE__:')]


def test_requests_are_forked_from_the_warm_process(tmp_path, env):
    files = paths(tmp_path, {'value': 1})
    assert pool.runInWarmWorker(FAKE, files, env, 30) == 0
    assert reply(files) == [{'echo': {'value': 1}}]
    first = pool._warm.process.pid
    files = paths(tmp_path, {'value': 2, 'exit': 3})
    assert pool.runInWarmWorker(FAKE, files, env, 30) == 3
    assert reply(files) == [{'echo': {'value': 2, 'exit': 3}}]
    assert pool._warm.process.pid == first


def test_a_slow_request_is_killed_without_stopping_the_warm_process(tmp_path, env):
    started = time.time()
    with pytest.raises(pool.WarmWorkerTimeout):
        pool.runInWarmWorker(FAKE, paths(tmp_path, {'sleep': 60}), env, 1)
    assert time.time() - started < 15
    assert pool.runInWarmWorker(FAKE, paths(tmp_path, {}), env, 30) == 0


def test_a_new_plugins_or_environment_revision_restarts_the_warm_process(tmp_path, env, monkeypatch):
    assert pool.runInWarmWorker(FAKE, paths(tmp_path, {}), env, 30) == 0
    first = pool._warm.process.pid
    monkeypatch.setattr(pool, 'currentRevision', lambda: 'r2')
    files = paths(tmp_path, {'value': 'after'})
    assert pool.runInWarmWorker(FAKE, files, env, 30) == 0
    assert pool._warm.process.pid != first
    assert reply(files) == [{'echo': {'value': 'after'}}]


def test_only_viewer_worker_modules_can_be_run(tmp_path, env):
    assert pool.runInWarmWorker('os', paths(tmp_path, {}), env, 30) is None


def test_disabled_warm_worker_means_a_cold_worker(tmp_path, env, monkeypatch):
    monkeypatch.setenv(pool.WARM_SWITCH, '0')
    assert pool.runInWarmWorker(FAKE, paths(tmp_path, {}), env, 30) is None


def test_edited_module_files_make_the_warm_process_stale(tmp_path):
    source = tmp_path / 'edited_plugin_module.py'
    source.write_text('VALUE = 1\n')
    snapshot = {str(source): source.stat().st_mtime_ns}
    assert not warmWorker.changedModuleFiles(snapshot)
    os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 1_000_000))
    assert warmWorker.changedModuleFiles(snapshot)
    source.unlink()
    assert warmWorker.changedModuleFiles(snapshot)


def test_prestarting_warms_up_without_blocking(tmp_path, env):
    pool.prestartWarmWorker(env)
    deadline = time.time() + 30
    while (pool._warm is None or not pool._warm._ready.is_set()) and time.time() < deadline:
        time.sleep(0.05)
    warm = pool._warm
    assert warm is not None and warm.alive
    assert pool.runInWarmWorker(FAKE, paths(tmp_path, {}), env, 30) == 0
    assert pool._warm is warm
