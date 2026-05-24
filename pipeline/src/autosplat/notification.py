# SPDX-License-Identifier: AGPL-3.0-or-later

"""macOS Notification Center integration for autosplat pipeline events."""

from __future__ import annotations

import platform
import subprocess

from .logging import get_logger

logger = get_logger(__name__)


def notify_training_complete(
    capture_name: str,
    duration_s: float,
    gaussians: int = 0,
) -> None:
    """Send a macOS Notification Center alert after training completes.

    No-op on non-macOS systems or when osascript is unavailable.
    Failures are logged at DEBUG level and never propagate.
    """
    if platform.system() != "Darwin":
        return
    mins = int(duration_s // 60)
    secs = int(duration_s % 60)
    duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"
    if gaussians:
        body = f"{capture_name} — {gaussians:,} Gaussians in {duration_str}"
    else:
        body = f"{capture_name} — training done in {duration_str}"
    title = "autosplat: Training complete"
    script = f'display notification "{body}" with title "{title}"'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
            check=False,
        )
        logger.debug("notification.sent", capture=capture_name, duration_s=duration_s)
    except Exception as exc:
        logger.debug("notification.failed", error=str(exc))
