# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI `autosplat migrate-storage` — bring the existing captures/ + outputs/
backlog onto the lifecycle retention policy.

Fixture note: files are backdated (`_backdate`) well past the
`recently_active` window (1h) whenever a test expects an actual reclaim.
Without that, every freshly-written test fixture would look like an
in-flight `add-video`/`resume` run and `--apply` would (correctly) refuse to
touch it — see `test_apply_skips_recently_active_capture` below, which
relies on exactly that guard by deliberately leaving mtimes fresh.

Review note (task-8 fix pass): an `outputs/<name>` entry is reclaimed ONLY
when a capture of that name still exists AND that capture has its own
exported PLY. An "orphaned" entry (no capture of that name at all) is the
last surviving copy of a scene and is NEVER deleted, regardless of --apply —
see `test_orphaned_outputs_dir_is_never_deleted`, which replaces the
original (incorrect) brief test asserting the orphan got deleted.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autosplat.cli import EXIT_USER_ERROR, app

runner = CliRunner()

_OLD_ENOUGH_S = 2 * 3600  # comfortably past recently_active's 1h default window


def _backdate(path: Path, seconds_ago: float = _OLD_ENOUGH_S) -> None:
    """Push every file/dir under (and including) `path` into the past so
    `lifecycle.recently_active` does not mistake a fresh test fixture for an
    in-flight run."""
    ts = time.time() - seconds_ago
    for p in [path, *path.rglob("*")]:
        os.utime(p, (ts, ts))


def _snapshot(root: Path) -> list[tuple[str, int, float]]:
    """(relative path, size, mtime) for every file/dir under `root`.

    Used instead of a bytes-only total so the "dry run changes nothing" test
    would also notice a removed empty directory, a newly created file, or an
    mtime change — none of which a size-sum would catch.
    """
    if not root.exists():
        return []
    return sorted(
        (str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime) for p in root.rglob("*")
    )


def _legacy_tree(root: Path) -> Path:
    """Mirrors the real backlog: a nested pre-Phase-9 capture with a PLY."""
    captures = root / "captures"
    inner = captures / "2026-05-25_max_strasse_rescue" / "2026-05-25_A_vor1"
    (inner / "output").mkdir(parents=True)
    (inner / "output" / "scene.ply").write_bytes(b"ply\nend_header\n")
    for sub in ("frames", "colmap", "training"):
        (inner / sub).mkdir()
        (inner / sub / "blob").write_bytes(b"x" * 100)
    _backdate(captures)
    return captures


def _config_for(captures: Path, tmp_path: Path, outputs: Path | None = None) -> Path:
    cfg = tmp_path / "config.toml"
    outputs = outputs if outputs is not None else tmp_path / "outputs"
    cfg.write_text(
        f'[paths]\ncaptures_dir = "{captures}"\n\n[export]\noutputs_dir = "{outputs}"\n',
        encoding="utf-8",
    )
    return cfg


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    captures = _legacy_tree(tmp_path)
    outputs = tmp_path / "outputs"
    (outputs / "2026-05-14_orphan").mkdir(parents=True)
    (outputs / "2026-05-14_orphan" / "scene.ply").write_bytes(b"x" * 500)
    _backdate(outputs)
    cfg = _config_for(captures, tmp_path, outputs)
    before_captures = _snapshot(captures)
    before_outputs = _snapshot(outputs)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert result.exit_code == 0
    assert _snapshot(captures) == before_captures
    assert _snapshot(outputs) == before_outputs
    assert "2026-05-25_A_vor1" in result.stdout


def test_apply_reclaims_nested_legacy_capture(tmp_path: Path) -> None:
    captures = _legacy_tree(tmp_path)
    cfg = _config_for(captures, tmp_path)
    inner = captures / "2026-05-25_max_strasse_rescue" / "2026-05-25_A_vor1"

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code == 0
    assert not (inner / "colmap").exists()
    assert not (inner / "training").exists()
    assert (inner / "output" / "scene.ply").exists()


