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
    return (
        'tell application "Terminal"\n'
        f"  do script \"bash {quoted}\"\n"
        "  activate\n"
        "end tell"
    )


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


def main() -> None:  # pragma: no cover - integration entry (rumps UI + real server)
    """Frozen-app / `autosplat app` entry point.

    Runs first-run setup if tools are missing, serves the WebUI in a background
    thread, opens the browser, and shows a rumps menubar item to open/quit.
    """
    from .config import load_config
    from .webui import create_app

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

    # Headless smoke mode (build verification / CI): serve without browser or
    # menubar so the frozen bundle can be curl-checked end-to-end.
    if os.environ.get("AUTOSPLAT_APP_HEADLESS"):
        while not getattr(server, "should_exit", False):
            time.sleep(1)
        return

    # Give uvicorn a moment to bind before opening the browser.
    time.sleep(1.0)
    open_browser(url)

    _run_menubar(url, server)


def _bundled_install_script() -> Path | None:
    """Locate install_deps.sh in the bundle (Resources/) or the dev checkout."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "scripts" / "install_deps.sh",
        Path(__file__).resolve().parent / "scripts" / "install_deps.sh",
    ]
    return next((c for c in candidates if c.is_file()), None)


def _run_menubar(url: str, server: uvicorn.Server) -> None:  # pragma: no cover - rumps UI
    """Show a menubar item. Falls back to blocking on the server if rumps is absent."""
    try:
        import rumps
    except ImportError:
        logger.warning("desktop.rumps_missing", detail="menubar unavailable; serving headless")
        while not getattr(server, "should_exit", False):
            time.sleep(1)
        return

    class AutoSplatApp(rumps.App):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__("AutoSplat", title="◆ AutoSplat")
            self.menu = ["Open AutoSplat"]

        @rumps.clicked("Open AutoSplat")
        def open_app(self, _: object) -> None:
            open_browser(url)

    app = AutoSplatApp()

    @rumps.clicked("Quit")  # type: ignore[misc]
    def _quit(_: object) -> None:
        server.should_exit = True
        rumps.quit_application()

    app.run()
