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


# ─── launcher orchestration (slice 2) ──────────────────────────────────────


def test_serve_url_formats_localhost_url() -> None:
    from autosplat.desktop import serve_url

    assert serve_url(8080) == "http://127.0.0.1:8080"


def test_make_server_binds_configured_host_and_port() -> None:
    from autosplat.desktop import make_server

    async def _app(scope, receive, send):  # minimal ASGI callable
        pass

    server = make_server(_app, "127.0.0.1", 8137)
    assert server.config.host == "127.0.0.1"
    assert server.config.port == 8137


def test_open_browser_calls_opener_with_url() -> None:
    from autosplat.desktop import open_browser

    calls: list[str] = []
    open_browser("http://127.0.0.1:9999", opener=calls.append)
    assert calls == ["http://127.0.0.1:9999"]


def test_wait_until_serving_true_when_port_listens() -> None:
    from autosplat.desktop import wait_until_serving

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert wait_until_serving("127.0.0.1", port, timeout=2.0) is True


def test_wait_until_serving_false_on_timeout() -> None:
    from autosplat.desktop import pick_free_port, wait_until_serving

    # A free (unbound) port → nothing accepts → times out to False fast.
    dead = pick_free_port()
    assert wait_until_serving("127.0.0.1", dead, timeout=0.5) is False


def test_run_first_run_setup_invokes_osascript_with_command(tmp_path: Path) -> None:
    from autosplat.desktop import run_first_run_setup

    script = tmp_path / "install_deps.sh"
    captured: list[list[str]] = []

    def _runner(args, **kw):  # stand-in for subprocess.run
        captured.append(args)

    run_first_run_setup(script, runner=_runner)

    assert len(captured) == 1
    args = captured[0]
    assert args[0] == "osascript"
    assert "-e" in args
    # The AppleScript handed to osascript must reference the install script.
    assert any(str(script) in part for part in args)