def test_never_touches_a_reclaimable_dir_holding_a_nested_ply(tmp_path: Path) -> None:
    """Constructed hazard: `rescue/` looks like an ordinary reclaimable
    subdir of `2026-07-01_x`, but a probe buried inside it holds its own
    exported PLY. `find_capture_dirs` deliberately does not surface that
    nested PLY as a separate capture (recursion stops once `2026-07-01_x`
    itself is recognised as a capture) — so the only thing that can protect
    it is treating any target that contains a PLY anywhere within it as
    off-limits, in its entirety.

    This replaces the brief's original test, which never actually exercised
    the guard: its `scene.ply` sat under a `rescue/` with no sibling capture
    dir at all, so `find_capture_dirs` never returned anything and the loop
    body never ran. `colmap/`, which holds no PLY, must still be reclaimed
    normally alongside it — proving the fix is a targeted filter, not a
    blanket refusal to touch the capture.
    """
    captures = tmp_path / "captures"
    capture = captures / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\nend_header\n")
    nested_ply = capture / "rescue" / "probe_0" / "output" / "scene.ply"
    nested_ply.parent.mkdir(parents=True)
    nested_ply.write_bytes(b"ply\nend_header\n")
    (capture / "colmap").mkdir()
    (capture / "colmap" / "blob").write_bytes(b"x" * 100)
    _backdate(captures)
    cfg = _config_for(captures, tmp_path)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code == 0
    assert nested_ply.exists()
    assert (capture / "rescue").exists()
    assert not (capture / "colmap").exists()


def test_orphaned_outputs_dir_is_never_deleted(tmp_path: Path) -> None:
    """No capture named `2026-05-14_jay_1` exists anywhere under captures/ —
    this outputs/ entry is the LAST surviving copy of that scene, not a
    redundant duplicate. --apply must never delete it, no matter how old it
    is or how the preview labels it."""
    captures = _legacy_tree(tmp_path)
    outputs = tmp_path / "outputs"
    (outputs / "2026-05-14_jay_1").mkdir(parents=True)
    (outputs / "2026-05-14_jay_1" / "scene.ply").write_bytes(b"x" * 500)
    _backdate(outputs)
    cfg = _config_for(captures, tmp_path, outputs)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])
    assert "2026-05-14_jay_1" in result.stdout
    assert "orphaned" in result.stdout.lower()
    assert (outputs / "2026-05-14_jay_1").exists()  # dry run

    applied = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert applied.exit_code == 0
    assert (outputs / "2026-05-14_jay_1").exists()  # still there — orphans are never deleted


def test_duplicate_outputs_dir_is_reclaimed_when_capture_has_ply(tmp_path: Path) -> None:
    """A genuine duplicate: outputs/2026-05-25_A_vor1 mirrors a capture that
    still exists AND has its own exported PLY. This one is safe to remove."""
    captures = _legacy_tree(tmp_path)
    outputs = tmp_path / "outputs"
    dup = outputs / "2026-05-25_A_vor1"
    dup.mkdir(parents=True)
    (dup / "scene.ply").write_bytes(b"x" * 500)
    _backdate(outputs)
    cfg = _config_for(captures, tmp_path, outputs)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code == 0
    assert not dup.exists()


def test_duplicate_outputs_dir_is_kept_when_capture_has_no_ply(tmp_path: Path) -> None:
    """Name matches a capture, but that capture hasn't exported its own PLY
    yet (still mid-run/failed) — the outputs/ copy may be the only PLY for
    this name and must be kept, exactly like an orphan."""
    captures = tmp_path / "captures"
    capture = captures / "2026-07-10_unfinished"
    (capture / "frames").mkdir(parents=True)
    (capture / "colmap").mkdir()
    _backdate(captures)
    outputs = tmp_path / "outputs"
    dup = outputs / "2026-07-10_unfinished"
    dup.mkdir(parents=True)
    (dup / "scene.ply").write_bytes(b"x" * 500)
    _backdate(outputs)
    cfg = _config_for(captures, tmp_path, outputs)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code == 0
    assert dup.exists()


def test_apply_skips_recently_active_capture(tmp_path: Path) -> None:
    """Task 7's `lifecycle.recently_active` guard: a capture that is
    otherwise fully reclaimable but has a just-touched file under colmap/
    must survive --apply — it looks like an in-flight add-video/resume
    rebuild, not a finished, safely-reclaimable capture."""
    captures = tmp_path / "captures"
    capture = captures / "2026-06-01_rebuilding"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\nend_header\n")
    (capture / "colmap").mkdir()
    (capture / "colmap" / "blob").write_bytes(b"x" * 100)
    # Backdate everything except the one file that simulates the in-flight
    # write — leaving its mtime at "now" so recently_active flags it.
    _backdate(capture)
    live_blob = capture / "colmap" / "blob"
    now = time.time()
    os.utime(live_blob, (now, now))
    cfg = _config_for(captures, tmp_path)

    preview = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])
    assert preview.exit_code == 0
    assert "2026-06-01_rebuilding" in preview.stdout
    assert "active" in preview.stdout.lower()

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code == 0
    assert (capture / "colmap").exists()
    assert (capture / "colmap" / "blob").exists()


