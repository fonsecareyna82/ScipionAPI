# Roadmap — ScipionAPI

**Status: draft, pending review with Yunior (repo co-owner).** Seeded from a rough team Google Doc plus findings surfaced while documenting this repo (2026-08-04). Treat as a starting point, not a committed plan.

## This repo specifically

- Consolidate `requirements.txt` into `pyproject.toml` (same pattern as the 3 core repos) — see `.ai/tech-debt.md`.
- Bump `actions/checkout`/`actions/setup-python` to `@v7` in `.github/workflows/tests.yml`.
- **`project_service.py` split into `app/backend/api/services/project/core/` — done (8 phases, branch `refactor/split-project-service`), see `.ai/tech-debt.md` for the current state.** Two follow-ups deliberately deferred rather than bundled in:
  - **Router migration**: `project_router.py`'s ~90 endpoints and the two external "private method" consumers (`protocol_service.py` → `ProjectService()._loadPostgresqlRuntimeProject`, `protocol_steps_sync.py` → `service._shouldRegisterProtocolOutputs`/`registerOutput`) still go through `ProjectService` rather than calling the new `project/core/` modules or `app/backend/runtime/*` services directly. Both of those specific methods are already thin delegators to already-extracted services, so the remaining work is purely updating the two call sites - low risk, but a distinct task from the service-layer split itself.
  - `external_viewers.py` (~612 lines) and `protocol_graph_builder.py` (~500 lines) are the two `project/core/` modules over the original ~200-500 line target - each is one cohesive responsibility (external-viewer discovery/resolution/matching/launch; the protocol-graph-node-assembly loop), not obviously further divisible. Worth a second look if either grows again, not a given split.

## For right after the fork merges back upstream

- **Point `requirements.txt` (or its `pyproject.toml` successor) at the official `scipion-em` org repos instead of `fonsecareyna82`'s personal fork.** Not before - the fork is intentionally ahead of upstream on this whole initiative (tests/CI/Python 3.8-3.12, AI-agent docs, the plugin-free-workflows test-debt work, etc.), and `ScipionAPI` needs to build against those in-progress changes, not stale upstream code. Switching too early would silently point a new `ScipionAPI` at an old `scipion-em` and break things. See `.ai/tech-debt.md` for the exact pins.

## Ecosystem-wide (applies to all 5 repos, not just this one)

- **Branch/release cleanup**: drop the redundant `master` branch (if this repo has one - confirm), rename `devel` → `main`, replace push-triggered publish with a manual `workflow_dispatch` release gated by a protected GitHub deployment environment. `I2PC/scipion-em-xmipp`'s `.github/workflows/release.yml` is a concrete reference.
- **This repo is part of the Tkinter replacement** (alongside ScipionWeb) - the legacy Tkinter GUI and an intermediate NiceGUI attempt are what it's replacing.
- **Convert buildbot to a GitHub Actions self-hosted runner.**
- **Set up a dependency manager (Renovate)** across all 5 repos.
