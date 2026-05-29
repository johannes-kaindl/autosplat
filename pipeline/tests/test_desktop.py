# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the desktop-app launcher logic (v1.7.0 DMG app)."""

from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import patch

from autosplat.doctor import CheckResult


def _results(**ok_by_name: bool) -> list[CheckResult]:
    """Build a doctor-style result list; unspecified tools default to OK."""
    names = {"ffmpeg": True, "colmap": True, "brush": True}
    names.update(ok_by_name)
    return [CheckResult(name=n, ok=ok, detail="", required=True) for n, ok in names.items()]


def test_missing_required_tools_lists_only_installable_gaps() -> None:
    from autosplat.desktop import missing_required_tools

    with patch("autosplat.desktop.run_doctor", return_value=_results(colmap=False, brush=False)):
        missing = missing_required_tools(config=object())  # type: ignore[arg-type]

    assert set(missing) == {"colmap", "brush"}


def test_missing_required_tools_empty_when_all_present() -> None:
    from autosplat.desktop import missing_required_tools

    with patch("autosplat.desktop.run_doctor", return_value=_results()):
        assert missing_required_tools(config=object()) == []  # type: ignore[arg-type]


def test_missing_required_tools_ignores_optional_and_non_installable() -> None:
    """A failing *optional* check (e.g. compress) or a non-installable one (e.g.
    platform) must not trigger first-run setup — we only act on ffmpeg/colmap/brush."""
    from autosplat.desktop import missing_required_tools

    results = [
        *_results(),
        CheckResult(name="compress", ok=False, detail="", required=False),
        CheckResult(name="platform", ok=False, detail="", required=True),
    ]
    with patch("autosplat.desktop.run_doctor", return_value=results):
        assert missing_required_tools(config=object()) == []  # type: ignore[arg-type]


def test_needs_first_run_setup_reflects_missing_tools() -> None:
    from autosplat.desktop import needs_first_run_setup

    with patch("autosplat.desktop.run_doctor", return_value=_results(ffmpeg=False)):
        assert needs_first_run_setup(config=object()) is True  # type: ignore[arg-type]
    with patch("autosplat.desktop.run_doctor", return_value=_results()):
        assert needs_first_run_setup(config=object()) is False  # type: ignore[arg-type]


def test_build_setup_terminal_command_runs_script_in_terminal(tmp_path: Path) -> None:
    from autosplat.desktop import build_setup_terminal_command

    script = tmp_path / "install_deps.sh"
    cmd = build_setup_terminal_command(script)

    assert "Terminal" in cmd
    assert "do script" in cmd
    assert str(script) in cmd


def test_build_setup_terminal_command_quotes_spaced_paths() -> None:
    from autosplat.desktop import build_setup_terminal_command

    script = Path("/Users/me/My Apps/AutoSplat.app/Contents/Resources/install_deps.sh")
    cmd = build_setup_terminal_command(script)

    # The space-containing path must be shell-quoted so `bash …` doesn't split it.
    assert "'/Users/me/My Apps/AutoSplat.app/Contents/Resources/install_deps.sh'" in cmd


def test_pick_free_port_returns_a_bindable_port() -> None:
    from autosplat.desktop import pick_free_port

    port = pick_free_port()
    assert 1024 < port < 65536
    # The port the helper picked must actually be bindable right after.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))
