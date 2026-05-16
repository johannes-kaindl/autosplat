# SPDX-License-Identifier: AGPL-3.0-or-later

"""Phase-6 pre-flight tests — ffprobe-validate + plausibility checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from autosplat.preflight import (
    MAX_DURATION_S,
    MAX_FPS,
    MIN_DURATION_S,
    MIN_FPS,
    MIN_RESOLUTION,
    PreflightFailure,
    VideoProbe,
    check_plausibility,
    run_preflight,
)


def _probe(**overrides) -> VideoProbe:
    base = {
        "duration_s": 30.0,
        "width": 3840,
        "height": 2160,
        "fps": 30.0,
        "codec": "hevc",
    }
    base.update(overrides)
    return VideoProbe(**base)


# ─── plausibility ──────────────────────────────────────────────────────────


def test_plausibility_passes_for_typical_drone_clip() -> None:
    check_plausibility(_probe())  # no raise


def test_plausibility_rejects_too_short() -> None:
    with pytest.raises(PreflightFailure) as excinfo:
        check_plausibility(_probe(duration_s=MIN_DURATION_S - 0.1))
    assert excinfo.value.reason == "implausible_duration"


def test_plausibility_rejects_too_long() -> None:
    with pytest.raises(PreflightFailure) as excinfo:
        check_plausibility(_probe(duration_s=MAX_DURATION_S + 1))
    assert excinfo.value.reason == "implausible_duration"


def test_plausibility_rejects_low_resolution() -> None:
    with pytest.raises(PreflightFailure) as excinfo:
        check_plausibility(_probe(width=1280, height=MIN_RESOLUTION - 1))
    assert excinfo.value.reason == "implausible_resolution"


def test_plausibility_rejects_too_low_fps() -> None:
    with pytest.raises(PreflightFailure) as excinfo:
        check_plausibility(_probe(fps=MIN_FPS - 1))
    assert excinfo.value.reason == "implausible_fps"


def test_plausibility_rejects_too_high_fps() -> None:
    with pytest.raises(PreflightFailure) as excinfo:
        check_plausibility(_probe(fps=MAX_FPS + 1))
    assert excinfo.value.reason == "implausible_fps"


def test_plausibility_accepts_30fps_4k() -> None:
    """Phase-0 bench_chill profile — sanity check it passes."""
    check_plausibility(_probe(duration_s=21.5, width=3840, height=2160, fps=29.97))


def test_plausibility_accepts_60fps_4k() -> None:
    """ice_bird / burgstall profile — should pass even though we know SfM fails."""
    check_plausibility(_probe(duration_s=34.2, width=3840, height=2160, fps=60.0))


# ─── run_preflight composition ─────────────────────────────────────────────


def test_run_preflight_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PreflightFailure) as excinfo:
        run_preflight(tmp_path / "nope.mp4")
    assert excinfo.value.reason == "video_missing"


def test_preflight_failure_has_reason_and_detail() -> None:
    err = PreflightFailure("test_reason", "test detail")
    assert err.reason == "test_reason"
    assert "test detail" in str(err)
