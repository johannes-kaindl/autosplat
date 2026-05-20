# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pipeline orchestrator — dry-run + capture-name format."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autosplat.config import load_config
from autosplat.pipeline import _make_capture_name, run_pipeline


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
            video, cfg,
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
