# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pipeline orchestrator — dry-run + capture-name format."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autosplat.config import load_config
from autosplat.pipeline import (
    _make_capture_name,
    detect_completed_stages,
    read_source_video_from_log,
    resume_capture,
    run_pipeline,
    run_pipeline_with_adaptive_retry,
)
from autosplat.quality import QualityGateFailure


def test_capture_name_format(tmp_path: Path) -> None:
    video = tmp_path / "neo2_garden.mp4"
    video.touch()
    name = _make_capture_name(video)
    today = date.today().isoformat()
    assert name == f"{today}_neo2_garden"


def test_dry_run_creates_capture_dir(tmp_path: Path) -> None:
    video = tmp_path / "input.mp4"
    video.write_bytes(b"\0")
    cfg = load_config(include_xdg=False)

    result = run_pipeline(
        video,
        cfg,
        output_dir_override=tmp_path / "captures",
        dry_run=True,
    )
    assert result.capture_dir.exists()
    assert (result.capture_dir / "source").exists()


def test_unknown_skip_stage_raises(tmp_path: Path) -> None:
    video = tmp_path / "input.mp4"
    video.write_bytes(b"\0")
    cfg = load_config(include_xdg=False)
    with pytest.raises(ValueError, match="Unknown stages"):
        run_pipeline(video, cfg, output_dir_override=tmp_path, skip_stages={"bogus"})


def test_capture_dir_override_targets_existing_dir(tmp_path: Path) -> None:
    """capture_dir_override adopts an existing capture dir (e.g. yesterday's
    failed run) instead of computing a fresh `<today>_<stem>` path."""
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    cfg = load_config(include_xdg=False)
    legacy_dir = tmp_path / "captures" / "2024-01-15_legacy_capture"
    legacy_dir.mkdir(parents=True)

    result = run_pipeline(video, cfg, capture_dir_override=legacy_dir, dry_run=True)

    assert result.capture_dir == legacy_dir
    assert result.capture_name == "2024-01-15_legacy_capture"


# ─── detect_completed_stages — resume-stage discovery ──────────────────────


def test_detect_completed_stages_empty_dir(tmp_path: Path) -> None:
    """No artifacts at all → no stages completed."""
    capture_dir = tmp_path / "fresh"
    capture_dir.mkdir()
    assert detect_completed_stages(capture_dir) == set()


def test_detect_completed_stages_preprocess_done(tmp_path: Path) -> None:
    """At least one extracted frame → preprocess is done."""
    capture_dir = tmp_path / "cap"
    frames = capture_dir / "frames"
    frames.mkdir(parents=True)
    (frames / "frame_00001.jpg").write_bytes(b"\xff\xd8\xff")
    assert detect_completed_stages(capture_dir) == {"preprocess"}


def test_detect_completed_stages_through_sfm(tmp_path: Path) -> None:
    """colmap/sparse/0/images.bin present → sfm done (frames implied)."""
    capture_dir = tmp_path / "cap"
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "frames" / "frame_00001.jpg").write_bytes(b"\xff\xd8")
    sparse = capture_dir / "colmap" / "sparse" / "0"
    sparse.mkdir(parents=True)
    (sparse / "images.bin").write_bytes(b"\0" * 16)
    assert detect_completed_stages(capture_dir) == {"preprocess", "sfm"}


def test_detect_completed_stages_through_export(tmp_path: Path) -> None:
    """A scene.ply in output/ → preprocess + sfm + train + export all done."""
    capture_dir = tmp_path / "cap"
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "frames" / "frame_00001.jpg").write_bytes(b"\xff\xd8")
    sparse = capture_dir / "colmap" / "sparse" / "0"
    sparse.mkdir(parents=True)
    (sparse / "images.bin").write_bytes(b"\0" * 16)
    training = capture_dir / "training"
    training.mkdir()
    (training / "splat.ply").write_bytes(b"ply\n")
    output = capture_dir / "output"
    output.mkdir()
    (output / "scene.ply").write_bytes(b"ply\n")
    assert detect_completed_stages(capture_dir) == {
        "preprocess",
        "sfm",
        "train",
        "export",
    }


# ─── read_source_video_from_log — resume source recovery ───────────────────


