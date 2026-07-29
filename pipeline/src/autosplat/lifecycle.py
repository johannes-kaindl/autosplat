# SPDX-License-Identifier: AGPL-3.0-or-later

"""Derives a capture's lifecycle state and what may be reclaimed from it.

Single source of truth for retention. Pure and read-only: state is DERIVED
from files and mtimes, never stored. That is what makes the v1.15.0 review
gate correct — a rebuilt scene.ply invalidates everything downstream by mtime
alone, with no bookkeeping to keep in sync — and this module preserves it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

LifecycleState = Literal["failed", "done", "reviewed", "archived"]
ReviewStatus = Literal["unreviewed", "reviewed"]

# Working dirs that hold nothing worth keeping once the scene is signed off.
# `training` predates the current pipeline but is still written every run
# (`train.py` points Brush's `--export-path` at it) and exists in legacy
# captures too. `source` is deliberately absent — see the design doc:
# sub-project 4 decides whether the source video belongs in a capture at all.
#
# `rescue` is deliberately NOT here: `rescue/clips/*.mp4` are the leaf-clip
# sources a bisection-rescued capture records in pipeline.log as its origin,
# and `add-video`/`resume` re-extract from them. Deleting them makes
# `add-video` fail with "cannot extend a capture whose origin is unknown",
# recoverable only by re-running bisection (5h36m on the documented
# max_strasse case) against an original video that may no longer exist.
# `cleanup-rescue` keeps them by default for exactly that reason; the probe
# workspaces underneath `rescue/probes/` — where the mass actually sits
# (3,1 GB on the maintainer's tree) — are reclaimed instead, see below.
RECLAIMABLE_SUBDIRS: tuple[str, ...] = (
    "frames",
    "colmap",
    "training",
    "brush_dataset",
)

# Reclaimable paths that are not top-level subdirs of the same shape.
_EXTRA_RECLAIMABLE: tuple[tuple[str, ...], ...] = (
    ("share", "_tmp"),
    ("rescue", "probes"),
)

# Directory names that are never a capture in their own right — recursion in
# `find_capture_dirs` stops at them. Kept separate from RECLAIMABLE_SUBDIRS:
# `rescue/` is no longer reclaimable wholesale, but it is still a working dir
# of its capture, and descending into it would register every bisection probe
# workspace (`frames/` + `colmap/`, no PLY) as a capture of its own.
_NON_CAPTURE_SUBDIRS: tuple[str, ...] = (*RECLAIMABLE_SUBDIRS, "rescue", "output")

# The pipeline's capture-directory naming scheme: YYYY-MM-DD_<stem>.
CAPTURE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_.+$")


@dataclass(frozen=True)
class Lifecycle:
    state: LifecycleState
    reclaimable: list[Path]
    reclaimable_bytes: int
    grace_days_left: int | None


def review_marker_path(capture_dir: Path) -> Path:
    """Where the publish-quality-gate review marker lives for a capture."""
    return capture_dir / "output" / ".review.json"


def review_status(capture_dir: Path) -> ReviewStatus:
    """Compute review status from the marker file vs. output/scene.ply's mtime.

    Purely mtime-based invalidation: a rebuilt scene.ply (different mtime)
    silently reverts the capture to unreviewed, so callers that regenerate
    scene.ply (add-video, resume) need no awareness of review state at all.
    """
    marker = review_marker_path(capture_dir)
    if not marker.exists():
        return "unreviewed"
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreviewed"
    if not isinstance(data, dict):
        return "unreviewed"
    recorded_mtime = data.get("source_ply_mtime")
    scene_ply = capture_dir / "output" / "scene.ply"
    try:
        current_mtime = scene_ply.stat().st_mtime
    except OSError:
        return "unreviewed"
    if recorded_mtime != current_mtime:
        return "unreviewed"
    return "reviewed"


def find_ply(capture_dir: Path) -> Path | None:
    """The capture's canonical PLY, newest layout first."""
    for candidate in [
        capture_dir / "output" / "scene.ply",
        capture_dir / "scene.ply",
    ]:
        if candidate.exists():
            return candidate
    plys = sorted(capture_dir.glob("*.ply"))
    return plys[0] if plys else None


def resolve_publish_ply(capture_dir: Path, status: ReviewStatus) -> Path | None:
    """Which PLY represents this capture for viewing/sharing.

    Prefers the manually-cleaned output/scene_reviewed.ply once the capture
    is reviewed and that file exists; otherwise falls back to find_ply. A
    stale scene_reviewed.ply left over from before a rebuild is automatically
    skipped once `status` recomputes to unreviewed.
    """
    if status == "reviewed":
        reviewed_ply = capture_dir / "output" / "scene_reviewed.ply"
        if reviewed_ply.exists():
            return reviewed_ply
    return find_ply(capture_dir)


