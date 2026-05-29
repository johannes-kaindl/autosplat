# SPDX-License-Identifier: AGPL-3.0-or-later

"""Desktop-app launcher for the bundled AutoSplat.app.

Splits cleanly into pure, testable logic (tool detection, setup-command
construction, port picking) and the integration glue (`main`, rumps menubar)
added in slice 2. The frozen `.app` entry point is `main`.
"""

from __future__ import annotations

import shlex
import socket
from pathlib import Path

from .config import Config
from .doctor import run_doctor

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
