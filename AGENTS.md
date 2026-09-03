# ScipionAPI — developer manual for AI agents

Read this before making changes here. Written for an AI coding agent, not end users — see `README.rst` for that.

For deeper, less-frequently-needed context, see:
- [`.ai/tech-debt.md`](.ai/tech-debt.md) — known problem areas, with file:line
- [`.ai/roadmap.md`](.ai/roadmap.md) — planned/likely future work (draft, pending team review)
- [`.ai/postgresql-runtime-compatibility.md`](.ai/postgresql-runtime-compatibility.md) — mandatory PostgreSQL runtime Set, streaming, concurrency, and legacy SQLite compatibility rules

## What this repo is

A FastAPI backend exposing Scipion project management, protocol interaction, output browsing/previews, plugin inspection, and auth over a REST API. Part of the intended replacement for the Tkinter desktop GUI (alongside ScipionWeb, the React frontend that talks to this backend). **Not standalone** — runs inside a Scipion-capable Python environment and imports `pyworkflow`/`pwem` directly at runtime (`app/backend/runtime/*`, `app/backend/utils/outputs_preview.py`), and depends on `scipion-app`'s `PluginRepository` (`app/backend/api/services/plugin_service.py:15`).

## Stack

FastAPI + Uvicorn, PostgreSQL via SQLAlchemy 2.0 + Alembic migrations, Celery + Valkey for task brokering/result storage, JWT auth(`app/backend/utils/jwt.py`). **`pydantic` is pinned to 1.10.x** (`requirements.txt:22-23`, conditional on `python_version`) — this is deliberate, not an oversight; introducing Pydantic v2 syntax (`model_config`, `field_validator`, ...) anywhere will break the build until a real migration is planned.

## Architecture map

- `app/backend/api/` — FastAPI routers.
- `app/backend/mapper/` — data-access layer (SQLAlchemy models + a separate flat Postgres mapper for some relational features, e.g. project shares).
- `app/backend/models/` — Pydantic (v1) request/response schemas.
- `app/backend/project/`, `app/backend/runtime/` — the layer that actually talks to Scipion (`pyworkflow`/`pwem` imports live here).
- `app/backend/utils/`, `app/backend/viewers/` — including `outputs_preview.py`, which imports `pwem.emlib`/`pwem.viewers` directly.
- `app/workers/` — Celery worker + config (`celery_worker.py`, `celeryconfig.py`).
- `scipionapi_cli/` — a separate, packaged admin/provisioning CLI (`scipionapi` console script): `bootstrap.py`, `provision.py`, `db.py`, `admin.py`, `doctor.py`. This is what sets up Postgres/Valkey/the Scipion env for a fresh install — not "clone and pytest," there's a real provisioning flow.
- `tests/{unit,integration,smoke}/` — `integration/` needs real Postgres+Valkey running (`tests/integration/db/test_migrations.py`, `tests/integration/workers/test_task_queue.py` will fail without them); `unit/` and `smoke/` don't.

## Packaging note (two files, deliberately)