def _candidate_targets(capture_dir: Path) -> list[Path]:
    """Existing working dirs of `capture_dir`, before the safety filter."""
    targets = [capture_dir / sub for sub in RECLAIMABLE_SUBDIRS]
    targets += [capture_dir.joinpath(*parts) for parts in _EXTRA_RECLAIMABLE]
    return [t for t in targets if t.is_dir()]


def holds_exported_result(target: Path) -> bool:
    """True if `target` is, or buries, a directory that produced an exported
    result of its own — `output/scene.ply`, or a top-level `scene.ply`.

    This is the spec's hard safety rule ("a directory containing the only PLY
    of a capture is never touched") in its one and only implementation. It
    lives here rather than in `migrate-storage` because it must hold for
    every deletion path: the review-triggered prune, the grace sweep and
    `cleanup-intermediates` reach the same shapes with no human in the loop.

    Deliberately NOT `is_capture_dir`'s full signature (which also matches a
    directory holding just `frames/` + `colmap/`, no PLY) — that is exactly
    what `bisection._probe_workspace_for` writes for every probe, and an
    abandoned probe workspace is pure intermediate, not a result worth
    protecting. Equally, a loose `training/scene.ply` (a Brush checkpoint
    `export.py` already copied to `output/`) is a duplicate, not a nested
    capture: only a *directory* that exported qualifies.

    Only *subdirectories* are inspected, never `target` itself: a PLY sitting
    loose directly in the target (`training/scene.ply`) is a Brush checkpoint
    `export.py` already copied to `output/` — a duplicate, and protecting it
    hid 1,8 GB on the real tree. The capture's own published PLY is handled
    separately, by `protected_targets`.

    Tolerant of unreadable or vanishing entries, like `bytes_in` and
    `recently_active`: this runs inside `migrate-storage`'s preview and the
    dashboard's per-capture sizing, where an OSError must not abort the
    whole listing with a traceback. An entry that cannot be read cannot be
    shown to hold a result, so it does not protect the target — the walk
    simply continues.
    """
    try:
        walker = target.rglob("*")
    except OSError:
        return False
    while True:
        try:
            p = next(walker)
        except StopIteration:
            break
        except OSError:
            # A directory vanished or is unreadable mid-walk — nothing more
            # to inspect down this branch.
            continue
        try:
            if not p.is_dir():
                continue
            if (p / "output" / "scene.ply").exists() or (p / "scene.ply").exists():
                return True
        except OSError:
            continue
    return False


def protected_targets(capture_dir: Path) -> list[Path]:
    """Candidate targets withheld from reclaim because they bury a result.

    The complement of `reclaimable_targets` over the same candidate list.
    Exists so `migrate-storage` can *name* what it kept in its report without
    re-deriving the rule — display logic only; the rule itself is enforced by
    `reclaimable_targets`, which every deletion path goes through.
    """
    ply = find_ply(capture_dir)
    return [
        t
        for t in _candidate_targets(capture_dir)
        if holds_exported_result(t) or (ply is not None and (ply == t or t in ply.parents))
    ]


def reclaimable_targets(capture_dir: Path) -> list[Path]:
    """Existing working dirs of `capture_dir`, regardless of lifecycle state.

    Never includes a target that is, or buries, an exported result — see
    `holds_exported_result`. Every deletion path (`cleanup.prune_intermediates`
    and therefore `sweep_expired`, the review-triggered prune,
    `cleanup-intermediates`, and `migrate-storage`) derives its targets from
    here, so the safety rule cannot hold in one path and not another.
    """
    protected = protected_targets(capture_dir)
    return [t for t in _candidate_targets(capture_dir) if t not in protected]


def bytes_in(targets: list[Path]) -> int:
    """Total bytes under `targets`, recursively.

    Tolerant of concurrent deletion: `list_captures`/the dashboard route call
    this per capture on every request, and the background grace sweep (or a
    concurrent CLI run) can be removing files under the same tree at the same
    time. A file or directory vanishing mid-walk is treated as already
    reclaimed rather than raised.
    """
    total = 0
    for target in targets:
        try:
            walker = target.rglob("*")
        except OSError:
            continue
        while True:
            try:
                p = next(walker)
            except StopIteration:
                break
            except OSError:
                # A directory vanished mid-walk — nothing more to count here.
                continue
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    return total


def recently_active(capture_dir: Path, *, now: datetime, within_s: float = 3600) -> bool:
    """True if `capture_dir` shows signs of an in-flight run.

    Reclaim eligibility (`inspect`) only looks at output/scene.ply's mtime,
    which stays old for the entire duration of an `add-video`/`resume`
    rebuild — the old PLY is still sitting there while frames/ and colmap/
    are being rewritten. Without this check, a sweep landing mid-rebuild
    would `rmtree` the very directories a concurrent CLI process is writing
    to. Consulted by both the grace sweep and `migrate-storage --apply`,
    which can equally run during a rebuild.

    Looks at the newest mtime among files recursively under the capture's
    reclaimable targets (a rewrite touches files inside colmap/, not the dir
    itself) or its pipeline.log. Read-only and pure like the rest of this
    module; tolerates stat failures by treating that entry as not recent
    rather than raising.
    """
    newest = 0.0
    candidates: list[Path] = []
    for target in reclaimable_targets(capture_dir):
        try:
            candidates.extend(target.rglob("*"))
        except OSError:
            continue
    log = capture_dir / "pipeline.log"
    if log.exists():
        candidates.append(log)

    for p in candidates:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime > newest:
            newest = mtime

    if newest == 0.0:
        return False
    return (now.timestamp() - newest) < within_s


