# SPDX-License-Identifier: AGPL-3.0-or-later

"""Quality-Gate stage — Phase-3 validation between SfM and Brush (spec §11.3).

Bails out *before* the expensive Brush stage when the COLMAP output is too thin
to produce a usable splat. Two thresholds:

  - cameras_registered / frames_kept ratio  (default 0.5)
  - absolute sparse-point count             (default 5000)

When the gate fails, it raises `QualityGateFailure` carrying a structured
`retry_hint` dict that the watcher can apply to the next run's config (e.g.
swap `colmap.matcher` from sequential to exhaustive).

Both the threshold defaults and the hint policy come from Phase-0's ice_bird
investigation (docs/PHASE-0-CALIBRATION.md): 4 cameras out of 106 frames
with sequential matcher → exhaustive next.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import ColmapConfig, QualityGateConfig
from .logging import get_logger
from .sfm import SfmResult

logger = get_logger(__name__)


_CAPTURE_GUIDE_HINT = (
    " — see docs/CAPTURE-GUIDE.md (rotation-dominated footage and low-texture "
    "surfaces are common causes; no parameter tweak rescues these)."
)


class QualityGateFailure(Exception):
    """Raised by `check_sfm_quality` when SfM output doesn't meet thresholds.

    Carries enough context that the caller can:
      - log the structured reason
      - mark the capture failed in state.json
      - decide whether to schedule an adaptive retry with `retry_hint`

    str(exc) appends a pointer to docs/CAPTURE-GUIDE.md when this is a
    terminal failure (no `retry_hint` left to try). The CLI prints str(exc),
    the WebUI stores it in `JobState.error`, so the actionable advice lands
    in both UIs without any per-caller plumbing.
    """

    def __init__(
        self,
        reason: str,
        *,
        stage: str = "sfm_validation",
        retry_hint: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.retry_hint = retry_hint
        self.metrics = metrics or {}

    def __str__(self) -> str:
        if self.retry_hint is None:
            return f"{self.reason}{_CAPTURE_GUIDE_HINT}"
        return self.reason


@dataclass
class QualityCheckResult:
    ok: bool
    ratio: float
    points: int
    reason: str | None


def evaluate_sfm(
    sfm: SfmResult,
    frames_kept: int,
    cfg: QualityGateConfig,
) -> QualityCheckResult:
    """Pure helper — computes pass/fail without raising. Useful for tests + status."""
    if frames_kept <= 0:
        return QualityCheckResult(ok=False, ratio=0.0, points=sfm.points, reason="no_frames_kept")
    ratio = sfm.cameras_registered / frames_kept
    if ratio < cfg.min_camera_ratio:
        return QualityCheckResult(
            ok=False,
            ratio=ratio,
            points=sfm.points,
            reason=f"low_camera_ratio: {ratio:.2f} < {cfg.min_camera_ratio}",
        )
    if sfm.points < cfg.min_points:
        return QualityCheckResult(
            ok=False,
            ratio=ratio,
            points=sfm.points,
            reason=f"low_points: {sfm.points} < {cfg.min_points}",
        )
    return QualityCheckResult(ok=True, ratio=ratio, points=sfm.points, reason=None)


def _retry_hint_for(reason: str, colmap_cfg: ColmapConfig) -> dict[str, Any] | None:
    """Decide what config override (if any) might rescue the next attempt.

    Currently: only the sequential→exhaustive matcher swap. Spec §9.2 lists this
    as the recommended retry for low camera registration. No hint for low-points
    because that usually means the source footage is structurally bad and no
    pipeline-side tweak will fix it.
    """
    if reason.startswith("low_camera_ratio") and colmap_cfg.matcher == "sequential":
        return {"colmap": {"matcher": "exhaustive"}}
    return None


def retry_hint_for_brush_oom(resolution_cap_attempted: int) -> dict[str, Any]:
    """Phase-6 / Spec §9.2: Brush OOM → retry with halved resolution_cap.

    Halves the value, clamped to the Pydantic minimum (256). Returns the
    full nested override dict ready for `apply_override`.
    """
    halved = max(256, resolution_cap_attempted // 2)
    return {"brush": {"resolution_cap": halved}}


def check_sfm_quality(
    sfm: SfmResult,
    frames_kept: int,
    cfg: QualityGateConfig,
    colmap_cfg: ColmapConfig,
) -> None:
    """Raise QualityGateFailure if SfM output is below thresholds. Otherwise no-op."""
    if not cfg.enabled:
        logger.debug("quality_gate.disabled")
        return

    result = evaluate_sfm(sfm, frames_kept, cfg)
    metrics = {
        "cameras_registered": sfm.cameras_registered,
        "frames_kept": frames_kept,
        "ratio": round(result.ratio, 4),
        "points": result.points,
        "matcher": colmap_cfg.matcher,
    }

    if result.ok:
        logger.info("quality_gate.passed", **metrics)
        return

    hint = _retry_hint_for(result.reason or "", colmap_cfg)
    logger.warning(
        "quality_gate.failed",
        reason=result.reason,
        retry_hint=hint,
        **metrics,
    )
    raise QualityGateFailure(
        reason=result.reason or "unknown",
        stage="sfm_validation",
        retry_hint=hint,
        metrics=metrics,
    )
