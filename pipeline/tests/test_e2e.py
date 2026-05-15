"""End-to-end pipeline test.

Skipped by default. Opt in with `AUTOSPLAT_E2E=1` (and have ffmpeg, colmap,
and the brush binary available). Marked `slow` so `pytest -m "not slow"`
also skips it.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from autosplat.config import load_config
from autosplat.pipeline import run_pipeline

pytestmark = pytest.mark.slow


def _e2e_enabled() -> bool:
    return os.environ.get("AUTOSPLAT_E2E", "").lower() in ("1", "true", "yes")


def _tooling_available() -> tuple[bool, str]:
    cfg = load_config(include_xdg=False)
    if shutil.which("ffmpeg") is None:
        return False, "ffmpeg not in PATH"
    if shutil.which("colmap") is None:
        return False, "colmap not in PATH"
    if not cfg.paths.brush_binary.exists():
        return False, f"brush binary missing at {cfg.paths.brush_binary}"
    return True, ""


@pytest.mark.skipif(not _e2e_enabled(), reason="set AUTOSPLAT_E2E=1 to run")
@pytest.mark.needs_ffmpeg
@pytest.mark.needs_colmap
@pytest.mark.needs_brush
def test_pipeline_end_to_end(tmp_path: Path, repo_root: Path) -> None:
    """Full pipeline on tests/fixtures/tiny_video.mp4 → scene.ply."""
    fixture = repo_root / "tests" / "fixtures" / "tiny_video.mp4"
    assert fixture.exists(), f"Fixture missing: {fixture}"

    ok, why = _tooling_available()
    if not ok:
        pytest.skip(why)

    cfg = load_config(include_xdg=False)

    # Override training budget hard so the test completes in minutes, not hours.
    cfg.brush.max_steps = 500
    cfg.brush.densify_until_iter = 250
    cfg.viewer.auto_open = False  # no browser pops during tests
    cfg.export.copy_to_outputs = False  # keep everything in tmp_path

    result = run_pipeline(fixture, cfg, output_dir_override=tmp_path / "captures")

    assert result.output_ply.exists(), "Pipeline did not produce a PLY"
    assert result.output_ply.stat().st_size > 100 * 1024, "PLY suspiciously small"
    assert result.metadata_path.exists()
