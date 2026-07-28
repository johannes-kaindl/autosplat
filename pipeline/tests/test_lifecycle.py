# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autosplat import lifecycle


def _make_capture(root: Path, name: str, *, with_ply: bool = True) -> Path:
    capture = root / name
    (capture / "output").mkdir(parents=True)
    if with_ply:
        (capture / "output" / "scene.ply").write_bytes(b"ply\nend_header\n")
    return capture


def _mark_reviewed(capture: Path) -> None:
    ply = capture / "output" / "scene.ply"
    marker = capture / "output" / ".review.json"
    marker.write_text(json.dumps({"source_ply_mtime": ply.stat().st_mtime}), encoding="utf-8")


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def test_failed_when_no_ply(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x", with_ply=False)
    (capture / "colmap").mkdir()

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "failed"
    assert result.reclaimable == []  # failed keeps everything for diagnosis


def test_done_when_ply_but_no_marker(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "done"
    assert result.reclaimable == []  # not reclaimable until reviewed or grace expires


def test_reviewed_exposes_reclaimable_targets(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    (capture / "rescue").mkdir()
    (capture / "brush_dataset").mkdir()
    (capture / "colmap" / "db.bin").write_bytes(b"x" * 100)
    _mark_reviewed(capture)

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "reviewed"
    assert {p.name for p in result.reclaimable} == {"colmap", "rescue", "brush_dataset"}
    assert result.reclaimable_bytes == 100


def test_archived_when_reviewed_and_nothing_left(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    _mark_reviewed(capture)

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "archived"
    assert result.reclaimable_bytes == 0


def test_share_tmp_is_reclaimable(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "share" / "_tmp").mkdir(parents=True)
    (capture / "share" / "_tmp" / "scene.sog").write_bytes(b"y" * 50)
    (capture / "share" / "tok").mkdir()  # a real bundle — must NOT be reclaimed
    _mark_reviewed(capture)

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert [p.name for p in result.reclaimable] == ["_tmp"]
    assert result.reclaimable_bytes == 50


def test_marker_invalidated_by_rebuilt_ply(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    _mark_reviewed(capture)
    ply = capture / "output" / "scene.ply"
    import os

    os.utime(ply, (1_000_000, 1_000_000))  # simulate a rebuild

    assert lifecycle.review_status(capture) == "unreviewed"
    assert lifecycle.inspect(capture, now=NOW, grace_days=30).state == "done"


def test_reviewed_ply_preferred_when_reviewed(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "output" / "scene_reviewed.ply").write_bytes(b"ply\n")
    _mark_reviewed(capture)

    resolved = lifecycle.resolve_publish_ply(capture, "reviewed")

    assert resolved is not None
    assert resolved.name == "scene_reviewed.ply"


@pytest.mark.parametrize(
    ("age_days", "expected_left"),
    [(0, 30), (23, 7), (30, 0), (45, 0)],
)
def test_grace_days_left_counts_down(tmp_path: Path, age_days: int, expected_left: int) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    import os

    mtime = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(capture / "output" / "scene.ply", (mtime, mtime))

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "done"
    assert result.grace_days_left == expected_left


def test_grace_expiry_makes_targets_reclaimable(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    (capture / "colmap" / "db.bin").write_bytes(b"z" * 10)
    import os

    mtime = (NOW - timedelta(days=31)).timestamp()
    os.utime(capture / "output" / "scene.ply", (mtime, mtime))

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.grace_days_left == 0
    assert [p.name for p in result.reclaimable] == ["colmap"]


def test_grace_disabled_never_expires(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    import os

    mtime = (NOW - timedelta(days=999)).timestamp()
    os.utime(capture / "output" / "scene.ply", (mtime, mtime))

    result = lifecycle.inspect(capture, now=NOW, grace_days=0)

    assert result.grace_days_left is None
    assert result.reclaimable == []


def test_find_capture_dirs_finds_nested_legacy_layout(tmp_path: Path) -> None:
    # Reproduces 2026-05-25_max_strasse_rescue/2026-05-25_A_vor1 (8,1 GB on disk)
    outer = tmp_path / "2026-05-25_max_strasse_rescue"
    inner = outer / "2026-05-25_A_vor1"
    (inner / "output").mkdir(parents=True)
    (inner / "output" / "scene.ply").write_bytes(b"ply\n")
    (inner / "frames").mkdir()
    (inner / "colmap").mkdir()

    found = lifecycle.find_capture_dirs(tmp_path)

    assert inner in found
    assert outer not in found  # the shell holds no PLY and no frames+colmap of its own


def test_find_capture_dirs_finds_unfinished_capture(tmp_path: Path) -> None:
    capture = tmp_path / "2026-07-01_x"
    (capture / "frames").mkdir(parents=True)
    (capture / "colmap").mkdir()

    assert lifecycle.find_capture_dirs(tmp_path) == [capture]
