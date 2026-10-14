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

## Packaging

`pyproject.toml` is the authoritative dependency definition for both the
ScipionAPI backend and the packaged `scipionapi_cli` CLI.

Runtime dependencies live in `[project].dependencies`. Test-only
dependencies (`pytest`, `pytest-asyncio`, `httpx`) live in `[project.optional-dependencies].test`.

`requirements.txt` is retained only as a compatibility shim and installs
the editable project with test dependencies. New install/bootstrap/update
code must install from `pyproject.toml`, not maintain a second dependency list.

## Testing

- CI already exists: `.github/workflows/tests.yml`, matrix Python 3.8–3.12, `pytest.ini` with `testpaths = tests`, using `actions/checkout@v7` and `actions/setup-python@v7`.
- Run locally: needs real Postgres + Valkey (see `scipionapi_cli/provision.py`/`db.py` for setup), then `pip install -e ".[test]" && pytest`.
- `pytest-asyncio` is part of the test extra; keep it compatible with Python 3.8–3.12 so marked async tests execute throughout the CI matrix.
- The thumbnail route tests call their coroutines with `asyncio.run()` from ordinary tests, so those checks also execute when async plugin loading is disabled.
- Unhandled async tests and unraisable teardown exceptions are errors in `pytest.ini`; do not silence them or rely on garbage collection for resource cleanup.
- `tests/smoke/` (e.g. `test_app_import.py`, `test_main_app.py`) is the fastest thing to run to sanity-check the app still imports/boots.

## PostgreSQL runtime Set contract

PostgreSQL is the only authoritative runtime persistence for Scipion Sets. Temporary SQLite files are allowed only as worker-local compatibility snapshots for legacy code that explicitly calls `Set.getFileName()`.

These snapshots must remain under `/tmp/postgresql-runtime-sets/worker-<PID>/`, must be isolated per consumer worker, and must refresh at the same path when the PostgreSQL revision changes. Never replace this with one SQLite file shared by the producer and consumers, and never create compatibility SQLite files inside `Runs/`.

Input restoration and compatibility materialization must not mutate or persist parent protocols or their canonical outputs.

Ordinary-item compatibility snapshots initialize their SQLite schema from the
complete persisted PostgreSQL columns before copying items, so optional fields
first present in later items remain readable. Do not infer that schema only
from the first item or scan all items to build it.

Runtime Set iteration uses independent server cursors with `WITH HOLD`, decodes
rows in batches and hydrates only consumed objects. At commit, PostgreSQL spools
remaining source rows on the server while preserving their snapshot. Hydrators
prepare access-path metadata per schema and still resolve owners and call native
setters for every row; custom hydration hooks retain the generic path.
Pointer-free items with primitive values can consume their own freshly
collected graph during serialization. Never reuse item values between appends;
custom conversion/introspection hooks keep the general serialization route.
Native runtime appends use a compact buffer that spills above
8 MiB into an anonymous worker-local temporary file until the existing flush
boundary; custom serializers retain deferred conversion. Root bulk writes update canonical and logical item tables in
one SQL statement per chunk, inside one transaction covering the entire flush.
Preserve rollback/retry behavior and both stored representations.

Nested runtime Sets revalidate their current logical table with a scoped
identity query instead of loading every class or tilt-series table. Native
child appends are buffered without a lookup per item; flushing revalidates
the table and restores queued schema paths if it was replaced. Schema growth
still validates the current table before writing columns. Once an
owned writable child mapper has flushed, parent updates may reuse its exact
persisted table without copying the child items again. External/SQLite-backed
children and mismatched or pending mapper scopes still use snapshot import.
Set properties read a Set's sampling-rate getter before falling back to its
first item, avoiding implicit SQLite materialization of native class Sets.
Child reads resolve the table identity once per query, never per hydrated
row. A parent's `_setItemMapperPath` hook does not export the parent for
runtime children, which load their own mapper; subclass hook code still runs.
Set iteration builds a new item per row by default. `SCIPIONAPI_SET_ITEM_TEMPLATE=1`
opts into native template reuse for `iterItems()`/`for x in set` (honoring
`SCIPION_MAPPER_USE_TEMPLATE`); `set[id]`, `getFirstItem()` and `iterate=False`
always return independent objects, and nested Set items are always built anew.
Enable it only once every plugin in use clones the items it keeps; code here
that keeps iterated items must clone them or pass `iterate=False`.

Neither canonical root nor logical items keep a JSON GIN. Migration
`b75a4e291c0f` drops the canonical root GIN; `9d064ee31b1b` dropped the
partial nested GIN (added by `41c8d93e7a62`). Normal reads use the scoped
item indexes. Rare or absent undeclared-field type lookups scan a root Set,
which can cost more for very large Sets. Dynamic logical-field discovery still
reads both parent populations in one statement so legacy null-parent rows
remain readable. These migrations run concurrently, retry failed builds, and
do not change item data.

Read [`.ai/postgresql-runtime-compatibility.md`](.ai/postgresql-runtime-compatibility.md) before changing runtime Sets, streaming inputs, `getFileName()`, `Set.load()`, output restoration, or SQLite materialization.

## Known gotchas

- **`pyproject.toml` currently pulls `scipion-pyworkflow`, `scipion-em`,and `scipion-app` from Yunior's fork `devel` branches rather than the official Scipion repositories. This is intentional while the fork remains ahead of upstream.
- **Runtime-generated persistence artifacts are not source files**: files such as `dump.rdb` and `.backend_reload_marker` are gitignored and must remain untracked.
- **Valkey intentionally still uses the Redis Celery transport/client stack**: `celery[redis]`, `redis-py`, and `redis://`/`rediss://` URLs remain correct. Do not replace them merely because the server is Valkey.
- `pydantic==1.10.x` pin (see Stack above) — a real, easy-to-violate-by-accident constraint.
- `scipion_home/` is gitignored and holds a local `.env` — not a leak, just local config; don't assume secrets belong there or that it's meant to be committed.

## Keeping this document current

This file describes the repo as of the last time someone updated it — it will drift out of date as the code changes. If your change touches anything described above (stack, architecture map, testing setup, dependencies, gotchas), update the relevant section in this file as part of the same change, not as a separate follow-up. Don't wait to be asked.
