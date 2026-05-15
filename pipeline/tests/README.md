# Tests

116 unit tests + 2 opt-in E2E tests. The full suite runs in ~3 s on Mac M5; that's the contract.

## Running

```bash
# Default — fast, ~3 s, skips opt-in E2E
uv run pytest -q

# Verbose
uv run pytest -v

# Just one file
uv run pytest tests/test_compress.py

# Just one test
uv run pytest tests/test_compress.py::test_quality_profiles_all_three_levels_present
```

## Opt-in E2E tests

Two tests are gated behind environment variables because they need real tooling and take real time. They're marked `@pytest.mark.slow` so `pytest -m "not slow"` also skips them.

### `tests/test_e2e.py` — full pipeline against `tiny_video.mp4`

Runs the entire pipeline (preprocess → SfM → Brush → export) against a 5-second 720p fixture. Needs `ffmpeg`, `colmap`, and the `brush` binary. Training is hard-capped at 500 steps so it completes in a few minutes.

```bash
AUTOSPLAT_E2E=1 uv run pytest tests/test_e2e.py
```

### `tests/test_compress.py::test_real_compress_smoke` — real compress against bench_chill

Runs `splat-transform` (via npx if not globally installed) against the real bench_chill PLY at `~/AutoSplat/outputs/...`. Skipped if that PLY isn't present.

```bash
AUTOSPLAT_COMPRESS_E2E=1 uv run pytest tests/test_compress.py
```

## Test layout

| File                    | Module under test  | Notes                                                  |
| ----------------------- | ------------------ | ------------------------------------------------------ |
| `test_config.py`        | `config.py`        | TOML loading, layering, override helper, Phase-3 sections |
| `test_doctor.py`        | `doctor.py`        | Result aggregation + status emoji semantics            |
| `test_preprocess.py`    | `preprocess.py`    | ffmpeg command-builder + fps-target math               |
| `test_sfm.py`           | `sfm.py`           | COLMAP command-builders + binary `.bin` stats parser   |
| `test_quality.py`       | `quality.py`       | Quality-gate thresholds + retry-hint policy            |
| `test_train.py`         | `train.py`         | Brush command-builder + dataset staging via symlinks   |
| `test_export.py`        | `export.py`        | PLY-validation (header magic + min size)               |
| `test_pipeline.py`      | `pipeline.py`      | Dry-run + skip-stage validation                        |
| `test_watcher.py`       | `watcher.py`       | State persistence, crash-recovery, retry, pruning      |
| `test_obsidian.py`      | `obsidian.py`      | PLY header parser, frontmatter render, marker-pattern  |
| `test_compress.py`      | `compress.py`      | Quality-profile mapping, command-builder, error paths  |
| `test_e2e.py`           | full pipeline      | **Opt-in** — needs ffmpeg+colmap+brush                 |

`conftest.py` provides shared fixtures (`repo_root`, `packaged_default_config`, `tmp_capture_dir`).
`fixtures/` holds `tiny_video.mp4` (the 5 s test clip used by `test_e2e.py`).

## Adding a test

1. Most modules already have a `test_*.py` file. Add to the existing file unless your test is genuinely a new concern.
2. Real subprocess calls (`ffmpeg`, `colmap`, `brush`, `splat-transform`) should be **mocked** in unit tests. The command-builder functions exist precisely so we can assert on the argv without running anything.
3. If your test really does need real tooling, mark it `@pytest.mark.slow` and skip-unless-opt-in.
4. Tests should run in **milliseconds**. If yours doesn't, mock more aggressively or move it to an E2E variant.

## Markers

Defined in `pyproject.toml`:

- `@pytest.mark.slow` — opt-in via `pytest -m slow` or env-flag inside the test
- `@pytest.mark.needs_ffmpeg` — documents the runtime dep
- `@pytest.mark.needs_colmap`
- `@pytest.mark.needs_brush`

`--strict-markers` is on, so typos error immediately.

## Coverage

Not formally measured. The bar is "every public function has at least one happy-path test plus its main error path." For Phase-3 retry-logic and Phase-4 obsidian writer, coverage is unusually thick because those are the most behaviour-critical modules.
