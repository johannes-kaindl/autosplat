# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the Brush command builder and dataset staging.

Brush v0.3.x flag surface: source is positional, training params are flags
(`--total-steps`, `--max-resolution`, `--sh-degree`, `--growth-stop-iter`,
`--export-path`, `--export-name`, `--export-every`).
"""

from __future__ import annotations

from pathlib import Path

from autosplat.config import BrushConfig
from autosplat.train import (
    BrushOOMError,
    _looks_like_oom,
    build_brush_command,
    estimate_wall_time_s,
    stage_dataset,
)


def test_brush_command_positional_source_first(tmp_path: Path) -> None:
    cfg = BrushConfig(
        max_steps=10000,
        resolution_cap=1600,
        sh_degree=3,
        densify_until_iter=5000,
        extra_args=[],
    )
    cmd = build_brush_command(
        brush_binary=tmp_path / "brush",
        dataset_root=tmp_path / "dataset",
        output_dir=tmp_path / "out",
        cfg=cfg,
    )
    assert cmd[0] == str(tmp_path / "brush")
    assert cmd[1] == str(tmp_path / "dataset"), "Source must be positional, right after the binary"


def test_brush_command_total_steps_flag(tmp_path: Path) -> None:
    cfg = BrushConfig(
        max_steps=12345,
        resolution_cap=1600,
        sh_degree=3,
        densify_until_iter=5000,
        extra_args=[],
    )
    cmd = build_brush_command(
        brush_binary=tmp_path / "brush",
        dataset_root=tmp_path / "ds",
        output_dir=tmp_path / "out",
        cfg=cfg,
    )
    idx = cmd.index("--total-steps")
    assert cmd[idx + 1] == "12345"


def test_brush_command_max_resolution_flag(tmp_path: Path) -> None:
    cfg = BrushConfig(
        max_steps=1000,
        resolution_cap=800,
        sh_degree=2,
        densify_until_iter=500,
        extra_args=[],
    )
    cmd = build_brush_command(
        brush_binary=tmp_path / "brush",
        dataset_root=tmp_path / "ds",
        output_dir=tmp_path / "out",
        cfg=cfg,
    )
    idx = cmd.index("--max-resolution")
    assert cmd[idx + 1] == "800"


def test_brush_command_growth_stop_iter_flag(tmp_path: Path) -> None:
    cfg = BrushConfig(
        max_steps=10000,
        resolution_cap=1600,
        sh_degree=3,
        densify_until_iter=4321,
        extra_args=[],
    )
    cmd = build_brush_command(
        brush_binary=tmp_path / "brush",
        dataset_root=tmp_path / "ds",
        output_dir=tmp_path / "out",
        cfg=cfg,
    )
    idx = cmd.index("--growth-stop-iter")
    assert cmd[idx + 1] == "4321"


def test_brush_command_export_path_and_name(tmp_path: Path) -> None:
    cfg = BrushConfig(
        max_steps=1000,
        resolution_cap=1600,
        sh_degree=3,
        densify_until_iter=500,
        extra_args=[],
    )
    cmd = build_brush_command(
        brush_binary=tmp_path / "brush",
        dataset_root=tmp_path / "ds",
        output_dir=tmp_path / "out",
        cfg=cfg,
        export_name="custom.ply",
    )
    idx_path = cmd.index("--export-path")
    assert cmd[idx_path + 1] == str(tmp_path / "out")
    idx_name = cmd.index("--export-name")
    assert cmd[idx_name + 1] == "custom.ply"


def test_brush_extra_args_appended(tmp_path: Path) -> None:
    cfg = BrushConfig(
        max_steps=1000,
        resolution_cap=1600,
        sh_degree=2,
        densify_until_iter=500,
        extra_args=["--seed", "42"],
    )
    cmd = build_brush_command(
        brush_binary=tmp_path / "brush",
        dataset_root=tmp_path / "ds",
        output_dir=tmp_path / "out",
        cfg=cfg,
    )
    assert cmd[-2:] == ["--seed", "42"]


def test_stage_dataset_creates_symlinks(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    sparse = tmp_path / "sparse"
    frames.mkdir()
    sparse.mkdir()
    (frames / "frame_00001.jpg").touch()

    staging = tmp_path / "staging"
    result = stage_dataset(frames, sparse, staging)

    assert result == staging
    assert (staging / "images").is_symlink()
    assert (staging / "sparse").is_symlink()
    assert (staging / "images" / "frame_00001.jpg").exists()


def test_looks_like_oom_detects_canonical_oom() -> None:
    assert _looks_like_oom("Error: out of memory")
    assert _looks_like_oom("WGPU memory exhausted")
    assert _looks_like_oom("Device lost: alloc failed")


def test_looks_like_oom_false_on_unrelated_error() -> None:
    assert not _looks_like_oom("Error: COLMAP sparse model missing")
    assert not _looks_like_oom("Training step 1000 — loss 0.05")


def test_brush_oom_error_carries_resolution_cap(tmp_path: Path) -> None:
    err = BrushOOMError(resolution_cap_attempted=1600, tail="out of memory")
    assert err.resolution_cap_attempted == 1600
    assert "1600" in str(err)


def test_estimate_wall_time_scales_with_steps() -> None:
    cfg_5k = BrushConfig(
        max_steps=5000, resolution_cap=1600, sh_degree=3, densify_until_iter=2500
    )
    cfg_30k = BrushConfig(
        max_steps=30000, resolution_cap=1600, sh_degree=3, densify_until_iter=15000
    )
    assert estimate_wall_time_s(cfg_30k) > estimate_wall_time_s(cfg_5k)
    # Ratio approximately 6×
    assert 5 < estimate_wall_time_s(cfg_30k) / estimate_wall_time_s(cfg_5k) < 7


def test_estimate_wall_time_calibrated_against_bench_chill() -> None:
    """bench_chill ran 5000 steps at resolution_cap=1600 in 282 s real.
    Heuristic should land within 2× of that — under-estimating is OK,
    massively over-estimating is not."""
    cfg = BrushConfig(
        max_steps=5000, resolution_cap=1600, sh_degree=3, densify_until_iter=2500
    )
    est = estimate_wall_time_s(cfg)
    # Real was 282 s; heuristic produces 5000 * 80 ms = 400 s. Within 2×.
    assert 140 < est < 600


def test_estimate_wall_time_scales_with_resolution() -> None:
    """Higher resolution → longer wall-time. Heuristic floors at 0.3× so
    very-low-resolution doesn't go to zero, hence the wide tolerance."""
    cfg_low = BrushConfig(
        max_steps=10000, resolution_cap=800, sh_degree=3, densify_until_iter=5000
    )
    cfg_high = BrushConfig(
        max_steps=10000, resolution_cap=1600, sh_degree=3, densify_until_iter=5000
    )
    assert estimate_wall_time_s(cfg_high) > estimate_wall_time_s(cfg_low)


def test_stage_dataset_replaces_existing(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    sparse = tmp_path / "sparse"
    frames.mkdir()
    sparse.mkdir()

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "images").mkdir()  # stale, non-symlink
    (staging / "images" / "stale.jpg").touch()

    stage_dataset(frames, sparse, staging)

    assert (staging / "images").is_symlink()
    assert not (staging / "images" / "stale.jpg").exists()
