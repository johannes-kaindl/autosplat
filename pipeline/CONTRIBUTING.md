# Contributing

`auto-splat-pipeline` is a **personal tool** built for one specific Mac-Silicon-only Gaussian-Splatting workflow. It's not actively soliciting contributions — but issues and PRs are welcome if you find a sharp edge.

## Bug reports

Use the [Codeberg issue tracker](https://codeberg.org/jkaindl/video-to-3d-gaussian-splat/issues) — the bug-report and feature-request templates in `.forgejo/issue_template/` prompt for everything below.

Please include:

- macOS version + CPU (`uname -a`)
- `autosplat doctor` output
- The relevant `pipeline.log` from `<capture-dir>/pipeline.log`
- Steps to reproduce, including the source video properties (`ffprobe`)

For security-sensitive reports see [`SECURITY.md`](SECURITY.md).

## Development setup

```bash
git clone https://codeberg.org/jkaindl/video-to-3d-gaussian-splat.git
cd video-to-3d-gaussian-splat
uv sync                          # install deps (Python 3.11+, uv-managed)
uv run pre-commit install        # install pre-commit hooks (ruff + ruff-format on commit, pytest on push)
uv run autosplat doctor          # check ffmpeg / colmap / brush / compress
```

## Contributor License Agreement (CLA)

Contributions are accepted under a lightweight [Contributor License Agreement](CLA.md). In short:

- **You keep your copyright** — the CLA is not an assignment.
- You grant the maintainer a relicensing right, so the project can stay AGPL for the commons **and** be offered under a separate commercial license to parties who can't comply with AGPL §13.
- Your contribution stays in the commons under AGPL-3.0-or-later (inbound = outbound).

By opening a pull request you accept the CLA. For any non-trivial change, make it explicit with a sign-off (`git commit -s`):

```
Signed-off-by: Your Name <your-email@example.com>
```

This exists for one reason: accepting even a single non-trivial PR *without* a relicensing grant would permanently remove the option to dual-license. The CLA is the insurance against that one irreversible mistake — see [`CLA.md`](CLA.md) for the full text.

## Pull requests

1. **Tests first.** TDD with a failing test, then the implementation. New features land with tests. The bar for "unit-tested" is intentionally low — match what's in `tests/`.
2. **Run the local suite before pushing:**
   ```bash
   uv run pytest -q                    # 267 unit tests, ~7s
   uv run ruff check src/ tests/       # lint
   uv run ruff format src/ tests/      # format (do not hand-format)
   uv run mypy src/                    # type-check (strict mode)
   ```
3. **HTTP code needs real request tests.** WebUI / server changes must be covered with actual HTTP requests (httpx / `starlette.testclient.TestClient`), not just mocked units — past CORS bugs slipped through mock-only coverage.
4. **Don't bypass the pre-commit hooks.** If `pre-commit` fails, fix the underlying issue. `--no-verify` is not an acceptable workaround.
5. **Atomic slices.** Implement in small, self-contained slices; commit per slice; bundle into a release when a set of slices is complete.
6. **Update the spec when the surface changes.** The authoritative spec lives at [`docs/AUTO-SPLAT PIPELINE — Spec & Implementation Plan.md`](docs/AUTO-SPLAT%20PIPELINE%20%E2%80%94%20Spec%20%26%20Implementation%20Plan.md). If your PR materially changes the surface, update the spec or call out the divergence in the PR description.
7. **Conventional commits** — `feat(scope): summary`, `fix(scope): …`, `docs(scope): …`, `chore(scope): …`.
8. **AI co-author trailer** — Anthropic Claude was a heavy contributor to the codebase. Commits with substantial AI input use:
   ```
   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   ```

For deeper agent guidance see [`AGENTS.md`](AGENTS.md).

## Out of scope

- Windows / Linux support — the pipeline is intentionally Mac-Silicon-only (see spec §2.1).
- Cloud rendering / remote training — local-first by design.
- Mesh extraction from splats — future work, not currently planned.

If you want a feature beyond that, opening an issue to discuss first is much faster than a surprise PR.