def test_read_source_video_from_log_returns_video_path(tmp_path: Path) -> None:
    """The first pipeline.start event in pipeline.log carries the source video."""
    capture_dir = tmp_path / "cap"
    capture_dir.mkdir()
    video = tmp_path / "input.mp4"
    video.write_bytes(b"\0")
    log = capture_dir / "pipeline.log"
    log.write_text(
        '{"event": "pipeline.start", "capture_name": "cap", "video": "'
        + str(video)
        + '", "level": "info", "ts": "2026-05-22T18:15:18Z"}\n'
        '{"event": "preflight.passed", "level": "info"}\n',
        encoding="utf-8",
    )
    assert read_source_video_from_log(capture_dir) == video


def test_read_source_video_from_log_missing_log(tmp_path: Path) -> None:
    """No pipeline.log → None (caller must fall back to --video)."""
    capture_dir = tmp_path / "cap"
    capture_dir.mkdir()
    assert read_source_video_from_log(capture_dir) is None


# ─── resume_capture — orchestrator for `autosplat resume` ──────────────────


def test_resume_capture_skips_completed_stages_and_targets_dir(
    tmp_path: Path,
) -> None:
    """resume_capture picks up the source video from pipeline.log, computes
    skip_stages from on-disk artifacts, and calls the retry wrapper with the
    existing capture_dir preserved (no fresh date-stamped dir)."""
    capture_dir = tmp_path / "2024-01-15_partial"
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "frames" / "frame_00001.jpg").write_bytes(b"\xff\xd8")
    video = tmp_path / "src.mp4"
    video.write_bytes(b"\0")
    (capture_dir / "pipeline.log").write_text(
        '{"event": "pipeline.start", "video": "' + str(video) + '"}\n',
        encoding="utf-8",
    )
    cfg = load_config(include_xdg=False)
    success = MagicMock(spec=["capture_dir", "output_ply"])

    with patch(
        "autosplat.pipeline.run_pipeline_with_adaptive_retry", return_value=success
    ) as mocked:
        result = resume_capture(capture_dir, cfg)

    assert result is success
    kwargs = mocked.call_args.kwargs
    assert mocked.call_args.args[0] == video
    assert kwargs["capture_dir_override"] == capture_dir
    assert kwargs["skip_stages"] == {"preprocess"}


def test_resume_capture_video_override_wins(tmp_path: Path) -> None:
    """An explicit video override beats whatever pipeline.log recorded —
    handy when the original file has moved."""
    capture_dir = tmp_path / "2024-01-15_moved"
    capture_dir.mkdir()
    (capture_dir / "pipeline.log").write_text(
        '{"event": "pipeline.start", "video": "/gone/old.mp4"}\n', encoding="utf-8"
    )
    new_video = tmp_path / "new.mp4"
    new_video.write_bytes(b"\0")
    cfg = load_config(include_xdg=False)

    with patch(
        "autosplat.pipeline.run_pipeline_with_adaptive_retry",
        return_value=MagicMock(),
    ) as mocked:
        resume_capture(capture_dir, cfg, video_override=new_video)

    assert mocked.call_args.args[0] == new_video


def test_resume_capture_rejects_when_export_complete(tmp_path: Path) -> None:
    """A capture with output/scene.ply is already done — resume is a no-op
    and the user gets a clear refusal instead of redoing the whole pipeline."""
    capture_dir = tmp_path / "2024-01-15_done"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n")
    video = tmp_path / "src.mp4"
    video.write_bytes(b"\0")
    cfg = load_config(include_xdg=False)

    with (
        patch("autosplat.pipeline.run_pipeline_with_adaptive_retry") as mocked,
        pytest.raises(ValueError, match="already complete"),
    ):
        resume_capture(capture_dir, cfg, video_override=video)

    mocked.assert_not_called()


def test_resume_capture_errors_without_video_source(tmp_path: Path) -> None:
    """No pipeline.log AND no --video → clear error, no pipeline call."""
    capture_dir = tmp_path / "2024-01-15_bare"
    capture_dir.mkdir()
    cfg = load_config(include_xdg=False)

    with (
        patch("autosplat.pipeline.run_pipeline_with_adaptive_retry") as mocked,
        pytest.raises(ValueError, match="source video"),
    ):
        resume_capture(capture_dir, cfg)

    mocked.assert_not_called()


# ─── Helpers for embed_url tests ────────────────────────────────────────────


