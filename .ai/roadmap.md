# Roadmap — ScipionAPI

**Status: draft, pending review with Yunior (repo co-owner).** Seeded from a rough team Google Doc plus findings surfaced while documenting this repo (2026-08-04), refreshed 2026-08-12. Treat as a starting point, not a committed plan.

## This repo specifically

- ~~Consolidate `requirements.txt` into `pyproject.toml`~~ — done. `pyproject.toml` is now the authoritative runtime/test dependency definition; `requirements.txt` remains only as a compatibility shim.
- Consider a real refactor plan for `app/backend/api/services/project_service.py` (15062 lines) - this is the single largest tech-debt item across all 5 repos by size alone. Still open; the file has stayed roughly flat in size despite heavy runtime work landing elsewhere.
- ~~Bump `actions/checkout`/`actions/setup-python` to `@v7`~~ — done (`960c5dd`).
- ~~Get `tests/integration/` running in CI against real Postgres/Valkey~~ — done: `backend-tests` provisions `postgres:16` and Valkey service containers and runs the full suite across the Python 3.8–3.12 matrix. The Celery integration test validates the configured broker and result backend against the real Valkey service. Possible next step: extend that same real-infra coverage to load/performance scenarios beyond the current benchmarks in `tests/integration/db/test_postgresql_observability.py`, if that's a priority.
## For right after the fork merges back upstream

- **Point `pyproject.toml` at the official `scipion-em` org repos instead of `fonsecareyna82`'s personal fork.** Not before - the fork is intentionally ahead of upstream on this whole initiative (tests/CI/Python 3.8-3.12, AI-agent docs, the plugin-free-workflows test-debt work, etc.), and `ScipionAPI` needs to build against those in-progress changes, not stale upstream code. Switching too early would silently point a new `ScipionAPI` at an old `scipion-em` and break things. See `.ai/tech-debt.md` for the exact pins.

## Ecosystem-wide (applies to all 5 repos, not just this one)

- **Branch/release cleanup**: drop the redundant `master` branch (if this repo has one - confirm), rename `devel` → `main`, replace push-triggered publish with a manual `workflow_dispatch` release gated by a protected GitHub deployment environment. `I2PC/scipion-em-xmipp`'s `.github/workflows/release.yml` is a concrete reference.
- **This repo is part of the Tkinter replacement** (alongside ScipionWeb) - the legacy Tkinter GUI and an intermediate NiceGUI attempt are what it's replacing.
- **Convert buildbot to a GitHub Actions self-hosted runner.**
- **Set up a dependency manager (Renovate)** across all 5 repos.
