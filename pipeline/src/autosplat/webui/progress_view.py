# SPDX-License-Identifier: AGPL-3.0-or-later

"""Turn a raw `ProgressState` into a display-ready view model for the WebUI.

Pure + clock-injected (`now` is a parameter) so the formatting and stall logic
are deterministically testable without patching time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from autosplat.progress import ProgressState

# How long without a heartbeat before we flag a run as possibly stalled. The
# pipeline writes progress.json every ~2 s, so 90 s of silence is well outside
# normal jitter and worth surfacing rather than letting the screen sit still.
STALL_THRESHOLD_S = 90


@dataclass
class ProgressView:
    pct: int
    elapsed_str: str
    eta_remaining_str: str
    updated_ago_s: int
    stalled: bool
    step: int | None
    total_steps: int | None
    psnr: float | None

    @property
    def has_eval(self) -> bool:
        return self.step is not None


def _fmt_mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def build_progress_view(state: ProgressState, now: datetime) -> ProgressView:
    """Derive percent, mm:ss elapsed/remaining, and liveness from `state`."""
    updated = datetime.fromisoformat(state.updated_at.replace("Z", "+00:00"))
    ago = max(0, int((now - updated).total_seconds()))
    remaining = max(0.0, state.eta_s - state.elapsed_s)
    return ProgressView(
        pct=round(state.est_pct * 100),
        elapsed_str=_fmt_mmss(state.elapsed_s),
        eta_remaining_str=_fmt_mmss(remaining),
        updated_ago_s=ago,
        stalled=ago > STALL_THRESHOLD_S,
        step=state.step,
        total_steps=state.total_steps,
        psnr=state.psnr,
    )
