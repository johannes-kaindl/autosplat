# SPDX-License-Identifier: AGPL-3.0-or-later

"""Phase-3 quality-gate tests — thresholds, retry hints, exception payload."""

from __future__ import annotations

from pathlib import Path

import pytest

from autosplat.config import ColmapConfig, QualityGateConfig
from autosplat.quality import (
    QualityGateFailure,
    check_sfm_quality,
    evaluate_sfm,
    retry_hint_for_brush_oom,
)
from autosplat.sfm import SfmResult


def _sfm(cams: int, points: int) -> SfmResult:
    return SfmResult(
        workspace=Path("/tmp"),
        database_path=Path("/tmp/db.db"),
        sparse_dir=Path("/tmp/sparse"),
        cameras_registered=cams,
        points=points,
        duration_s=10.0,
    )


def _cfg(min_ratio: float = 0.5, min_points: int = 5000) -> QualityGateConfig:
    return QualityGateConfig(enabled=True, min_camera_ratio=min_ratio, min_points=min_points)


def _seq() -> ColmapConfig:
    return ColmapConfig(matcher="sequential", quality="medium", single_camera=True)


def _exh() -> ColmapConfig:
    return ColmapConfig(matcher="exhaustive", quality="medium", single_camera=True)


# ─── evaluate_sfm — pure helper ─────────────────────────────────────────────


def test_evaluate_passes_when_above_thresholds() -> None:
    result = evaluate_sfm(_sfm(cams=80, points=10000), frames_kept=100, cfg=_cfg())
    assert result.ok is True
    assert result.ratio == pytest.approx(0.8)
    assert result.points == 10000


def test_evaluate_fails_on_low_ratio() -> None:
    # bench_chill: 107/107 = 1.0 ✓ but ice_bird-style 4/106 = 0.038 ✗
    result = evaluate_sfm(_sfm(cams=4, points=10000), frames_kept=106, cfg=_cfg())
    assert result.ok is False
    assert "low_camera_ratio" in (result.reason or "")


def test_evaluate_fails_on_low_points() -> None:
    # High ratio but tiny sparse cloud
    result = evaluate_sfm(_sfm(cams=80, points=500), frames_kept=100, cfg=_cfg(min_points=5000))
    assert result.ok is False
    assert "low_points" in (result.reason or "")


def test_evaluate_fails_when_no_frames_kept() -> None:
    result = evaluate_sfm(_sfm(cams=0, points=0), frames_kept=0, cfg=_cfg())
    assert result.ok is False
    assert result.reason == "no_frames_kept"


# ─── check_sfm_quality — raises on fail ────────────────────────────────────


def test_check_disabled_is_noop() -> None:
    cfg = QualityGateConfig(enabled=False, min_camera_ratio=0.99, min_points=99_999_999)
    check_sfm_quality(_sfm(0, 0), frames_kept=0, cfg=cfg, colmap_cfg=_seq())  # no raise


def test_check_passes_for_good_sfm() -> None:
    check_sfm_quality(
        _sfm(cams=107, points=53_000), frames_kept=107, cfg=_cfg(), colmap_cfg=_seq()
    )  # no raise


def test_check_raises_on_low_ratio_with_exhaustive_hint_for_sequential() -> None:
    # When matcher was sequential, the retry hint should suggest exhaustive.
    with pytest.raises(QualityGateFailure) as excinfo:
        check_sfm_quality(
            _sfm(cams=4, points=10000), frames_kept=106, cfg=_cfg(), colmap_cfg=_seq()
        )
    err = excinfo.value
    assert err.stage == "sfm_validation"
    assert err.retry_hint == {"colmap": {"matcher": "exhaustive"}}
    assert err.metrics["cameras_registered"] == 4
    assert err.metrics["matcher"] == "sequential"


def test_check_raises_on_low_ratio_without_hint_when_already_exhaustive() -> None:
    # Already on exhaustive — no further matcher we can swap to.
    with pytest.raises(QualityGateFailure) as excinfo:
        check_sfm_quality(
            _sfm(cams=4, points=10000), frames_kept=106, cfg=_cfg(), colmap_cfg=_exh()
        )
    assert excinfo.value.retry_hint is None


def test_check_raises_on_low_points_without_hint() -> None:
    # No matcher swap will rescue a texture-poor scene; hint is None on purpose.
    with pytest.raises(QualityGateFailure) as excinfo:
        check_sfm_quality(
            _sfm(cams=80, points=500), frames_kept=100, cfg=_cfg(min_points=5000), colmap_cfg=_seq()
        )
    assert excinfo.value.retry_hint is None
    assert "low_points" in excinfo.value.reason


# ─── retry_hint_for_brush_oom (Phase 6 / Spec §9.2) ─────────────────────────


def test_brush_oom_retry_hint_halves_resolution() -> None:
    assert retry_hint_for_brush_oom(1600) == {"brush": {"resolution_cap": 800}}
    assert retry_hint_for_brush_oom(800) == {"brush": {"resolution_cap": 400}}


def test_brush_oom_retry_hint_clamps_to_minimum() -> None:
    # Pydantic BrushConfig has ge=256 for resolution_cap, so we clamp there.
    assert retry_hint_for_brush_oom(300) == {"brush": {"resolution_cap": 256}}
    assert retry_hint_for_brush_oom(100) == {"brush": {"resolution_cap": 256}}
