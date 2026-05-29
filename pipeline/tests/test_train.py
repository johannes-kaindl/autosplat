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
    cfg_5k = BrushConfig(max_steps=5000, resolution_cap=1600, sh_degree=3, densify_until_iter=2500)
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
    cfg = BrushConfig(max_steps=5000, resolution_cap=1600, sh_degree=3, densify_until_iter=2500)
    est = estimate_wall_time_s(cfg)
    # Real was 282 s; heuristic produces 5000 * 80 ms = 400 s. Within 2×.
    assert 140 < est < 600


def test_estimate_wall_time_scales_with_resolution() -> None:
    """Higher resolution → longer wall-time. Heuristic floors at 0.3× so
    very-low-resolution doesn't go to zero, hence the wide tolerance."""
    cfg_low = BrushConfig(max_steps=10000, resolution_cap=800, sh_degree=3, densify_until_iter=5000)
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


# ─── v1.5.0: compute_eval_psnr ──────────────────────────────────────────────


def _write_png(path: Path, fill: int, shape: tuple[int, int] = (64, 64)) -> None:
    import cv2
    import numpy as np

    img = np.full((*shape, 3), fill, dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)


def _write_jpg(path: Path, fill: int, shape: tuple[int, int] = (64, 64)) -> None:
    import cv2
    import numpy as np

    img = np.full((*shape, 3), fill, dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])


def test_compute_eval_psnr_identical_returns_high(tmp_path: Path) -> None:
    """Two identical solid-colour images → very high PSNR (≥ 40 dB typical
    threshold; identical-uint8 hits the sentinel cap)."""
    from autosplat.train import compute_eval_psnr

    eval_dir = tmp_path / "eval_1000"
    frames_dir = tmp_path / "frames"

    _write_png(eval_dir / "frame_00010.png", fill=128)
    _write_jpg(frames_dir / "frame_00010.jpg", fill=128)

    psnr = compute_eval_psnr(eval_dir, frames_dir)
    assert psnr is not None
    # JPG re-encode introduces minimal noise; should still be ≥ 35 dB
    assert psnr >= 35.0


def test_compute_eval_psnr_differs_returns_finite(tmp_path: Path) -> None:
    """Render at fill=100, original at fill=200 — large MSE, low PSNR."""
    from autosplat.train import compute_eval_psnr

    eval_dir = tmp_path / "eval_1000"
    frames_dir = tmp_path / "frames"

    _write_png(eval_dir / "frame_00010.png", fill=100)
    _write_jpg(frames_dir / "frame_00010.jpg", fill=200)

    psnr = compute_eval_psnr(eval_dir, frames_dir)
    assert psnr is not None
    # Solid 100 vs 200 → MSE ≈ 10000 → PSNR ≈ 8 dB
    assert 5.0 < psnr < 15.0


def test_compute_eval_psnr_downscales_original_to_render(tmp_path: Path) -> None:
    """Render at 32×32, original at 128×128 — original gets downscaled to
    match before MSE. Both fill=200 → very high PSNR."""
    from autosplat.train import compute_eval_psnr

    eval_dir = tmp_path / "eval_1000"
    frames_dir = tmp_path / "frames"

    _write_png(eval_dir / "frame_00010.png", fill=200, shape=(32, 32))
    _write_jpg(frames_dir / "frame_00010.jpg", fill=200, shape=(128, 128))

    psnr = compute_eval_psnr(eval_dir, frames_dir)
    assert psnr is not None
    assert psnr >= 35.0


def test_compute_eval_psnr_no_eval_dir_returns_none(tmp_path: Path) -> None:
    from autosplat.train import compute_eval_psnr

    assert compute_eval_psnr(tmp_path / "missing", tmp_path / "frames") is None


def test_compute_eval_psnr_no_matching_originals_returns_none(tmp_path: Path) -> None:
    from autosplat.train import compute_eval_psnr

    eval_dir = tmp_path / "eval_1000"
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()

    _write_png(eval_dir / "rogue.png", fill=128)
    # frames_dir is empty → no matching original
    assert compute_eval_psnr(eval_dir, frames_dir) is None


def test_compute_eval_psnr_averages_multiple_pairs(tmp_path: Path) -> None:
    """Three pairs with different PSNR contributions → mean is averaged."""
    from autosplat.train import compute_eval_psnr

    eval_dir = tmp_path / "eval_1000"
    frames_dir = tmp_path / "frames"

    # Three identical pairs → all near-sentinel-high PSNR; mean stays high
    for i in (10, 20, 30):
        _write_png(eval_dir / f"frame_{i:05d}.png", fill=128)
        _write_jpg(frames_dir / f"frame_{i:05d}.jpg", fill=128)

    psnr = compute_eval_psnr(eval_dir, frames_dir)
    assert psnr is not None
    assert psnr >= 35.0


