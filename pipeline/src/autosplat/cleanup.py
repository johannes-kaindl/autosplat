# SPDX-License-Identifier: AGPL-3.0-or-later

"""Reclaim disk space held by a finished capture's SfM/training working dirs.

Shared core for `autosplat cleanup-intermediates` (CLI) and the WebUI's
per-capture "free up space" action.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

INTERMEDIATE_SUBDIRS = ("frames", "colmap", "training")


class NotExported(Exception):
    """Raised when a capture hasn't finished exporting yet."""


@dataclass
class PruneResult:
    removed: list[Path]
    bytes_reclaimed: int


def is_exported(capture_dir: Path) -> bool:
    return (capture_dir / "output" / "scene.ply").exists() or (capture_dir / "scene.ply").exists()


def prunable_targets(capture_dir: Path) -> list[Path]:
    return [capture_dir / sub for sub in INTERMEDIATE_SUBDIRS if (capture_dir / sub).is_dir()]


def _bytes_in(targets: list[Path]) -> int:
    total = 0
    for target in targets:
        for p in target.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    return total


def prune_intermediates(capture_dir: Path, *, dry_run: bool = False) -> PruneResult:
    """Delete frames/, colmap/, training/ for a capture that finished exporting.

    Raises `NotExported` if `output/scene.ply` (or legacy `scene.ply`) is
    missing — an unfinished capture still needs these for `autosplat resume`.
    """
    if not is_exported(capture_dir):
        raise NotExported(capture_dir)

    targets = prunable_targets(capture_dir)
    total_bytes = _bytes_in(targets)

    if not dry_run:
        for target in targets:
            shutil.rmtree(target)

    return PruneResult(removed=targets, bytes_reclaimed=total_bytes)
