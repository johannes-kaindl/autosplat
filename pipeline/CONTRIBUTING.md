# Contributing

`auto-splat-pipeline` is a **personal tool** built for one specific Mac-Silicon-only Gaussian-Splatting workflow. It's not actively soliciting contributions — but issues and PRs are welcome if you find a sharp edge.

## Bug reports

Please include:

- macOS version + CPU (`uname -a`)
- `autosplat doctor` output
- The relevant `pipeline.log` from `<capture-dir>/pipeline.log`
- Steps to reproduce, including the source video properties (`ffprobe`)

## Pull requests

1. Run the tests: `uv run pytest -q`
2. Optional but appreciated: `uv run ruff check src/ tests/`
3. New features should land with tests. The bar for "unit-tested" is low — see `tests/` for examples.
4. The spec lives at [`docs/AUTO-SPLAT PIPELINE — Spec & Implementation Plan.md`](docs/AUTO-SPLAT%20PIPELINE%20%E2%80%94%20Spec%20%26%20Implementation%20Plan.md). If your PR materially changes the surface, update the spec or call out the divergence in the PR description.
5. Commits follow conventional-commits-ish (`feat(scope): summary`, `fix(scope): …`, `docs(scope): …`).
6. Anthropic Claude was a heavy contributor to the codebase — commits with substantial AI input use `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` in the trailer.

## Out of scope

- Windows / Linux support — the pipeline is intentionally Mac-Silicon-only (see spec §2.1).
- Cloud rendering / remote training — local-first by design.
- Mesh extraction from splats — future work, not currently planned.

If you want a feature beyond that, opening an issue to discuss first is much faster than a surprise PR.
