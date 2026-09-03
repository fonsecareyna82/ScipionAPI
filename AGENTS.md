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
- **Valkey intentionally still uses the Redis Celery transport/client stack**: `celery[redis]`, `redis-py`, and `redis://`/`rediss://` URLs remain correct. Do not replace them merely because the server is Valkey.
- `pydantic==1.10.x` pin (see Stack above) — a real, easy-to-violate-by-accident constraint.
- `scipion_home/` is gitignored and holds a local `.env` — not a leak, just local config; don't assume secrets belong there or that it's meant to be committed.

## Keeping this document current

This file describes the repo as of the last time someone updated it — it will drift out of date as the code changes. If your change touches anything described above (stack, architecture map, testing setup, dependencies, gotchas), update the relevant section in this file as part of the same change, not as a separate follow-up. Don't wait to be asked.