# ─── v1.5.0: PlateauMonitor ────────────────────────────────────────────────


def _scripted_psnr(by_step: dict[int, float]):
    """Returns a psnr_fn that maps a step number (parsed from eval_dir name)
    to a fixed PSNR. Steps not in the dict get None ('eval incomplete')."""

    def _fn(eval_dir, frames_dir):
        from autosplat.train import _parse_eval_step

        step = _parse_eval_step(eval_dir)
        return by_step.get(step) if step is not None else None

    return _fn


def _make_eval_dirs(output_dir: Path, steps: list[int]) -> None:
    """Create empty eval_<step>/ dirs with a fake PNG so glob('*.png') works."""
    for step in steps:
        d = output_dir / f"eval_{step}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "any.png").write_bytes(b"\x00")


def test_plateau_monitor_no_stop_below_min_steps(tmp_path: Path) -> None:
    """Flat PSNR but last step still below min_steps → no stop."""
    from autosplat.train import PlateauMonitor

    out = tmp_path / "training"
    _make_eval_dirs(out, [1000, 2000, 3000, 4000])
    psnrs = {1000: 30.0, 2000: 30.01, 3000: 30.02, 4000: 30.03}

    m = PlateauMonitor(
        output_dir=out,
        frames_dir=tmp_path / "frames",
        min_steps=5000,  # 4000 < 5000
        patience=3,
        min_delta_psnr=0.05,
        psnr_fn=_scripted_psnr(psnrs),
    )
    m.poll_once()
    assert m.should_stop is False
    assert len(m.history) == 4


def test_plateau_monitor_no_stop_with_improving_psnr(tmp_path: Path) -> None:
    """Steady > epsilon improvement → no stop ever."""
    from autosplat.train import PlateauMonitor

    out = tmp_path / "training"
    steps = [1000, 2000, 3000, 4000, 5000, 6000]
    _make_eval_dirs(out, steps)
    # Each step gains 1.0 dB — far above min_delta 0.05
    psnrs = {s: 20.0 + (i * 1.0) for i, s in enumerate(steps)}

    m = PlateauMonitor(
        output_dir=out,
        frames_dir=tmp_path / "frames",
        min_steps=1000,
        patience=3,
        min_delta_psnr=0.05,
        psnr_fn=_scripted_psnr(psnrs),
    )
    m.poll_once()
    assert m.should_stop is False


def test_plateau_monitor_stops_on_flat_history(tmp_path: Path) -> None:
    """Three consecutive Δ < 0.05 dB past min_steps → stop."""
    from autosplat.train import PlateauMonitor

    out = tmp_path / "training"
    steps = [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000]
    _make_eval_dirs(out, steps)
    # Steps 1000-4000 climb fast; then flat from 5000 on.
    psnrs = {
        1000: 20.0,
        2000: 23.0,
        3000: 25.0,
        4000: 26.5,
        5000: 27.0,
        6000: 27.02,  # Δ = 0.02
        7000: 27.04,  # Δ = 0.02
        8000: 27.05,  # Δ = 0.01
    }

    m = PlateauMonitor(
        output_dir=out,
        frames_dir=tmp_path / "frames",
        min_steps=5000,
        patience=3,
        min_delta_psnr=0.05,
        psnr_fn=_scripted_psnr(psnrs),
    )
    m.poll_once()
    assert m.should_stop is True
    # All 8 steps were recorded
    assert len(m.history) == 8


def test_plateau_monitor_poll_once_handles_missing_dir(tmp_path: Path) -> None:
    """output_dir doesn't exist yet (Brush still starting) → no-op, no exception."""
    from autosplat.train import PlateauMonitor

    m = PlateauMonitor(
        output_dir=tmp_path / "not_here",
        frames_dir=tmp_path / "frames",
        min_steps=1000,
        patience=3,
        min_delta_psnr=0.05,
        psnr_fn=_scripted_psnr({}),
    )
    m.poll_once()  # should not raise
    assert m.history == []
    assert m.should_stop is False


def test_plateau_monitor_idempotent_polls(tmp_path: Path) -> None:
    """Polling twice on the same eval_dirs records each step exactly once."""
    from autosplat.train import PlateauMonitor

    out = tmp_path / "training"
    _make_eval_dirs(out, [1000, 2000])
    m = PlateauMonitor(
        output_dir=out,
        frames_dir=tmp_path / "frames",
        min_steps=100,
        patience=1,
        min_delta_psnr=10.0,  # absurdly high — won't trigger
        psnr_fn=_scripted_psnr({1000: 25.0, 2000: 26.0}),
    )
    m.poll_once()
    m.poll_once()
    assert len(m.history) == 2


