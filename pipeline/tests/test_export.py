# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for PLY-validation."""

from __future__ import annotations

from pathlib import Path

from autosplat.config import load_config
from autosplat.export import MIN_PLY_BYTES, validate_ply


def _write_ply(path: Path, *, size: int, header_ok: bool = True) -> None:
    head = b"ply\n" if header_ok else b"xxx\n"
    path.write_bytes(head + b"\0" * max(0, size - len(head)))


def test_validate_ply_happy(tmp_path: Path) -> None:
    p = tmp_path / "scene.ply"
    _write_ply(p, size=MIN_PLY_BYTES + 1)
    assert validate_ply(p) is True


def test_validate_ply_too_small(tmp_path: Path) -> None:
    p = tmp_path / "scene.ply"
    _write_ply(p, size=100)
    assert validate_ply(p) is False


def test_validate_ply_bad_header(tmp_path: Path) -> None:
    p = tmp_path / "scene.ply"
    _write_ply(p, size=MIN_PLY_BYTES + 1, header_ok=False)
    assert validate_ply(p) is False


def test_validate_ply_missing(tmp_path: Path) -> None:
    assert validate_ply(tmp_path / "nope.ply") is False


def test_export_does_not_write_outputs_dir_by_default(tmp_path: Path) -> None:
    # outputs/ held 8,8 GB of second copies, 10 of them orphaned.
    cfg = load_config(include_xdg=False)

    assert cfg.export.copy_to_outputs is False
