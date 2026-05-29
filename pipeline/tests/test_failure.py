# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for failure classification + log-derived reason (v1.8.0)."""

from __future__ import annotations

from pathlib import Path

from autosplat.failure import classify_failure, failure_reason_from_log


def test_classify_blur_rejection() -> None:
    info = classify_failure(
        "All 250 extracted frames were rejected as blurry "
        "(Laplacian variance below blur_threshold=100.0).",
        stage="preprocess",
    )
    assert info.category == "blur"
    assert "blurry" in info.headline.lower()
    assert "blur_threshold" in info.hint


def test_classify_sfm_no_matches() -> None:
    info = classify_failure(
        "Command '['colmap', 'mapper', ...]' returned non-zero exit status 1.",
        stage="sfm",
    )
    assert info.category == "sfm"
    assert "rescue" in info.hint.lower()


def test_classify_sfm_no_images_phrase() -> None:
    info = classify_failure("No images with matches", stage="sfm")
    assert info.category == "sfm"


def test_classify_oom() -> None:
    info = classify_failure("Brush hit OOM at resolution_cap=1600", stage="train")
    assert info.category == "oom"
    assert "resolution_cap" in info.hint


def test_classify_no_video() -> None:
    info = classify_failure("No source video found in /x/y", stage=None)
    assert info.category == "no_video"


def test_classify_interrupted() -> None:
    info = classify_failure("interrupted — the run ended without producing a result")
    assert info.category == "interrupted"
    assert "resume" in info.hint.lower()


def test_classify_unknown_fallback() -> None:
    info = classify_failure("some totally novel explosion", stage="train")
    assert info.category == "unknown"
    assert info.headline
    assert info.hint  # never empty — always actionable


def test_classify_none_reason_is_fallback() -> None:
    info = classify_failure(None, stage=None)
    assert info.category == "unknown"
    assert info.hint


def test_failure_reason_from_log_extracts_last_error_event(tmp_path: Path) -> None:
    log = tmp_path / "pipeline.log"
    log.write_text(
        '{"event": "sfm.mapper.start", "level": "info", "ts": "t1"}\n'
        '{"error": "Failed to create any sparse model", '
        '"event": "sfm.subprocess_failed", "level": "error", "ts": "t2"}\n'
    )
    reason = failure_reason_from_log(tmp_path)
    assert reason is not None
    assert "sparse model" in reason


def test_failure_reason_from_log_none_when_no_log(tmp_path: Path) -> None:
    assert failure_reason_from_log(tmp_path) is None


def test_failure_reason_from_log_none_when_no_error_lines(tmp_path: Path) -> None:
    log = tmp_path / "pipeline.log"
    log.write_text('{"event": "preprocess.done", "level": "info", "ts": "t"}\n')
    # No error event → return the last line so the panel still shows something.
    reason = failure_reason_from_log(tmp_path)
    assert reason is None or "preprocess.done" in reason
