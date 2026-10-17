"""Warm process that forks a fresh viewer worker per request.

Starting a viewer worker from scratch spends most of its time importing
Scipion and the plugins and discovering the domain. This process does that
once and then, for every request, forks a child that runs the usual worker
module (form or action) exactly as a separate process would: the child reads
the request from its stdin, writes its reply to its stdout, and exits.

Control protocol, one JSON object per line:
  in:  {"id", "module", "stdin", "stdout", "stderr", "revision"}
  out: {"id", "pid"} once forked, then {"id", "exit"} when the child ends,
       or {"id", "stale": true} when the process must be restarted.
The process is stale when the plugins or environment revision changed or a
loaded module file changed (e.g. a plugin edited in develop mode).
"""
from __future__ import annotations

import importlib
import json
import os
import select
import signal
import sys

ALLOWED_MODULES = frozenset({
    'app.backend.api.services.protocol_viewer_dynamic_form_worker',
    'app.backend.api.services.protocol_viewer_action_worker',
})
PRELOAD_SWITCH = 'SCIPION_VIEWER_WARM_PRELOAD'
TEST_MODULES_SWITCH = 'SCIPION_VIEWER_WARM_TEST_MODULES'


def preload():
    """Import Scipion, the plugins and the worker modules; discover the domain."""
    if os.environ.get(PRELOAD_SWITCH, '1') == '0':
        return
    import pyworkflow
    from pyworkflow import Config
    if Config.getDomain() is None:
        Config.setDomain('pwem')
    domain = Config.getDomain()
    domain.getProtocols()
    domain.getViewers()
    import app.backend.api.services.project_service  # noqa: F401
    for module in ALLOWED_MODULES:
        importlib.import_module(module)
    del pyworkflow


def moduleFiles():
    """Modification times of the source files of every loaded module."""
    files = {}
    for module in list(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if isinstance(path, str) and path.endswith('.py'):
            try:
                files[path] = os.stat(path).st_mtime_ns
            except OSError:
                pass
    return files


def changedModuleFiles(snapshot):
    for path, mtime in snapshot.items():
        try:
            if os.stat(path).st_mtime_ns != mtime:
                return True
        except OSError:
            return True
    return False


def allowedModule(name):
    if name in ALLOWED_MODULES:
        return True
    prefixes = [p for p in os.environ.get(TEST_MODULES_SWITCH, '').split(',') if p]
    return any(name.startswith(prefix) for prefix in prefixes)


def runChild(command):
    """In the forked child: become a normal one-shot worker process."""
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    # Database connections are never shared with the warm process.
    engine = getattr(sys.modules.get('app.backend.database'), 'engine', None)
    if engine is not None:
        try:
            engine.dispose(close=False)
        except TypeError:
            engine.pool = engine.pool.recreate()
    code = 1
    try:
        for fd, name, mode in ((0, 'stdin', os.O_RDONLY), (1, 'stdout', os.O_WRONLY),
                               (2, 'stderr', os.O_WRONLY)):
            handle = os.open(command[name], mode)
            os.dup2(handle, fd)
            os.close(handle)
        sys.stdin = open(0, 'r', closefd=False)
        sys.stdout = open(1, 'w', closefd=False)
        sys.stderr = open(2, 'w', closefd=False)
        module = importlib.import_module(command['module'])
        code = int(module.main() or 0)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except BaseException:
        import traceback
        traceback.print_exc()
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(code)


def write(message):
    sys.__stdout__.write(json.dumps(message) + '\n')
    sys.__stdout__.flush()


def serve():
    revision = os.environ.get('SCIPION_VIEWER_WARM_REVISION', '')
    snapshot = moduleFiles()
    children = {}
    write({'ready': True})
    stdin = sys.__stdin__
    while True:
        # Reap finished children and report how they ended.
        while children:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                children.clear()
                break
            if pid == 0:
                break
            requestId = children.pop(pid, None)
            if requestId is not None:
                code = os.waitstatus_to_exitcode(status) if hasattr(os, 'waitstatus_to_exitcode') else (
                    os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status))
                write({'id': requestId, 'exit': code})
        ready, _, _ = select.select([stdin], [], [], 0.05)
        if not ready:
            continue
        line = stdin.readline()
        if not line:
            return  # The API process closed the channel.
        try:
            command = json.loads(line)
        except ValueError:
            continue
        requestId = command.get('id')
        if (not isinstance(command, dict) or not allowedModule(command.get('module', ''))
                or not all(isinstance(command.get(key), str) for key in ('stdin', 'stdout', 'stderr'))):
            write({'id': requestId, 'error': 'invalid_command'})
            continue
        if command.get('revision') != revision or changedModuleFiles(snapshot):
            write({'id': requestId, 'stale': True})
            return
        pid = os.fork()
        if pid == 0:
            runChild(command)
        children[pid] = requestId
        write({'id': requestId, 'pid': pid})


def main():
    try:
        preload()
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
    serve()
    return 0


if __name__ == '__main__':
    sys.exit(main())
