# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from autosplat.cli import app

runner = CliRunner()


def _capture(tmp_path: Path) -> Path:
    capture = tmp_path / "2026-07-19_lgs"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 100)
    return capture


def test_share_refuses_an_unreviewed_capture(tmp_path: Path) -> None:
    """The gate is the point. Today it lives in the route, so a CLI command
    calling the runner directly would have walked straight past it."""
    result = runner.invoke(app, ["share", str(_capture(tmp_path))])
    assert result.exit_code != 0
    assert "review" in result.output.lower()


def test_build_share_bundle_raises_on_an_unreviewed_capture(tmp_path: Path) -> None:
    from autosplat.config import load_config
    from autosplat.webui.share_runner import UnreviewedCapture, build_share_bundle

    capture = _capture(tmp_path)
    cfg = load_config(include_xdg=False)
    with pytest.raises(UnreviewedCapture):
        build_share_bundle(cfg, capture, capture.name)


def test_share_reports_missing_ply_once_reviewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins `share`'s handling of build_share_bundle's "No output/scene.ply"
    FileNotFoundError (share_runner.py) — the guard the WebUI equivalent
    covers in test_review_routes.py. A reviewer noted this is unreachable
    through the normal CLI flow: review_status() can only be "reviewed" while
    output/scene.ply exists with a matching mtime, and resolve_publish_ply()
    always finds that same file — so the unreviewed-capture gate refuses
    first, long before this guard could ever fire. The only way in is the PLY
    vanishing between the two checks, so the test forces that directly by
    patching resolve_publish_ply to report "gone" for an otherwise reviewed
    capture, exercising the real FileNotFoundError raise and the CLI's
    "Share failed" handling around it.
    """
    from autosplat.lifecycle import write_review_marker

    capture = _capture(tmp_path)
    write_review_marker(capture)

    monkeypatch.setattr(
        "autosplat.webui.share_runner.resolve_publish_ply", lambda *_a, **_k: None
    )

    result = runner.invoke(app, ["share", str(capture)])

    assert result.exit_code != 0
    assert "No output/scene.ply" in result.output
