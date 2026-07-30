# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autosplat import migration


def _settled_capture(captures: Path, name: str, *, with_ply: bool = True) -> Path:
    capture = captures / name
    (capture / "output").mkdir(parents=True)
    if with_ply:
        (capture / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 100)
    (capture / "frames").mkdir()
    (capture / "frames" / "0001.png").write_bytes(b"x" * 5000)
    if not with_ply:
        # `lifecycle.is_capture_dir` recognises an in-progress capture only
        # by the frames/ + colmap/ shape (no PLY yet) — without a colmap/
        # dir this fixture wouldn't be recognised as a capture at all, and
        # `find_capture_dirs` would recurse straight past it, producing no
        # row of any kind. See `lifecycle.is_capture_dir`.
        (capture / "colmap").mkdir()
    ts = time.time() - 2 * 3600
    for p in [capture, *capture.rglob("*")]:
        os.utime(p, (ts, ts))
    return capture


def test_plan_lists_a_finished_capture_as_reclaimable(tmp_path: Path) -> None:
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    _settled_capture(captures, "2026-05-01_demo")

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert plan.reclaimable_bytes > 0
    kinds = {r.kind for r in plan.rows}
    assert "reclaim" in kinds


def test_plan_keeps_a_capture_without_a_ply(tmp_path: Path) -> None:
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    _settled_capture(captures, "2026-05-02_failed", with_ply=False)

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert plan.reclaimable_bytes == 0
    assert [r for r in plan.rows if r.kind == "failed"]
    assert plan.skipped == 1


def test_plan_never_reclaims_an_orphaned_outputs_entry(tmp_path: Path) -> None:
    """The 10 orphans on the real disk are each the last copy of their scene."""
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    orphan = outputs / "2026-04-01_gone"
    orphan.mkdir(parents=True)
    (orphan / "scene.ply").write_bytes(b"ply\n" + b"x" * 900)

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert plan.reclaimable_bytes == 0
    row = next(r for r in plan.rows if r.kind == "outputs_kept")
    assert "orphaned" in row.label


def test_plan_skips_a_capture_with_an_in_flight_run(tmp_path: Path) -> None:
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    capture = _settled_capture(captures, "2026-05-03_live")
    (capture / "pipeline.log").write_text("running\n")  # fresh mtime

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert [r for r in plan.rows if r.kind == "active"]
    assert plan.reclaimable_bytes == 0


def test_plan_delegates_eligibility_to_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The protective predicate must be lifecycle's, not a second copy.

    Written twice, this rule was wrong twice — once locking training/ out of
    cleanup forever, once exposing the bisection probe workspaces. Neutering
    lifecycle.reclaimable_targets must therefore neuter the whole plan; if
    anything is still planned, migration.py has its own opinion about what
    may be deleted, and that is the defect.
    """
    from autosplat import lifecycle

    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    _settled_capture(captures, "2026-05-05_demo")

    monkeypatch.setattr(lifecycle, "reclaimable_targets", lambda _c: [])

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert plan.reclaimable_bytes == 0
    assert not [r for r in plan.rows if r.kind == "reclaim"]


def test_apply_reclaims_only_planned_targets(tmp_path: Path) -> None:
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    capture = _settled_capture(captures, "2026-05-04_demo")

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))
    result = migration.apply_migration(plan)

    assert result.failures == ()
    assert result.reclaimed_bytes > 0
    assert not (capture / "frames").exists()
    assert (capture / "output" / "scene.ply").exists()
