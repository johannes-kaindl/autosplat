# SPDX-License-Identifier: AGPL-3.0-or-later

"""What `migrate-storage` would reclaim, decided separately from how it is shown.

The rules lived inside `cli.py`'s command body, interleaved with Rich table
construction, which made them reachable only from a terminal. They are
unchanged here — `tests/test_cli_migrate_storage.py` is the oracle for that —
but now a WebUI page can ask the same question.

Nothing in this module decides *whether* a target may be deleted: that is
`lifecycle.reclaimable_targets` / `protected_targets`, called, never restated.
The one time that rule was written a second time it was wrong twice.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from autosplat import cleanup, lifecycle
from autosplat.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PlanRow:
    display: str
    kind: str  # reclaim | kept | active | failed | outputs_reclaim | outputs_kept
    label: str
    size: int
    targets: tuple[Path, ...] = ()
    capture_dir: Path | None = None
    outputs_entry: Path | None = None


@dataclass(frozen=True)
class MigrationPlan:
    rows: tuple[PlanRow, ...]
    reclaimable_bytes: int
    skipped: int
    duplicate_names: tuple[str, ...]


@dataclass(frozen=True)
class ApplyResult:
    reclaimed_bytes: int
    failures: tuple[str, ...]


def target_labels(capture_dir: Path, targets: list[Path]) -> str:
    """Name reclaim targets by their path relative to the capture.

    A bare `.name` is ambiguous now that targets can be nested: `share/_tmp`
    and `rescue/probes` would both read as a single opaque leaf ("_tmp",
    "probes") in a report whose whole purpose is telling the user exactly what
    is about to be deleted.
    """
    return ", ".join(t.relative_to(capture_dir).as_posix() for t in targets)


def plan_migration(captures_dir: Path, outputs_dir: Path, *, now: datetime) -> MigrationPlan:
    """What a migrate-storage run would reclaim, and what it would keep and why.

    Relaxed rule for the backlog: a finished PLY is enough — review status is
    not required, otherwise no legacy capture would ever qualify.

    Callers must apply their own unsafe-layout guard before acting on this
    (see `cli._refuse_if_unsafe_storage_layout`); a planner that refused by
    raising would be awkward to render.
    """
    rows: list[PlanRow] = []
    total = 0
    skipped = 0

    capture_dirs = lifecycle.find_capture_dirs(captures_dir)

    # Deliberate last-wins on a basename collision (the real backlog has
    # repeated names, e.g. two unrelated captures both called
    # "2026-05-25_A_vor1" under different parents) — reported below rather
    # than silently letting an outputs/<name> match resolve against
    # whichever capture happened to be enumerated last.
    capture_by_name: dict[str, Path] = {}
    duplicate_names: set[str] = set()
    for c in capture_dirs:
        if c.name in capture_by_name:
            duplicate_names.add(c.name)
        capture_by_name[c.name] = c

    for capture_dir in capture_dirs:
        display = str(capture_dir.relative_to(captures_dir))
        if lifecycle.find_ply(capture_dir) is None:
            # Failed/unfinished capture — colmap/rescue are still needed for
            # diagnosis or `resume`. Listed (not skipped silently) so the user
            # can see why it's absent from the reclaim total.
            skipped += 1
            rows.append(
                PlanRow(
                    display=display,
                    kind="failed",
                    label="failed — kept (no scene.ply)",
                    size=0,
                    capture_dir=capture_dir,
                )
            )
            continue

        # The safety rule itself lives in `lifecycle.reclaimable_targets`, so
        # every deletion path inherits it. All that is left here is naming
        # what was kept, which `protected_targets` answers.
        targets = lifecycle.reclaimable_targets(capture_dir)
        protected = lifecycle.protected_targets(capture_dir)
        if not targets and not protected:
            continue  # genuinely nothing there — nothing to explain
        protected_note = (
            f" (kept: {target_labels(capture_dir, protected)} — holds a nested capture)"
            if protected
            else ""
        )
        if not targets:
            # Something was there, but every single target is protected (e.g. a
            # nested capture buried in rescue/) — listed as kept, by name,
            # instead of letting the capture vanish with no explanation.
            skipped += 1
            rows.append(
                PlanRow(
                    display=display,
                    kind="kept",
                    label=f"kept{protected_note}",
                    size=0,
                    capture_dir=capture_dir,
                )
            )
            continue

        size = lifecycle.bytes_in(targets)

        if lifecycle.recently_active(capture_dir, now=now):
            # The old output/scene.ply keeps its stale mtime for the whole
            # duration of an add-video/resume rebuild while frames/colmap are
            # rewritten from scratch, so reclaim eligibility alone can't tell a
            # finished capture from one mid-rebuild.
            skipped += 1
            rows.append(
                PlanRow(
                    display=display,
                    kind="active",
                    label=f"active — skipped (in-flight run){protected_note}",
                    size=size,
                    capture_dir=capture_dir,
                )
            )
            continue

        total += size
        # A target can be protected even while others on the same capture are
        # reclaimed normally (a probe that succeeded sits next to abandoned
        # ones under rescue/) — protected_note names it instead of letting it
        # disappear from this row with no trace, which is exactly what hid the
        # round-2 regression until real data surfaced it.
        rows.append(
            PlanRow(
                display=display,
                kind="reclaim",
                label=f"{target_labels(capture_dir, targets)}{protected_note}",
                size=size,
                targets=tuple(targets),
                capture_dir=capture_dir,
            )
        )

    if outputs_dir.is_dir():
        for entry in sorted(outputs_dir.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                continue
            size = lifecycle.bytes_in([entry])
            owning_capture = capture_by_name.get(entry.name)
            if owning_capture is not None and lifecycle.find_ply(owning_capture) is not None:
                total += size
                rows.append(
                    PlanRow(
                        display=f"outputs/{entry.name}",
                        kind="outputs_reclaim",
                        label="duplicate — reclaimed",
                        size=size,
                        outputs_entry=entry,
                    )
                )
                continue
            # Otherwise it is the last surviving copy of a scene whose capture
            # directory is gone (or never finished): kept unconditionally, no
            # matter how long it has sat there.
            skipped += 1
            rows.append(
                PlanRow(
                    display=f"outputs/{entry.name}",
                    kind="outputs_kept",
                    label=(
                        "orphaned — kept (no capture holds this scene)"
                        if owning_capture is None
                        else "duplicate — kept (capture has no scene.ply yet)"
                    ),
                    size=size,
                    outputs_entry=entry,
                )
            )

    return MigrationPlan(
        rows=tuple(rows),
        reclaimable_bytes=total,
        skipped=skipped,
        duplicate_names=tuple(sorted(duplicate_names)),
    )


def apply_migration(plan: MigrationPlan) -> ApplyResult:
    """Execute a plan's reclaim rows. One failure never stops the sweep."""
    reclaimed = 0
    failures: list[str] = []

    for row in plan.rows:
        if row.kind == "reclaim" and row.capture_dir is not None:
            try:
                result = cleanup.prune_intermediates(row.capture_dir, targets=list(row.targets))
            except Exception as e:
                failures.append(f"{row.capture_dir} — {e}")
                continue
            reclaimed += result.bytes_reclaimed
            failures.extend(str(f) for f in result.failed)
        elif row.kind == "outputs_reclaim" and row.outputs_entry is not None:
            try:
                size = lifecycle.bytes_in([row.outputs_entry])
                shutil.rmtree(row.outputs_entry)
            except OSError as e:
                failures.append(f"{row.outputs_entry} — {e}")
                continue
            reclaimed += size

    logger.info("migration.applied", reclaimed=reclaimed, failures=len(failures))
    return ApplyResult(reclaimed_bytes=reclaimed, failures=tuple(failures))