def _days_since(path: Path, now: datetime) -> int:
    age = now.timestamp() - path.stat().st_mtime
    return max(0, int(age // 86400))


def inspect(capture_dir: Path, *, now: datetime, grace_days: int) -> Lifecycle:
    """Derive lifecycle state and reclaimable targets for one capture.

    `grace_days` of 0 disables the unreviewed grace sweep entirely: an
    unreviewed capture then stays untouched forever.
    """
    ply = find_ply(capture_dir)
    if ply is None:
        # No PLY means the run never finished. Diagnosis needs colmap/ and
        # rescue/, so a failed capture keeps everything.
        return Lifecycle(state="failed", reclaimable=[], reclaimable_bytes=0, grace_days_left=None)

    targets = reclaimable_targets(capture_dir)

    if review_status(capture_dir) == "reviewed":
        state: LifecycleState = "archived" if not targets else "reviewed"
        return Lifecycle(
            state=state,
            reclaimable=targets,
            reclaimable_bytes=bytes_in(targets),
            grace_days_left=None,
        )

    if grace_days <= 0:
        return Lifecycle(state="done", reclaimable=[], reclaimable_bytes=0, grace_days_left=None)

    days_left = max(0, grace_days - _days_since(ply, now))
    if days_left > 0:
        # Still within the grace window — quality is unconfirmed, keep everything.
        return Lifecycle(
            state="done", reclaimable=[], reclaimable_bytes=0, grace_days_left=days_left
        )
    return Lifecycle(
        state="done",
        reclaimable=targets,
        reclaimable_bytes=bytes_in(targets),
        grace_days_left=0,
    )


def is_capture_dir(path: Path) -> bool:
    """True if `path` itself has the shape of a capture directory.

    Either it has already exported (`output/scene.ply`, or a legacy
    top-level `scene.ply`), or it looks like one still in progress (both
    `frames/` and `colmap/` present, no PLY yet) — the in-progress half is
    what `resume` needs it to keep matching.

    Answers only "where should `find_capture_dirs` stop recursing", which is
    its sole caller. It is deliberately NOT the retention safety predicate:
    reusing it as one cost a full fix round, because an abandoned bisection
    probe workspace has exactly the frames+colmap shape and is pure
    intermediate. That question is `holds_exported_result`'s.
    """
    if (path / "output" / "scene.ply").exists() or (path / "scene.ply").exists():
        return True
    return (path / "frames").is_dir() and (path / "colmap").is_dir()


def list_capture_dirs(captures_dir: Path) -> list[Path]:
    """The captures the UI lists — top-level, `YYYY-MM-DD_<stem>`, no recursion.

    THE definition of "a capture the user can see", shared by
    `webui.state.list_captures` and `cleanup.sweep_expired` so the two cannot
    drift. They did: the sweep enumerated via `find_capture_dirs` (recursive,
    no name filter) and so reclaimed captures the UI never showed and never
    counted down a grace period for — including the 6,4 GB nested legacy
    layout, and, because every existing capture is already past 30 days, most
    of the backlog on the very first launch after upgrading.

    Anything this does not return is deliberately left to `migrate-storage`:
    an explicit, previewable command is the right instrument for a
    non-conforming or nested layout, not a silent daemon thread.

    Symlinks are skipped — a symlinked capture dir would otherwise let the
    sweep `rmtree` through the link into a tree it was never pointed at.
    """
    if not captures_dir.is_dir():
        return []
    return sorted(
        entry
        for entry in captures_dir.iterdir()
        if entry.is_dir() and not entry.is_symlink() and CAPTURE_DIR_RE.match(entry.name)
    )


def find_capture_dirs(root: Path) -> list[Path]:
    """All capture directories under `root`, including nested legacy layouts.

    Pre-Phase-9 rescue runs nested a whole capture inside another directory
    (2026-05-25_max_strasse_rescue/2026-05-25_A_vor1). A non-recursive scan
    misses those entirely — which is how 8,1 GB stayed invisible to cleanup.
    Recursion stops at a directory that is itself a capture: its `rescue/`
    subtree is reclaimable as a whole, not a set of separate captures.
    """
    found: list[Path] = []
    if not root.is_dir():
        return found
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        if entry.name in _NON_CAPTURE_SUBDIRS:
            continue
        if is_capture_dir(entry):
            found.append(entry)
        else:
            found.extend(find_capture_dirs(entry))
    return found
