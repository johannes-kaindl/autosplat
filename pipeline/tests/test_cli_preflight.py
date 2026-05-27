# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI pre-flight viewer-config check — v1.4.6 fail-loud-at-start helper."""

from __future__ import annotations

from pathlib import Path

from autosplat.cli import _warn_if_viewer_misconfigured
from autosplat.config import apply_override, load_config


def test_no_warning_when_auto_open_disabled(capsys, tmp_path: Path) -> None:
    cfg = apply_override(
        load_config(include_xdg=False),
        {"viewer": {"auto_open": False, "target": "supersplat-local"}},
    )
    _warn_if_viewer_misconfigured(cfg)
    assert capsys.readouterr().err == ""


def test_no_warning_when_target_is_remote(capsys, tmp_path: Path) -> None:
    """Remote target has its own deprecation warning in viewer.py — the
    pre-flight helper only fires for local-target + missing-dist."""
    cfg = apply_override(
        load_config(include_xdg=False),
        {"viewer": {"target": "supersplat"}},
    )
    _warn_if_viewer_misconfigured(cfg)
    assert capsys.readouterr().err == ""


def test_no_warning_when_dist_present(capsys, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("ok", encoding="utf-8")
    cfg = apply_override(
        load_config(include_xdg=False),
        {"viewer": {"target": "supersplat-local", "supersplat_dist_path": str(dist)}},
    )
    _warn_if_viewer_misconfigured(cfg)
    assert capsys.readouterr().err == ""


def test_warning_when_dist_missing(capsys, tmp_path: Path) -> None:
    """The canonical case the pre-flight helper exists for: user starts a
    5h run that will auto-open at the end, but the dist isn't built."""
    cfg = apply_override(
        load_config(include_xdg=False),
        {
            "viewer": {
                "target": "supersplat-local",
                "supersplat_dist_path": str(tmp_path / "missing_dist"),
            }
        },
    )
    _warn_if_viewer_misconfigured(cfg)
    err = capsys.readouterr().err
    assert "supersplat-local" in err
    assert "setup_supersplat.sh" in err