Unlike the 3 core repos (which consolidated test deps into `pyproject.toml`'s `[project.optional-dependencies]`), **this repo currently splits dependencies across two files**: `pyproject.toml` only packages the `scipionapi_cli` CLI itself (`typer`, `rich`, `python-dotenv` — installed via `pip install -e .`), while `requirements.txt` carries the full backend runtime stack (FastAPI, Celery, SQLAlchemy, pydantic, and the ecosystem packages below). Both are installed together in CI (`pip install -r requirements.txt && pip install -e .`). See `.ai/tech-debt.md` for the consolidation recommendation.

## Testing

- CI already exists: `.github/workflows/tests.yml`, matrix Python 3.8–3.12, `pytest.ini` with `testpaths = tests`, using `actions/checkout@v7` and `actions/setup-python@v7`.
- Run locally: needs real Postgres + Valkey (see `scipionapi_cli/provision.py`/`db.py` for setup), then `pip install -r requirements.txt && pip install -e . && pytest`.
- `tests/smoke/` (e.g. `test_app_import.py`, `test_main_app.py`) is the fastest thing to run to sanity-check the app still imports/boots.

## PostgreSQL runtime Set contract

PostgreSQL is the only authoritative runtime persistence for Scipion Sets. Temporary SQLite files are allowed only as worker-local compatibility snapshots for legacy code that explicitly calls `Set.getFileName()`.

These snapshots must remain under `/tmp/postgresql-runtime-sets/worker-<PID>/`, must be isolated per consumer worker, and must refresh at the same path when the PostgreSQL revision changes. Never replace this with one SQLite file shared by the producer and consumers, and never create compatibility SQLite files inside `Runs/`.

Input restoration and compatibility materialization must not mutate or persist parent protocols or their canonical outputs.

Read [`.ai/postgresql-runtime-compatibility.md`](.ai/postgresql-runtime-compatibility.md) before changing runtime Sets, streaming inputs, `getFileName()`, `Set.load()`, output restoration, or SQLite materialization.

## Known gotchas

- **`requirements.txt` pulls `scipion-pyworkflow`/`scipion-em`/`scipion-app` from a personal fork** (`git+https://github.com/fonsecareyna82/...@devel`), not the official `scipion-em` GitHub org. Installing from this file alone gets you Yunior's fork state, which may be ahead of or diverge from the official repos — if you're testing changes made in this workspace's own checkouts of those 3 repos, you likely need an editable local install instead, not whatever `requirements.txt` resolves to.
- **Runtime-generated persistence artifacts are not source files**: files such as `dump.rdb` and `.backend_reload_marker` are gitignored and must remain untracked.
- **Dev auto-reload on plugin install/uninstall requires `BACKEND_RELOAD_MODE=dev` in `.env` *and* `./scripts/scipionapi start`/`restart` (not a manually-run `uvicorn` command)**: plugin install/uninstall (`app/backend/api/services/reload_trigger.py`) touches a marker file (`BACKEND_RELOAD_TOUCH_PATH`, default `.backend_reload_marker`) meant to make the API process restart itself and pick up the refreshed `Domain`/plugin state. `scipionapi_cli/runtime.py`'s `_buildUvicornArgs` only adds `uvicorn --reload --reload-include <touchPath>` when `AUTO_RELOAD_ON_PLUGIN_CHANGE=1` and `BACKEND_RELOAD_MODE=dev` are both set — a fresh install defaults to `BACKEND_RELOAD_MODE=prod` (`scipionapi_cli/install.py`'s `_buildBackendReloadEnvUpdates`), which is correct for prod (a systemd/k8s watcher, not uvicorn, should watch the marker there) but means dev users must explicitly set `BACKEND_RELOAD_MODE=dev` in their `.env` once. That override now survives repeat `install`/`provision` runs (previously these 3 keys were force-reset to prod defaults every time — fixed).
  - `--reload-include` must be a **cwd-relative** glob (uvicorn resolves it via `Path.glob()`, which raises `NotImplementedError` for an absolute pattern) — `_buildUvicornArgs` passes `BACKEND_RELOAD_TOUCH_PATH` through as-is when relative (matching `reload_trigger.py`'s own dev-mode resolution, both anchored at `repoRoot`) and skips `--reload-include` entirely if it's absolute.
  - **This dev-mode reload only actually works if `SCIPION_HOME` lives outside the repo, or the OS's `fs.inotify.max_user_watches` is raised.** uvicorn's `WatchFilesReload` (this uvicorn version) always adds `Path.cwd()` to its watched roots regardless of `--reload-dir`/`--reload-exclude` — those only filter *which detected changes* trigger a restart, they don't reduce how many directories get an inotify watch registered in the first place (`FileFilter` in `uvicorn/supervisors/watchfilesreload.py` runs after `watch(..., watch_filter=None)`). If `SCIPION_HOME` is a subdirectory of the repo (a common local dev layout — it holds `software/` with real installed EM packages, tens of thousands of files), the recursive watch blows past the default 65536 limit with `OSError: OS file watch limit reached`, killing the reload supervisor. No code-level fix resolves this; it's a real environment precondition, not a bug to chase further here.
- **Valkey intentionally still uses the Redis Celery transport/client stack**: `celery[redis]`, `redis-py`, and `redis://`/`rediss://` URLs remain correct. Do not replace them merely because the server is Valkey.
- `pydantic==1.10.x` pin (see Stack above) — a real, easy-to-violate-by-accident constraint.
- `scipion_home/` is gitignored and holds a local `.env` — not a leak, just local config; don't assume secrets belong there or that it's meant to be committed.

## Keeping this document current

This file describes the repo as of the last time someone updated it — it will drift out of date as the code changes. If your change touches anything described above (stack, architecture map, testing setup, dependencies, gotchas), update the relevant section in this file as part of the same change, not as a separate follow-up. Don't wait to be asked.
