# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from autosplat.cli import app
from autosplat.lifecycle import review_marker_path, review_status

runner = CliRunner()


def _capture(tmp_path: Path) -> Path:
    capture = tmp_path / "2026-07-19_lgs"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 100)
    return capture


def test_confirm_unchanged_marks_the_capture_reviewed(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    result = runner.invoke(app, ["review", str(capture), "--confirm-unchanged"])
    assert result.exit_code == 0, result.output
    assert review_status(capture) == "reviewed"
    data = json.loads(review_marker_path(capture).read_text())
    assert data["source_ply_mtime"] == (capture / "output" / "scene.ply").stat().st_mtime


def test_upload_stores_the_cleaned_ply(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    cleaned = tmp_path / "cleaned.ply"
    cleaned.write_bytes(b"ply\n" + b"y" * 50)
    result = runner.invoke(app, ["review", str(capture), "--upload", str(cleaned)])
    assert result.exit_code == 0, result.output
    assert (capture / "output" / "scene_reviewed.ply").read_bytes() == cleaned.read_bytes()
    assert review_status(capture) == "reviewed"


def test_confirm_unchanged_removes_a_stale_reviewed_ply(tmp_path: Path) -> None:
    """Same trap the WebUI route documents: a leftover scene_reviewed.ply
    would keep being published after a rebuild."""
    capture = _capture(tmp_path)
    (capture / "output" / "scene_reviewed.ply").write_bytes(b"ply\nstale")
    runner.invoke(app, ["review", str(capture), "--confirm-unchanged"])
    assert not (capture / "output" / "scene_reviewed.ply").exists()


def test_both_flags_is_an_error(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    cleaned = tmp_path / "c.ply"
    cleaned.write_bytes(b"ply\n")
    result = runner.invoke(
        app, ["review", str(capture), "--confirm-unchanged", "--upload", str(cleaned)]
    )
    assert result.exit_code != 0


def test_neither_flag_is_an_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["review", str(_capture(tmp_path))])
    assert result.exit_code != 0


def test_non_ply_upload_is_rejected(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    bad = tmp_path / "notaply.ply"
    bad.write_bytes(b"this is not a ply")
    result = runner.invoke(app, ["review", str(capture), "--upload", str(bad)])
    assert result.exit_code != 0
    assert review_status(capture) == "unreviewed"


def test_review_refuses_a_capture_with_no_scene_ply(tmp_path: Path) -> None:
    """review's own no-PLY guard (cli.py:944-947) — the sibling of `share`'s,
    which test_cli_share.py already covers. `capture_dir` only requires the
    directory itself to exist (`exists=True, file_okay=False` on the typer
    argument); output/scene.ply is checked separately, after that."""
    capture = tmp_path / "2026-07-19_no_ply"
    capture.mkdir()
    result = runner.invoke(app, ["review", str(capture), "--confirm-unchanged"])
    assert result.exit_code != 0
    assert "No output/scene.ply" in result.output
    assert review_status(capture) == "unreviewed"
