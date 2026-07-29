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
    (capture / "rescue" / "probes").mkdir(parents=True)
    (capture / "brush_dataset").mkdir()
    (capture / "colmap" / "db.bin").write_bytes(b"x" * 100)
    _mark_reviewed(capture)

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "reviewed"
    assert {p.name for p in result.reclaimable} == {"colmap", "probes", "brush_dataset"}
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


def test_bytes_in_tolerates_file_vanishing_mid_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Finding 2 (task 7 review): the grace sweep can rmtree a tree while a
    # concurrent request is sizing it via bytes_in. Simulate that race by
    # making stat() raise for one specific file mid-walk.
    target = tmp_path / "colmap"
    target.mkdir()
    (target / "keep.bin").write_bytes(b"x" * 30)
    (target / "gone.bin").write_bytes(b"y" * 999)

    original_stat = Path.stat

    def flaky_stat(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "gone.bin":
            raise FileNotFoundError(self)
        return original_stat(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "stat", flaky_stat)

    total = lifecycle.bytes_in([target])

    assert total == 30


def test_bytes_in_tolerates_target_removed_entirely(tmp_path: Path) -> None:
    import shutil

    target = tmp_path / "colmap"
    target.mkdir()
    (target / "blob").write_bytes(b"x" * 10)
    shutil.rmtree(target)  # simulate a concurrent reclaim finishing first

    assert lifecycle.bytes_in([target]) == 0


def test_recently_active_true_when_reclaimable_target_touched_recently(tmp_path: Path) -> None:
    import os

    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    blob = capture / "colmap" / "blob"
    blob.write_bytes(b"x")
    recent = (NOW - timedelta(seconds=5)).timestamp()
    os.utime(blob, (recent, recent))

    assert lifecycle.recently_active(capture, now=NOW) is True


def test_recently_active_true_for_recent_pipeline_log(tmp_path: Path) -> None:
    import os

    capture = _make_capture(tmp_path, "2026-07-01_x")
    log = capture / "pipeline.log"
    log.write_text("{}", encoding="utf-8")
    recent = (NOW - timedelta(seconds=5)).timestamp()
    os.utime(log, (recent, recent))

    assert lifecycle.recently_active(capture, now=NOW) is True


def test_recently_active_false_when_everything_aged(tmp_path: Path) -> None:
    import os

    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    blob = capture / "colmap" / "blob"
    blob.write_bytes(b"x")
    old = (NOW - timedelta(days=40)).timestamp()
    os.utime(blob, (old, old))

    assert lifecycle.recently_active(capture, now=NOW) is False


def test_recently_active_false_when_nothing_to_check(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")

    assert lifecycle.recently_active(capture, now=NOW) is False


def test_recently_active_tolerates_stat_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    blob = capture / "colmap" / "blob"
    blob.write_bytes(b"x")
    recent = (NOW - timedelta(seconds=5)).timestamp()
    os.utime(blob, (recent, recent))

    original_stat = Path.stat

    def flaky_stat(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "blob":
            raise FileNotFoundError(self)
        return original_stat(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "stat", flaky_stat)

    # The one entry with a recent mtime is unreadable — must not raise, and
    # with nothing else to go on, must not be treated as active.
    assert lifecycle.recently_active(capture, now=NOW) is False


def test_rescue_clips_are_kept_while_probes_are_reclaimed(tmp_path: Path) -> None:
    """C1: `rescue/` as a whole was reclaimable, which destroyed
    `rescue/clips/*.mp4` — the leaf-clip sources a bisected capture records in
    pipeline.log as its origin. Without them `add-video`/`resume` fail with
    "cannot extend a capture whose origin is unknown", recoverable only by
    re-running bisection (5h36m on the documented max_strasse case) against an
    original video that may no longer exist. `cleanup-rescue` already keeps
    them by default; the lifecycle must not silently override that.
    """
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "rescue" / "clips").mkdir(parents=True)
    (capture / "rescue" / "clips" / "0.mp4").write_bytes(b"m" * 40)
    (capture / "rescue" / "probes" / "0" / "colmap").mkdir(parents=True)
    (capture / "rescue" / "probes" / "0" / "colmap" / "db").write_bytes(b"p" * 60)
    _mark_reviewed(capture)

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert [p.relative_to(capture).as_posix() for p in result.reclaimable] == ["rescue/probes"]
    assert result.reclaimable_bytes == 60


def test_reclaimable_targets_withholds_a_target_burying_an_export(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    nested = capture / "rescue" / "probes" / "probe_0" / "output"
    nested.mkdir(parents=True)
    (nested / "scene.ply").write_bytes(b"ply\n")

    assert [p.name for p in lifecycle.reclaimable_targets(capture)] == ["colmap"]
    assert [p.name for p in lifecycle.protected_targets(capture)] == ["probes"]


def test_loose_ply_directly_in_a_target_does_not_protect_it(tmp_path: Path) -> None:
    """A Brush checkpoint `export.py` already copied to `output/scene.ply` is
    a duplicate, not a nested capture — protecting it hid 1,8 GB on the real
    tree and made migrate-storage disagree with the automatic paths."""
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "training").mkdir()
    (capture / "training" / "scene.ply").write_bytes(b"ply\n")

    assert [p.name for p in lifecycle.reclaimable_targets(capture)] == ["training"]
    assert lifecycle.protected_targets(capture) == []


def test_holds_exported_result_tolerates_unreadable_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable directory must not abort a `migrate-storage` preview (or
    the dashboard's per-capture sizing) with a traceback — the same OSError
    tolerance `bytes_in` and `recently_active` already have."""
    target = tmp_path / "rescue" / "probes"
    (target / "probe_0").mkdir(parents=True)

    def exploding_is_dir(self: Path) -> bool:
        raise PermissionError(self)

    monkeypatch.setattr(Path, "is_dir", exploding_is_dir)

    assert lifecycle.holds_exported_result(target) is False