def test_failed_capture_listed_as_kept_not_silently_omitted(tmp_path: Path) -> None:
    """A capture with no exported PLY (failed/mid-run) must still show up in
    the preview, labelled as kept — not just vanish from the table with no
    explanation."""
    captures = tmp_path / "captures"
    capture = captures / "2026-05-22_max_strasse"
    (capture / "frames").mkdir(parents=True)
    (capture / "colmap").mkdir()
    (capture / "colmap" / "blob").write_bytes(b"x" * 100)
    _backdate(captures)
    cfg = _config_for(captures, tmp_path)

    preview = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert preview.exit_code == 0
    assert "2026-05-22_max_strasse" in preview.stdout
    assert "failed" in preview.stdout.lower()

    applied = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert applied.exit_code == 0
    assert (capture / "colmap").exists()


def test_reports_reclaimed_skipped_and_failed_counts(tmp_path: Path) -> None:
    """The closing --apply line must show all three buckets from the spec —
    reclaimed / skipped / failed — not just a bytes figure."""
    captures = _legacy_tree(tmp_path)
    # Add a capture that will be skipped (recently active).
    active = captures / "2026-06-01_rebuilding"
    (active / "output").mkdir(parents=True)
    (active / "output" / "scene.ply").write_bytes(b"ply\nend_header\n")
    (active / "colmap").mkdir()
    live_blob = active / "colmap" / "blob"
    live_blob.write_bytes(b"x" * 100)
    now = time.time()
    os.utime(live_blob, (now, now))
    cfg = _config_for(captures, tmp_path)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code == 0
    assert "skipped" in result.stdout.lower()
    assert "failure" in result.stdout.lower()
    assert "1 skipped" in result.stdout


def test_apply_reports_failure_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-target rmtree failure must surface in the closing report and
    make the process exit non-zero — not silently print "0 failure(s)" while
    a directory that should have been removed is still sitting there."""
    captures = _legacy_tree(tmp_path)
    cfg = _config_for(captures, tmp_path)

    original_rmtree = shutil.rmtree

    def rmtree_with_failure(path: str | Path, *args: object, **kwargs: object) -> None:
        if Path(path).name == "colmap":
            raise OSError("Permission denied")
        original_rmtree(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(shutil, "rmtree", rmtree_with_failure)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code != 0
    assert "failure" in result.stdout.lower()
    inner = captures / "2026-05-25_max_strasse_rescue" / "2026-05-25_A_vor1"
    assert (inner / "colmap").exists()  # removal failed — left in place
    assert not (inner / "training").exists()  # other targets still reclaimed


# --- CRITICAL 2: outputs_dir/captures_dir containment guard -----------------


def test_refuses_when_outputs_dir_equals_captures_dir(tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    cfg = _config_for(captures, tmp_path, outputs=captures)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert result.exit_code == EXIT_USER_ERROR
    assert "Refusing" in result.output


def test_refuses_when_captures_dir_is_inside_outputs_dir(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs_root"
    captures = outputs / "captures"
    captures.mkdir(parents=True)
    cfg = _config_for(captures, tmp_path, outputs=outputs)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert result.exit_code == EXIT_USER_ERROR
    assert "Refusing" in result.output


def test_refuses_when_outputs_dir_is_home_directory(tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    cfg = _config_for(captures, tmp_path, outputs=Path.home())

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert result.exit_code == EXIT_USER_ERROR
    assert "Refusing" in result.output


def test_refuses_when_outputs_dir_is_filesystem_root(tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    root = Path(tmp_path.anchor)  # e.g. "/" — a real filesystem root, portable
    cfg = _config_for(captures, tmp_path, outputs=root)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert result.exit_code == EXIT_USER_ERROR
    assert "Refusing" in result.output


def test_bad_config_path_is_a_clean_error_not_a_traceback(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["migrate-storage", "--config", str(tmp_path / "does-not-exist.toml")]
    )

    assert result.exit_code == EXIT_USER_ERROR
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "config" in result.output.lower()
