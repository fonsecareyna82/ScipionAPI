# Roadmap — ScipionAPI

**Status: draft, pending review with Yunior (repo co-owner).** Seeded from a rough team Google Doc plus findings surfaced while documenting this repo (2026-08-04). Treat as a starting point, not a committed plan.

## This repo specifically

- Consolidate `requirements.txt` into `pyproject.toml` (same pattern as the 3 core repos), and fix the fork-pin so it points at the official `scipion-em` org repos instead of a personal fork — see `.ai/tech-debt.md`.
- Untrack `dump.rdb`/`.backend_reload_marker` and gitignore them.
- Bump `actions/checkout`/`actions/setup-python` to `@v7` in `.github/workflows/tests.yml`.
- Consider a real refactor plan for `app/backend/api/services/project_service.py` (15176 lines) - this is the single largest tech-debt item across all 5 repos by size alone.

## Ecosystem-wide (applies to all 5 repos, not just this one)

- **Branch/release cleanup**: drop the redundant `master` branch (if this repo has one - confirm), rename `devel` → `main`, replace push-triggered publish with a manual `workflow_dispatch` release gated by a protected GitHub deployment environment. `I2PC/scipion-em-xmipp`'s `.github/workflows/release.yml` is a concrete reference.
- **This repo is part of the Tkinter replacement** (alongside ScipionWeb) - the legacy Tkinter GUI and an intermediate NiceGUI attempt are what it's replacing.
- **Convert buildbot to a GitHub Actions self-hosted runner.**
- **Set up a dependency manager (Renovate)** across all 5 repos.