# ─── v1.6.0: eval-history drain → progress callback ────────────────────────


def test_drain_eval_history_emits_only_new_entries(tmp_path: Path) -> None:
    """_drain_eval_history calls the eval_callback once per new (step, psnr)
    and returns the new cursor, so repeat drains don't re-emit old metrics."""
    from autosplat.train import PlateauMonitor, _drain_eval_history

    out = tmp_path / "training"
    _make_eval_dirs(out, [1000, 2000])
    m = PlateauMonitor(
        output_dir=out,
        frames_dir=tmp_path / "frames",
        min_steps=100,
        patience=1,
        min_delta_psnr=10.0,
        psnr_fn=_scripted_psnr({1000: 25.0, 2000: 26.0}),
    )
    m.poll_once()

    seen: list[tuple[int, float]] = []
    cursor = _drain_eval_history(m, 0, lambda step, psnr: seen.append((step, psnr)))
    assert seen == [(1000, 25.0), (2000, 26.0)]
    assert cursor == 2

    # A second drain with the returned cursor emits nothing new.
    cursor = _drain_eval_history(m, cursor, lambda step, psnr: seen.append((step, psnr)))
    assert seen == [(1000, 25.0), (2000, 26.0)]
    assert cursor == 2

    # New eval appears → only it is emitted.
    _make_eval_dirs(out, [3000])
    m.psnr_fn = _scripted_psnr({1000: 25.0, 2000: 26.0, 3000: 27.0})
    m.poll_once()
    cursor = _drain_eval_history(m, cursor, lambda step, psnr: seen.append((step, psnr)))
    assert seen[-1] == (3000, 27.0)
    assert cursor == 3


# ─── v1.5.0: build_brush_command plateau-flags integration ─────────────────


def test_build_brush_command_no_eval_flags_when_disabled(tmp_path: Path) -> None:
    """plateau_enabled=false (default) → no --eval-* flags."""
    from autosplat.train import build_brush_command

    cfg = BrushConfig(
        max_steps=30000,
        resolution_cap=1600,
        sh_degree=3,
        densify_until_iter=15000,
    )
    cmd = build_brush_command(tmp_path / "brush", tmp_path / "ds", tmp_path / "out", cfg)
    assert "--eval-split-every" not in cmd
    assert "--eval-every" not in cmd
    assert "--eval-save-to-disk" not in cmd
    # export-every is the legacy "only at the end" value
    assert cmd[cmd.index("--export-every") + 1] == str(cfg.max_steps)


def test_build_brush_command_emits_eval_flags_when_enabled(tmp_path: Path) -> None:
    """plateau_enabled=true → --eval-* flags appended, --export-every tied to eval-every."""
    from autosplat.train import build_brush_command

    cfg = BrushConfig(
        max_steps=30000,
        resolution_cap=1600,
        sh_degree=3,
        densify_until_iter=15000,
        plateau_enabled=True,
        plateau_eval_split_every=10,
        plateau_eval_every=1000,
        plateau_min_steps=5000,
        plateau_patience=3,
        plateau_min_delta_psnr=0.05,
    )
    cmd = build_brush_command(tmp_path / "brush", tmp_path / "ds", tmp_path / "out", cfg)
    assert "--eval-split-every" in cmd
    assert cmd[cmd.index("--eval-split-every") + 1] == "10"
    assert cmd[cmd.index("--eval-every") + 1] == "1000"
    assert "--eval-save-to-disk" in cmd
    # export-every == eval-every so every eval checkpoint is also a fresh PLY
    assert cmd[cmd.index("--export-every") + 1] == "1000"


def test_plateau_monitor_incomplete_step_retried_later(tmp_path: Path) -> None:
    """If psnr_fn returns None (step incomplete), it gets a second chance
    on the next poll once the data is ready."""
    from autosplat.train import PlateauMonitor

    out = tmp_path / "training"
    _make_eval_dirs(out, [1000])

    # First poll: psnr_fn returns None (e.g. eval dir still being written)
    psnrs: dict[int, float] = {}

    m = PlateauMonitor(
        output_dir=out,
        frames_dir=tmp_path / "frames",
        min_steps=100,
        patience=1,
        min_delta_psnr=10.0,
        psnr_fn=_scripted_psnr(psnrs),
    )
    m.poll_once()
    assert m.history == []

    # Now the data becomes available; next poll picks it up.
    psnrs[1000] = 30.0
    m.poll_once()
    assert len(m.history) == 1
    assert m.history[0] == (1000, 30.0)
