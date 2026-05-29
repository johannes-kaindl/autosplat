# SPDX-License-Identifier: AGPL-3.0-or-later

"""Desktop-app launcher for the bundled AutoSplat.app.

Splits cleanly into pure, testable logic (tool detection, setup-command
construction, port picking) and the integration glue (`main`, rumps menubar)
added in slice 2. The frozen `.app` entry point is `main`.
"""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import Config
from .doctor import run_doctor
from .logging import get_logger

if TYPE_CHECKING:
    import uvicorn

logger = get_logger(__name__)

# External tools the first-run setup can install via Homebrew + fetch_brush.sh.
# A missing one of these (and only these) triggers the setup flow — a failing
# platform/python check can't be fixed by `brew install`, and optional checks
# (compress) must not block launch.
_INSTALLABLE_TOOLS = ("ffmpeg", "colmap", "brush")


def missing_required_tools(config: Config) -> list[str]:
    """Names of installable external tools that doctor reports as missing."""
    try:
        results = run_doctor(config)
    except Exception:
        # If doctor itself blows up, surface every installable tool so the user
        # is steered to setup rather than into a broken launch.
        return list(_INSTALLABLE_TOOLS)
    return [r.name for r in results if r.name in _INSTALLABLE_TOOLS and not r.ok]


def needs_first_run_setup(config: Config) -> bool:
    """True when at least one installable external tool is missing."""
    return bool(missing_required_tools(config))


def build_setup_terminal_command(install_script: Path) -> str:
    """AppleScript that runs the dependency installer in a visible Terminal.

    Driven through Terminal (not in-app) so the user sees Homebrew's progress and
    can answer its password prompt; the app just polls doctor until tools appear.
    """
    quoted = shlex.quote(str(install_script))
    return f'tell application "Terminal"\n  do script "bash {quoted}"\n  activate\nend tell'


# Homebrew bin dirs. A GUI-launched .app inherits launchd's minimal PATH
# (/usr/bin:/bin:/usr/sbin:/sbin) — NOT the user's shell PATH — so ffmpeg/colmap
# installed via Homebrew are invisible unless we add these explicitly.
_HOMEBREW_BINS = ("/opt/homebrew/bin", "/usr/local/bin")


def ensure_homebrew_path(path: str) -> str:
    """Return `path` with the Homebrew bin dirs prepended if missing (no dups)."""
    parts = [p for p in path.split(":") if p]
    prefix = [b for b in _HOMEBREW_BINS if b not in parts]
    return ":".join(prefix + parts)


def pick_free_port() -> int:
    """Ask the OS for a currently-free localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_first_run_setup(
    install_script: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> None:
    """Open Terminal and run the dependency installer (via osascript)."""
    script = build_setup_terminal_command(install_script)
    runner(["osascript", "-e", script], check=False)


# ─── launcher orchestration ────────────────────────────────────────────────

_HOST = "127.0.0.1"


def serve_url(port: int) -> str:
    return f"http://{_HOST}:{port}"


def make_server(app: Any, host: str, port: int) -> uvicorn.Server:
    """Build a uvicorn Server for `app` (log_level warning — the menubar is the UI)."""
    import uvicorn

    return uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))


def open_browser(url: str, opener: Callable[[str], Any] = webbrowser.open) -> None:
    opener(url)


def wait_until_serving(host: str, port: int, timeout: float = 10.0) -> bool:
    """Poll until `host:port` accepts a TCP connection, or `timeout` elapses.

    Condition-based readiness so the app window loads the WebUI only once uvicorn
    is actually bound — no arbitrary sleep, no blank-page-then-error flash.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def main() -> None:  # pragma: no cover - integration entry (rumps UI + real server)
    """Frozen-app / `autosplat app` entry point.

    Runs first-run setup if tools are missing, serves the WebUI in a background
    thread, opens the browser, and shows a rumps menubar item to open/quit.
    """
    from .config import load_config
    from .webui import create_app

    # A Finder/Dock launch inherits launchd's minimal PATH, hiding Homebrew
    # tools (ffmpeg/colmap) from both doctor and the pipeline subprocesses.
    # Fix it before anything reads PATH, or the run hangs in first-run setup.
    os.environ["PATH"] = ensure_homebrew_path(os.environ.get("PATH", ""))

    cfg = load_config()

    if needs_first_run_setup(cfg):
        script = _bundled_install_script()
        if script is not None:
            run_first_run_setup(script)
        # Poll until the required tools appear (user-driven; cancellable by quit).
        while needs_first_run_setup(cfg):
            time.sleep(3)

    port = int(os.environ.get("AUTOSPLAT_APP_PORT", "0")) or pick_free_port()
    server = make_server(create_app(cfg), _HOST, port)
    threading.Thread(target=server.run, name="autosplat-webui", daemon=True).start()
    url = serve_url(port)
    logger.info("desktop.serving", url=url)

    # Headless smoke mode (build verification / CI): serve without a window so
    # the frozen bundle can be curl-checked end-to-end.
    if os.environ.get("AUTOSPLAT_APP_HEADLESS"):
        _block_until_exit(server)
        return

    # Wait for uvicorn to bind before pointing the window at it.
    if not wait_until_serving(_HOST, port):
        logger.error("desktop.server_not_ready", url=url)
    _run_window(url, server)


def _bundled_install_script() -> Path | None:
    """Locate install_deps.sh in the bundle (Resources/) or the dev checkout."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "scripts" / "install_deps.sh",
        Path(__file__).resolve().parent / "scripts" / "install_deps.sh",
    ]
    return next((c for c in candidates if c.is_file()), None)


def _block_until_exit(server: uvicorn.Server) -> None:  # pragma: no cover - loop
    while not getattr(server, "should_exit", False):
        time.sleep(1)


def _run_window(url: str, server: uvicorn.Server) -> None:  # pragma: no cover - GUI
    """Open a native app window (WKWebView) showing the WebUI and block until it
    closes. Falls back to the default browser if pywebview is unavailable."""
    try:
        import webview
    except ImportError:
        logger.warning("desktop.webview_missing", detail="no pywebview; opening browser instead")
        open_browser(url)
        _block_until_exit(server)
        return

    webview.create_window("AutoSplat", url, width=1280, height=860, min_size=(900, 600))
    webview.start()  # blocks on the Cocoa run loop until the window is closed
    server.should_exit = True
