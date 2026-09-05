# Tech debt — ScipionAPI

Findings from a real audit of this repo (2026-08-04), refreshed 2026-08-12 against the current `devel` HEAD after a large PostgreSQL-runtime migration push. Cited so they're checkable, not just asserted.

## The single largest "god file" across all 5 repos

`app/backend/api/services/project_service.py` — **15062 lines** (was 15176 on 2026-08-04; it's shrunk and grown several times as runtime work landed, net roughly flat). By a wide margin the most severe size/complexity outlier in the whole ecosystem (the next largest files anywhere are ~4600-7700 lines, see below). Still contains an unresolved `# TODO: Find viewers...` (line 5681). Any change here should be treated as high-risk regardless of how small it looks — a file this size almost certainly has non-obvious internal coupling. Splitting it is a real, standalone project, not a drive-by refactor.

Other large files for context: `utils/thumbnail_service.py` (7685 lines), `mapper/postgresql_runtime_mapper.py` (6379 lines, up from 5676 — grew during the identity/atomicity/SQLite-compat hardening work), `mapper/scipion_set_mapper.py` (4604 lines), `api/routers/project_router.py` (4250 lines).

## Dependency management consolidated in `pyproject.toml`

Resolved: `pyproject.toml` is now the authoritative dependency definition
for both the backend runtime and CLI. Test-only dependencies live under
`[project.optional-dependencies].test`.

`requirements.txt` remains only as a compatibility shim and does not
duplicate dependency versions.

## Scipion core dependencies point at a personal fork, not the official org - intentional for now

```
scipion-pyworkflow @ git+https://github.com/fonsecareyna82/scipion-pyworkflow.git@devel
scipion-em @ git+https://github.com/fonsecareyna82//scipion-em.git@devel
scipion-app @ git+https://github.com/fonsecareyna82//scipion-app.git@devel
```

**This is deliberate, not a bug to fix now.** The fork is ahead of the official `scipion-em` org repos on the current roadmap work (tests/CI/Python 3.8-3.12, AI-agent docs, etc.) - `ScipionAPI` needs to build against the fork's versions of `scipion-pyworkflow`/`scipion-em`/`scipion-app` while that work is in progress, otherwise a fresh `ScipionAPI` would import an old `scipion-em` that doesn't have the changes this whole initiative is making. **Do not point this at the official org until *after* the fork's changes are merged back upstream** - only then should `requirements.txt` (or its `pyproject.toml` successor, see above) switch to tracking the official repos again. Tracked as a post-merge task in `.ai/roadmap.md`.

## Resolved since 2026-08-04

- **CI action versions** — `.github/workflows/tests.yml` is now on `actions/checkout@v7`/`actions/setup-python@v7` (`960c5dd`), matching the 3 core repos.
- **Test suite needed real infrastructure** — `backend-tests` in CI now spins up real PostgreSQL and Valkey service containers and runs the full `pytest` (including `tests/integration/`) across the Python 3.8–3.12 matrix, not just `tests/unit`/`tests/smoke`. The Celery integration test validates broker/result-backend connectivity against Valkey, while `tests/integration/db/test_set_sqlite_compatibility.py` validates the SQLite-compatibility layer against a real PostgreSQL database.
- **Redis server dependency replaced by Valkey** — Valkey is now the supported Celery broker/result-backend server. Celery deliberately continues to use `celery[redis]`, `redis-py`, and `redis://` URLs because those are the compatible Celery transport/client interfaces used to communicate with Valkey.
- **`dump.rdb`/`.backend_reload_marker` tracked in git** — untracked and gitignored (`23cbe02`).

## The native-SQLite staging bridge is permanent, load-bearing debt — not a bug to remove

`mapper/postgresql_runtime_mapper.py::_prepareNativeSetForPostgresqlSnapshot` (and its callers in `createPostgresqlOutputSet`/`_storeSetObject`) writes/closes/reloads a real on-disk SQLite file for any output Set that wasn't created through the PostgreSQL-native runtime factory, then adopts its data into PostgreSQL. This was removed outright on 2026-08-09 (`5a358b6`, `4964eef`) and restored ~50 minutes later the same day (`99d8597`) once it broke a real code path — confirming it's not dead code. It exists because `scipion-pyworkflow`'s `Object`/`Set` machinery still allocates a `SqliteFlatMapper` by default for any protocol using the standard `_defineOutputs` flow; ScipionAPI has no hook to intercept that at creation time without an upstream change to `scipion-pyworkflow/pyworkflow/object.py` (flagged in that repo's own `AGENTS.md` as the highest-blast-radius file in the ecosystem). The rules for when this bridge may exist are formalized in [`postgresql-runtime-compatibility.md`](postgresql-runtime-compatibility.md) — treat that document as authoritative before touching this mechanism, not this note.

## Minor: cosmetic test-teardown warnings

`pytest tests/unit tests/smoke` passes clean (1179 passed as of 2026-08-12) but emits `PytestUnraisableExceptionWarning` from two test doubles whose `__del__`/`close()` contracts are incomplete: `ExplodingSet` (missing `_mapper`) and `FakeWritableMapper` (missing `close`), both in runtime test fixtures. Not a production bug, just noise in CI output — low-priority, drive-by fix whenever those fixture files are next touched.
