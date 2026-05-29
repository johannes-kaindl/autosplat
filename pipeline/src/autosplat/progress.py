# SPDX-License-Identifier: AGPL-3.0-or-later

"""`progress.json` — the single source of truth for live pipeline progress.

Written into a capture root every couple of seconds by the running pipeline and
read by any consumer (WebUI partial, CLI, tooling). Decoupled from log
throttling: the file always holds the latest heartbeat. Writes are atomic
(`os.replace`) so a 3 s-polling reader never sees a half-written file.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

_PROGRESS_FILENAME = "progress.json"


@dataclass
class ProgressState:
    """Latest known progress for a running capture.

    ``step``/``total_steps``/``psnr`` are populated only when the plateau
    monitor produces real eval metrics; they stay ``None`` for the common
    time-only heartbeat.
    """

    stage: str
    elapsed_s: float
    est_pct: float
    eta_s: float
    updated_at: str
    step: int | None = None
    total_steps: int | None = None
    psnr: float | None = None


def write_progress(capture_dir: Path, state: ProgressState) -> None:
    """Atomically write ``progress.json`` into ``capture_dir``.

    Writes to a sibling temp file and ``os.replace``s it into place so a
    concurrent reader either sees the old file or the new one — never a torn
    partial write and never a leftover temp file on success.
    """
    target = capture_dir / _PROGRESS_FILENAME
    tmp = capture_dir / f"{_PROGRESS_FILENAME}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(asdict(state)), encoding="utf-8")
    os.replace(tmp, target)


def read_progress(capture_dir: Path) -> ProgressState | None:
    """Read ``progress.json`` from ``capture_dir``.

    Returns ``None`` if the file is absent, unreadable, or not valid/complete
    JSON — never raises, so a warming-up or finished capture degrades cleanly.
    """
    target = capture_dir / _PROGRESS_FILENAME
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return ProgressState(**raw)
    except TypeError:
        return None
