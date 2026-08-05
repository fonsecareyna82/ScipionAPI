# Roadmap — ScipionAPI

**Status: draft, pending review with Yunior (repo co-owner).** Seeded from a rough team Google Doc plus findings surfaced while documenting this repo (2026-08-04). Treat as a starting point, not a committed plan.

## This repo specifically

- Consolidate `requirements.txt` into `pyproject.toml` (same pattern as the 3 core repos) — see `.ai/tech-debt.md`.
- Untrack `dump.rdb`/`.backend_reload_marker` and gitignore them.
- Bump `actions/checkout`/`actions/setup-python` to `@v7` in `.github/workflows/tests.yml`.
- Consider a real refactor plan for `app/backend/api/services/project_service.py` (15176 lines) - this is the single largest tech-debt item across all 5 repos by size alone.
- In progress (`app/backend/api/services/project/core/`): during Phase 1 of that split, `external_viewers.py` landed at ~612 lines (target was ~200-500), since discovery/resolution/matching/launch felt like one cohesive responsibility. Worth a second look once the rest of the split is done - split further only if a cleaner boundary is actually apparent then, not as a given.

## For right after the fork merges back upstream

- **Point `requirements.txt` (or its `pyproject.toml` successor) at the official `scipion-em` org repos instead of `fonsecareyna82`'s personal fork.** Not before - the fork is intentionally ahead of upstream on this whole initiative (tests/CI/Python 3.8-3.12, AI-agent docs, the plugin-free-workflows test-debt work, etc.), and `ScipionAPI` needs to build against those in-progress changes, not stale upstream code. Switching too early would silently point a new `ScipionAPI` at an old `scipion-em` and break things. See `.ai/tech-debt.md` for the exact pins.

## Ecosystem-wide (applies to all 5 repos, not just this one)

- **Branch/release cleanup**: drop the redundant `master` branch (if this repo has one - confirm), rename `devel` → `main`, replace push-triggered publish with a manual `workflow_dispatch` release gated by a protected GitHub deployment environment. `I2PC/scipion-em-xmipp`'s `.github/workflows/release.yml` is a concrete reference.
- **This repo is part of the Tkinter replacement** (alongside ScipionWeb) - the legacy Tkinter GUI and an intermediate NiceGUI attempt are what it's replacing.
- **Convert buildbot to a GitHub Actions self-hosted runner.**
- **Set up a dependency manager (Renovate)** across all 5 repos.
