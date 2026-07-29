# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI `autosplat migrate-storage` — bring the existing captures/ + outputs/
backlog onto the lifecycle retention policy.

Fixture note: files are backdated (`_backdate`) well past the
`recently_active` window (1h) whenever a test expects an actual reclaim.
Without that, every freshly-written test fixture would look like an
in-flight `add-video`/`resume` run and `--apply` would (correctly) refuse to
touch it — see `test_apply_skips_recently_active_capture` below, which
relies on exactly that guard by deliberately leaving mtimes fresh.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from typer.testing import CliRunner

from autosplat.cli import app

runner = CliRunner()

_OLD_ENOUGH_S = 2 * 3600  # comfortably past recently_active's 1h default window


def _backdate(path: Path, seconds_ago: float = _OLD_ENOUGH_S) -> None:
    """Push every file/dir under (and including) `path` into the past so
    `lifecycle.recently_active` does not mistake a fresh test fixture for an
    in-flight run."""
    ts = time.time() - seconds_ago
    for p in [path, *path.rglob("*")]:
        os.utime(p, (ts, ts))


def _total_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


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


def _config_for(captures: Path, tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[paths]\ncaptures_dir = "{captures}"\n\n[export]\noutputs_dir = "{tmp_path / "outputs"}"\n',
        encoding="utf-8",
    )
    return cfg


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    captures = _legacy_tree(tmp_path)
    cfg = _config_for(captures, tmp_path)
    before = _total_bytes(captures)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert result.exit_code == 0
    assert _total_bytes(captures) == before
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


def test_never_touches_a_directory_holding_the_only_ply(tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    # Constructed hazard: the PLY lives INSIDE what looks like an intermediate.
    weird = captures / "2026-07-01_x" / "rescue"
    weird.mkdir(parents=True)
    (weird / "scene.ply").write_bytes(b"ply\nend_header\n")
    _backdate(captures)
    cfg = _config_for(captures, tmp_path)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code == 0
    assert (weird / "scene.ply").exists()


def test_reports_orphaned_outputs_dirs(tmp_path: Path) -> None:
    captures = _legacy_tree(tmp_path)
    outputs = tmp_path / "outputs"
    (outputs / "2026-05-14_jay_1").mkdir(parents=True)
    (outputs / "2026-05-14_jay_1" / "scene.ply").write_bytes(b"x" * 500)
    cfg = _config_for(captures, tmp_path)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert "2026-05-14_jay_1" in result.stdout
    assert (outputs / "2026-05-14_jay_1").exists()  # dry run

    applied = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert applied.exit_code == 0
    assert not (outputs / "2026-05-14_jay_1").exists()


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
