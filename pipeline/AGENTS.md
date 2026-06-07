# AGENTS.md

> **Workspace-Standards:** Die verbindliche Leitkonvention steht in `_docs/CONVENTIONS.md`
> (am Workspace-Root `/Users/Shared/code/`), Modell comply-or-explain. Offene Punkte fuer
> dieses Repo siehe Abschnitt "Offene Konventions-Punkte".

Guidance for AI coding agents working in this repository. Human-facing docs live in
`README.md`, `CONTRIBUTING.md`, and `docs/`.

## Offene Konventions-Punkte

- [ ] CORE-GIT-01 — GitHub-Mirror-Remote (`github`) zusaetzlich zu Codeberg-`origin` anlegen.
- [ ] CORE-AGENT-01 — Abschnitt "Abweichungen von der Leitkonvention" in dieser AGENTS.md ergaenzen.
- [ ] CORE-AGENT-04 — `docs/superpowers/plans/` fuer Implementierungsplaene anlegen (nur `specs/` vorhanden).
- [ ] PROF-NAT-02 — version-bump-Script ergaenzen, das `pyproject.toml`-Version + `Info.plist`/`AutoSplat.spec` (CFBundleShortVersionString) synct.
- [ ] PROF-NAT-03 — `docs/MACOS-APP.md`/`MACOS-INSTALL.md` (Signing, Notarization, "Trotzdem oeffnen") anlegen; Install-Doku liegt bisher nur im README.

## Project

`autosplat` — an automated local pipeline that turns drone/handheld video into a trained
3D Gaussian Splat. Apple-Silicon-only by design (macOS 15+, M-series). Single maintainer,
AGPL-3.0 code / CC BY-SA 4.0 docs.

Pipeline stages: preprocess (FFmpeg; auto-tone-maps HDR HLG/PQ → SDR) → SfM (COLMAP) →
quality gate → train (Brush) → export PLY → compress → Obsidian capture-note →
SuperSplat auto-open.

## Setup & commands

```bash
uv sync                                  # install deps (Python 3.11+, uv-managed)
uv run autosplat doctor                  # check ffmpeg / colmap / brush / compress
uv run pytest -q                         # unit tests (~7s) — run before every commit
uv run ruff check src/ tests/            # lint
uv run ruff format src/ tests/           # format
uv run mypy src/                         # type-check (strict mode)
```

Opt-in tests (need external binaries, off by default):

```bash
AUTOSPLAT_E2E=1 uv run pytest             # full end-to-end (ffmpeg + colmap + brush)
AUTOSPLAT_COMPRESS_E2E=1 uv run pytest tests/test_compress.py
```

Test markers: `slow`, `needs_ffmpeg`, `needs_colmap`, `needs_brush`, `needs_supersplat_dist`.

## Layout

```
src/autosplat/      # pipeline modules: config, logging, doctor, preflight, preprocess,
                    #   sfm, quality, train, export, compress, viewer, watcher,
                    #   obsidian, notification, pipeline, cli
src/autosplat/webui/ # FastAPI + HTMX + Jinja2 browser UI (app, routes/, jobs_runner,
                    #   state, templates/, static/)
config/default.toml # all config defaults; user overrides at ~/.config/autosplat/config.toml
tests/              # one test_<module>.py per src module; fixtures in tests/fixtures/
docs/               # spec, architecture, configuration, workflows, phase reports
scripts/            # install_deps.sh, fetch_brush.sh, install_splat.sh, setup_supersplat.sh
examples/           # ready-made --config overlays
```

The authoritative spec is `docs/AUTO-SPLAT PIPELINE — Spec & Implementation Plan.md`.
If a change materially alters the surface, update the spec or call out the divergence.

## Code style

- Ruff: line-length 100, target py311, rules `E,F,I,B,UP,SIM,RUF` (see `pyproject.toml`
  for the ignore list). Formatting is ruff-format — do not hand-format.
- mypy runs in `strict` mode; keep new code fully typed.
- Typer for CLI, Pydantic v2 for models, structlog for logging, Rich for terminal output.
- Pipeline failures must be deterministic and structured: emit a typed event into
  `state.json`, never hang or fail silently.

## Workflow conventions

- **TDD, red first.** Write the failing test, then the implementation. New features land
  with tests; the bar for "unit-tested" is intentionally low — match existing `tests/`.
- **Atomic slices.** Implement in small, self-contained slices; commit per slice; cut a
  release only after a bundle of slices is complete.
- **HTTP code needs real request tests.** WebUI / server changes must be covered with
  actual HTTP requests (httpx), not just mocked units — past CORS bugs slipped through
  mock-only coverage.
- Pre-commit hooks run ruff + ruff-format on commit and `mypy src/` + `pytest` on push.
  Install once with `pre-commit install`. Do not use `--no-verify` to bypass a failing
  hook — fix it.

## Commits

- Conventional-commits style: `feat(scope): …`, `fix(scope): …`, `docs(scope): …`,
  `chore(scope): …`.
- Commits with substantial AI input add the trailer:
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- Create new commits; do not amend or force-push without explicit instruction.
- Remote is Codeberg (Forgejo) at `codeberg.org/jkaindl/video-to-3d-gaussian-splat`.

## Scope boundaries

Out of scope (do not add without discussion): Windows/Linux support, cloud/remote
training, mesh extraction from splats. The pipeline is deliberately local-first and
Mac-Silicon-only.
