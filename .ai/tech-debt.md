# Tech debt — ScipionAPI

Findings from a real audit of this repo (2026-08-04), not a wishlist. Cited so they're checkable, not just asserted.

## The single largest "god file" across all 5 repos

`app/backend/api/services/project_service.py` — **15176 lines**. By a wide margin the most severe size/complexity outlier in the whole ecosystem (the next largest files anywhere are ~2800-3000 lines). Contains at least one unresolved `# TODO: Find viewers...` (line 5738). Any change here should be treated as high-risk regardless of how small it looks — a file this size almost certainly has non-obvious internal coupling. Splitting it is a real, standalone project, not a drive-by refactor.

Other large files for context: `utils/thumbnail_service.py` (7685 lines), `mapper/postgresql_runtime_mapper.py` (5676 lines), `mapper/scipion_set_mapper.py` (4548 lines), `api/routers/project_router.py` (4290 lines).

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