def _fake_ply(tmp_path: Path) -> Path:
    """Create a minimal .ply file so export_capture can stat() it."""
    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply\nend_header\n")
    return ply


def _mock_pipeline_stages(tmp_path: Path, fake_ply: Path) -> dict:
    """Return MagicMock instances keyed by short stage name for use with _run_with_mocks."""
    preprocess_result = MagicMock(extracted_count=10, kept_count=10)
    sfm_result = MagicMock(cameras_registered=10, points=5000)
    train_result = MagicMock(final_ply=fake_ply, steps_completed=1000, duration_s=5.0)
    export_result = MagicMock(
        output_ply=fake_ply,
        metadata_path=tmp_path / "metadata.json",
        size_bytes=16,
    )
    return {
        "preflight": MagicMock(),
        "preprocess": MagicMock(return_value=preprocess_result),
        "sfm": MagicMock(return_value=sfm_result),
        "quality": MagicMock(),
        "train": MagicMock(return_value=train_result),
        "export": MagicMock(return_value=export_result),
        "ply_header": MagicMock(return_value={"gaussians": 80000, "sh_degree": 3}),
    }


def _cfg_with_viewer_target(target: str, obsidian_enabled: bool, tmp_path: Path):
    """Build a Config with the given viewer.target and obsidian.enabled settings."""

    cfg = load_config(include_xdg=False)
    # Pydantic models are immutable; build replacement instances.
    cfg = cfg.model_copy(
        update={
            "viewer": cfg.viewer.model_copy(update={"target": target, "auto_open": False}),
            "obsidian": cfg.obsidian.model_copy(
                update={
                    "enabled": obsidian_enabled,
                    "vault_path": tmp_path / "vault",
                }
            ),
        }
    )
    (tmp_path / "vault").mkdir(exist_ok=True)
    (tmp_path / "vault" / "3D Memories").mkdir(parents=True, exist_ok=True)
    return cfg


# ─── embed_url tests ─────────────────────────────────────────────────────────


def _run_with_mocks(video: Path, cfg, patches: dict, tmp_path: Path, state=None):
    """Run run_pipeline with all stage functions mocked via nested patch contexts.

    Returns a tuple ``(result, mock_write)`` where *result* is the
    ``PipelineResult`` returned by ``run_pipeline`` and *mock_write* is the
    ``MagicMock`` standing in for ``obsidian_mod.write_capture_note``.

    `state`, when given, is passed through to run_pipeline for status reporting.
    """
    with (
        patch("autosplat.pipeline.preflight_mod.run_preflight", patches["preflight"]),
        patch("autosplat.pipeline.preprocess_mod.extract_frames", patches["preprocess"]),
        patch("autosplat.pipeline.sfm_mod.run_colmap", patches["sfm"]),
        patch("autosplat.pipeline.quality_mod.check_sfm_quality", patches["quality"]),
        patch("autosplat.pipeline.train_mod.run_brush", patches["train"]),
        patch("autosplat.pipeline.export_mod.export_capture", patches["export"]),
        patch("autosplat.pipeline.obsidian_mod.read_ply_header", patches["ply_header"]),
        patch("autosplat.pipeline.obsidian_mod.write_capture_note") as mock_write,
        patch("autosplat.pipeline.viewer_mod.open_in_viewer"),
    ):
        result = run_pipeline(
            video,
            cfg,
            output_dir_override=tmp_path / "captures",
            state=state,
        )
        return result, mock_write


def test_embed_url_populated_for_supersplat_local(tmp_path: Path) -> None:
    """embed_url is built when target=supersplat-local and obsidian.enabled."""
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    fake_ply = _fake_ply(tmp_path)
    cfg = _cfg_with_viewer_target("supersplat-local", obsidian_enabled=True, tmp_path=tmp_path)
    patches = _mock_pipeline_stages(tmp_path, fake_ply)

    _, mock_write = _run_with_mocks(video, cfg, patches, tmp_path)

    note_data = mock_write.call_args[0][1]
    expected = (
        f"http://localhost:{cfg.viewer.supersplat_local_port}"
        f"?load=http://127.0.0.1:{cfg.viewer.local_http_port}/{fake_ply.name}"
    )
    assert note_data.embed_url == expected


