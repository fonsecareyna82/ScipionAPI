# Tech debt — ScipionAPI

Findings from a real audit of this repo (2026-08-04), not a wishlist. Cited so they're checkable, not just asserted.

## `project_service.py` — largest file in the ecosystem, now substantially decomposed (2026-08-06)

`app/backend/api/services/project_service.py` was **15176 lines** as a single undifferentiated `ProjectService` class - by far the most severe size/complexity outlier in the whole ecosystem. Split across 8 phases (branch `refactor/split-project-service`) into ~30 focused, independently-testable modules under `app/backend/api/services/project/core/` (~5900 lines total, none over ~610 lines), each targeting a single responsibility (preview-by-output-type, protocol graph, workflow import/export, project CRUD/sharing/paths, etc.) and verified against the full unit suite after every extraction (1077/1077 passing throughout, zero behavior changes).

`project_service.py` itself is now **9974 lines** - still the largest file in the ecosystem, but what remains is genuine composition-root orchestration (methods that wire together the extracted `core/` modules, mutate the few real instance-state fields like `currentProject`/`manager`, or are directly monkeypatched by name in tests and so need to stay as named seams) rather than undifferentiated bulk. Splitting it further is possible but has diminishing returns - the remaining large methods (`_migrateImportedProjectToPostgresql`, `applyWorkflowToProject`, `exportWorkflowProtocolsService`, the big preview-orchestration methods) are inherently imperative glue with real side effects, not pure computation.

Contains at least one unresolved `# TODO: Find viewers...` (line 3177) - not addressed by this refactor, out of scope.

Other large files for context: `utils/thumbnail_service.py` (7685 lines), `mapper/postgresql_runtime_mapper.py` (6027 lines), `mapper/scipion_set_mapper.py` (4676 lines), `api/routers/project_router.py` (4250 lines).

## Dependency management split across two files

`pyproject.toml` only packages the `scipionapi_cli` CLI (a handful of deps: `typer`, `rich`, `python-dotenv`); the full backend stack (FastAPI, Celery, SQLAlchemy, pydantic, and the ecosystem packages) lives in `requirements.txt`, installed separately. **Recommended fix (not executed - documentation only for now): consolidate into `pyproject.toml`'s `dependencies`/`[project.optional-dependencies]`, same pattern already applied to `scipion-pyworkflow`/`scipion-em`/`scipion-app`.** This would also be the natural place to fix the fork-pin issue below while touching this file.

## `requirements.txt` points at a personal fork, not the official org - intentional for now

```
scipion-pyworkflow @ git+https://github.com/fonsecareyna82/scipion-pyworkflow.git@devel
scipion-em @ git+https://github.com/fonsecareyna82//scipion-em.git@devel
scipion-app @ git+https://github.com/fonsecareyna82//scipion-app.git@devel
```

**This is deliberate, not a bug to fix now.** The fork is ahead of the official `scipion-em` org repos on the current roadmap work (tests/CI/Python 3.8-3.12, AI-agent docs, etc.) - `ScipionAPI` needs to build against the fork's versions of `scipion-pyworkflow`/`scipion-em`/`scipion-app` while that work is in progress, otherwise a fresh `ScipionAPI` would import an old `scipion-em` that doesn't have the changes this whole initiative is making. **Do not point this at the official org until *after* the fork's changes are merged back upstream** - only then should `requirements.txt` (or its `pyproject.toml` successor, see above) switch to tracking the official repos again. Tracked as a post-merge task in `.ai/roadmap.md`.

## CI still on older action versions

`.github/workflows/tests.yml` uses `actions/checkout@v4` and `actions/setup-python@v5` - the 3 core repos were bumped to `@v7` this session (clears a Node.js-version deprecation warning GitHub surfaces on older majors). Same fix would apply here.

## Test suite needs real infrastructure

`tests/integration/` needs a real Postgres + Redis instance - not something CI-collectible without provisioning first. `tests/unit/` and `tests/smoke/` don't have this constraint.
