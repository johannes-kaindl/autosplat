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