def test_embed_url_none_for_remote_supersplat_target(tmp_path: Path) -> None:
    """embed_url is None when target=supersplat (remote)."""
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    fake_ply = _fake_ply(tmp_path)
    cfg = _cfg_with_viewer_target("supersplat", obsidian_enabled=True, tmp_path=tmp_path)
    patches = _mock_pipeline_stages(tmp_path, fake_ply)

    _, mock_write = _run_with_mocks(video, cfg, patches, tmp_path)

    note_data = mock_write.call_args[0][1]
    assert note_data.embed_url is None


def test_embed_url_none_when_obsidian_disabled(tmp_path: Path) -> None:
    """Obsidian write is skipped entirely when obsidian.enabled=False.

    The local ``embed_url`` variable in pipeline.py stays ``None`` when the
    guard condition is false, but it is never exposed on any returned object
    we can inspect.  The observable proxy for "embed_url was never set *and*
    the obsidian block was never entered" is that *both* ``CaptureNoteData``
    was never instantiated *and* ``write_capture_note`` was never called.
    """
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    fake_ply = _fake_ply(tmp_path)
    cfg = _cfg_with_viewer_target("supersplat-local", obsidian_enabled=False, tmp_path=tmp_path)
    patches = _mock_pipeline_stages(tmp_path, fake_ply)

    with patch("autosplat.pipeline.obsidian_mod.CaptureNoteData") as mock_note_data:
        _, mock_write = _run_with_mocks(video, cfg, patches, tmp_path)

    # Neither CaptureNoteData nor write_capture_note should be called when
    # obsidian is disabled — this confirms the entire obsidian block is skipped,
    # which means embed_url was never built either.
    mock_note_data.assert_not_called()
    mock_write.assert_not_called()


# ─── SF-G2-9-PART-2 — run_pipeline reports WatcherState ─────────────────────


def test_run_pipeline_reports_watcher_state_on_success(tmp_path: Path) -> None:
    """run_pipeline writes capture-dir-keyed WatcherState so the WebUI can
    track the run regardless of trigger path (SF-G2-9-PART-2)."""
    from autosplat.watcher import WatcherState

    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    fake_ply = _fake_ply(tmp_path)
    cfg = _cfg_with_viewer_target("none", obsidian_enabled=False, tmp_path=tmp_path)
    patches = _mock_pipeline_stages(tmp_path, fake_ply)
    state = WatcherState(state_file=tmp_path / "state.json")
    capture_dir = tmp_path / "captures" / _make_capture_name(video)

    # Preflight runs right after begin() + update_stage — snapshot in_progress.
    seen: dict = {}

    def _record(*_a, **_k) -> None:
        ip = state.in_progress
        seen["path"] = ip.path if ip else None
        seen["stage"] = ip.stage if ip else None
        seen["source_video"] = ip.source_video if ip else None

    patches["preflight"].side_effect = _record

    _run_with_mocks(video, cfg, patches, tmp_path, state=state)

    # in_progress was set during the run, keyed by the capture directory
    assert seen["path"] == str(capture_dir)
    assert seen["stage"] == "preflight"
    assert seen["source_video"] == str(video)
    # after success: completed keyed by capture_dir, in_progress cleared
    assert state.in_progress is None
    assert len(state.completed) == 1
    assert state.completed[0].path == str(capture_dir)


def test_run_pipeline_leaves_in_progress_on_failure(tmp_path: Path) -> None:
    """A failing stage leaves in_progress set at that stage for the caller to
    resolve (retry vs. mark_failed) — SF-G2-9-PART-2."""
    from autosplat.watcher import WatcherState

    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    fake_ply = _fake_ply(tmp_path)
    cfg = _cfg_with_viewer_target("none", obsidian_enabled=False, tmp_path=tmp_path)
    patches = _mock_pipeline_stages(tmp_path, fake_ply)
    patches["sfm"].side_effect = RuntimeError("simulated SfM failure")
    state = WatcherState(state_file=tmp_path / "state.json")
    capture_dir = tmp_path / "captures" / _make_capture_name(video)

    with pytest.raises(RuntimeError, match="simulated SfM failure"):
        _run_with_mocks(video, cfg, patches, tmp_path, state=state)

    assert state.in_progress is not None
    assert state.in_progress.path == str(capture_dir)
    assert state.in_progress.stage == "sfm"
    assert state.completed == []


