# SPDX-License-Identifier: AGPL-3.0-or-later

"""Reclaim disk space held by a finished capture's working dirs.

Executor only — WHAT may be reclaimed is decided by `lifecycle`, so the CLI,
the WebUI and the grace sweep cannot hold three different opinions.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from autosplat import lifecycle
from autosplat.logging import get_logger

logger = get_logger(__name__)

# Backwards-compatible alias — lifecycle owns the list now.
INTERMEDIATE_SUBDIRS = lifecycle.RECLAIMABLE_SUBDIRS


class NotExported(Exception):
    """Raised when a capture hasn't finished exporting yet."""


@dataclass
class PruneResult:
    removed: list[Path]
    bytes_reclaimed: int
    failed: list[Path] = field(default_factory=list)


def is_exported(capture_dir: Path) -> bool:
    return lifecycle.find_ply(capture_dir) is not None


def prunable_targets(capture_dir: Path) -> list[Path]:
    return lifecycle.reclaimable_targets(capture_dir)


def prune_intermediates(capture_dir: Path, *, dry_run: bool = False) -> PruneResult:
    """Delete the working dirs of a capture that finished exporting.

    Raises `NotExported` if no PLY exists — an unfinished capture still needs
    these for `autosplat resume`, and a failed one needs them for diagnosis.

    Partial failures are reported rather than raised: unreclaimed space is
    cosmetic, and because targets are derived from the filesystem the next
    call simply retries whatever is still there.
    """
    if not is_exported(capture_dir):
        raise NotExported(capture_dir)

    targets = prunable_targets(capture_dir)
    removed: list[Path] = []
    failed: list[Path] = []
    total_bytes = 0

    for target in targets:
        size = lifecycle.bytes_in([target])
        if dry_run:
            removed.append(target)
            total_bytes += size
            continue
        try:
            shutil.rmtree(target)
        except OSError as e:
            logger.error("cleanup.prune_failed", target=str(target), error=str(e))
            failed.append(target)
            continue
        removed.append(target)
        total_bytes += size

    return PruneResult(removed=removed, bytes_reclaimed=total_bytes, failed=failed)


def sweep_expired(
    captures_dir: Path,
    *,
    grace_days: int,
    now: datetime,
) -> list[PruneResult]:
    """Reclaim captures whose unreviewed grace period has run out.

    Never raises: a failure on one capture must not stop the sweep, and the
    sweep must never prevent the WebUI/app from starting.
    """
    results: list[PruneResult] = []
    if grace_days <= 0:
        return results

    try:
        capture_dirs = lifecycle.find_capture_dirs(captures_dir)
    except OSError as e:
        logger.error(
            "cleanup.sweep_enum_failed",
            captures_dir=str(captures_dir),
            error=str(e),
        )
        return results

    for capture_dir in capture_dirs:
        try:
            state = lifecycle.inspect(capture_dir, now=now, grace_days=grace_days)
            if not state.reclaimable:
                continue
            result = prune_intermediates(capture_dir)
        except Exception as e:  # noqa: BLE001,RUF100
            logger.error("cleanup.sweep_failed", capture=str(capture_dir), error=str(e))
            continue
        logger.info(
            "cleanup.sweep_reclaimed",
            capture=capture_dir.name,
            bytes_reclaimed=result.bytes_reclaimed,
        )
        results.append(result)
    return results