# ─── run_pipeline_with_adaptive_retry — in-process Phase-3 retry ────────────


def _quality_gate_failure(hint: dict | None = None) -> QualityGateFailure:
    return QualityGateFailure(
        reason="low_camera_ratio: 0.01 < 0.5",
        stage="sfm_validation",
        retry_hint=hint,
        metrics={"cameras_registered": 3, "frames_kept": 244},
    )


def test_adaptive_retry_applies_hint_and_succeeds_on_second_attempt(
    tmp_path: Path,
) -> None:
    """QualityGateFailure with a retry_hint → wrapper re-runs with the hint as
    config_override and succeeds. Two run_pipeline calls; second one carries
    the override."""
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    cfg = load_config(include_xdg=False)
    success_result = MagicMock(spec=["capture_dir", "output_ply"])

    hint = {"colmap": {"matcher": "exhaustive"}}
    call_log: list[dict | None] = []

    def fake_run(*args, **kwargs):
        call_log.append(kwargs.get("config_override"))
        if len(call_log) == 1:
            raise _quality_gate_failure(hint=hint)
        return success_result

    with patch("autosplat.pipeline.run_pipeline", side_effect=fake_run) as mocked:
        result = run_pipeline_with_adaptive_retry(
            video, cfg, output_dir_override=tmp_path / "captures"
        )

    assert result is success_result
    assert mocked.call_count == 2
    assert call_log == [None, hint]


def test_adaptive_retry_reraises_when_hint_is_none(tmp_path: Path) -> None:
    """QualityGateFailure without retry_hint → no retry; bubble up unchanged."""
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    cfg = load_config(include_xdg=False)

    with (
        patch(
            "autosplat.pipeline.run_pipeline",
            side_effect=_quality_gate_failure(hint=None),
        ) as mocked,
        pytest.raises(QualityGateFailure),
    ):
        run_pipeline_with_adaptive_retry(video, cfg, output_dir_override=tmp_path / "captures")

    assert mocked.call_count == 1


def test_adaptive_retry_disabled_via_config(tmp_path: Path) -> None:
    """cfg.retry.enabled=False → no retry even when a hint is present."""
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    cfg = load_config(include_xdg=False)
    cfg = cfg.model_copy(update={"retry": cfg.retry.model_copy(update={"enabled": False})})

    with (
        patch(
            "autosplat.pipeline.run_pipeline",
            side_effect=_quality_gate_failure(hint={"colmap": {"matcher": "exhaustive"}}),
        ) as mocked,
        pytest.raises(QualityGateFailure),
    ):
        run_pipeline_with_adaptive_retry(video, cfg, output_dir_override=tmp_path / "captures")

    assert mocked.call_count == 1


def test_adaptive_retry_wipes_colmap_and_skips_preprocess_on_retry(
    tmp_path: Path,
) -> None:
    """Between attempts the wrapper deletes <capture_dir>/colmap (stale matcher
    DB) and adds 'preprocess' to skip_stages so the kept frames are reused."""
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"\0")
    cfg = load_config(include_xdg=False)
    captures_root = tmp_path / "captures"
    capture_dir = captures_root / _make_capture_name(video)
    colmap_dir = capture_dir / "colmap"
    sentinel = colmap_dir / "database.db"

    success_result = MagicMock(spec=["capture_dir", "output_ply"])
    seen: list[tuple[bool, set[str] | None]] = []

    def fake_run(*args, **kwargs):
        seen.append((sentinel.exists(), kwargs.get("skip_stages")))
        if len(seen) == 1:
            # Simulate the first SfM attempt having populated colmap/.
            colmap_dir.mkdir(parents=True, exist_ok=True)
            sentinel.write_bytes(b"stale-sequential-db")
            raise _quality_gate_failure(hint={"colmap": {"matcher": "exhaustive"}})
        return success_result

    with patch("autosplat.pipeline.run_pipeline", side_effect=fake_run):
        run_pipeline_with_adaptive_retry(video, cfg, output_dir_override=captures_root)

    # First call: clean state, no skip_stages.
    assert seen[0] == (False, None)
    # Second call: colmap/ was wiped before the retry, preprocess is skipped.
    second_seen_db, second_skip = seen[1]
    assert second_seen_db is False
    assert second_skip is not None and "preprocess" in second_skip
