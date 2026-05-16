# SPDX-License-Identifier: AGPL-3.0-or-later

"""PLY validation, output copying, and metadata bundling."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import ExportConfig
from .logging import get_logger

logger = get_logger(__name__)

MIN_PLY_BYTES = 1024 * 1024  # 1 MB per spec §9.2 — anything smaller is treated as failure


@dataclass
class ExportResult:
    output_ply: Path
    metadata_path: Path
    size_bytes: int
    duration_s: float


@dataclass
class CaptureMetadata:
    capture_name: str
    source_video: str
    captured_at: str
    frames_extracted: int
    frames_kept: int
    colmap_cameras_registered: int
    colmap_points: int
    training_steps: int
    training_duration_s: float
    output_ply_size_bytes: int

    def to_dict(self) -> dict:
        return asdict(self)


def validate_ply(path: Path) -> bool:
    """Check that the PLY exists, has a valid header, and exceeds the size floor."""
    if not path.exists():
        logger.warning("export.validate.missing", path=str(path))
        return False
    size = path.stat().st_size
    if size < MIN_PLY_BYTES:
        logger.warning("export.validate.too_small", path=str(path), size=size)
        return False
    # Header sniff — first 3 bytes should be 'ply' (ASCII or binary)
    try:
        with path.open("rb") as f:
            head = f.read(3)
        if head != b"ply":
            logger.warning("export.validate.bad_header", path=str(path), head=head.hex())
            return False
    except OSError as e:
        logger.warning("export.validate.read_failed", path=str(path), error=str(e))
        return False
    return True


def export_capture(
    capture_dir: Path,
    source_ply: Path,
    cfg: ExportConfig,
    *,
    capture_name: str,
    source_video: Path,
    frames_extracted: int,
    frames_kept: int,
    colmap_cameras_registered: int,
    colmap_points: int,
    training_steps: int,
    training_duration_s: float,
) -> ExportResult:
    t0 = time.monotonic()
    out_dir = capture_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    target_ply = out_dir / "scene.ply"
    shutil.copy2(source_ply, target_ply)

    if not validate_ply(target_ply):
        raise RuntimeError(f"PLY validation failed for {target_ply}")

    meta = CaptureMetadata(
        capture_name=capture_name,
        source_video=str(source_video),
        captured_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        frames_extracted=frames_extracted,
        frames_kept=frames_kept,
        colmap_cameras_registered=colmap_cameras_registered,
        colmap_points=colmap_points,
        training_steps=training_steps,
        training_duration_s=training_duration_s,
        output_ply_size_bytes=target_ply.stat().st_size,
    )
    metadata_path = out_dir / "metadata.json"
    metadata_path.write_text(json.dumps(meta.to_dict(), indent=2), encoding="utf-8")

    if cfg.copy_to_outputs:
        outputs_dir = cfg.outputs_dir / capture_name
        outputs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_ply, outputs_dir / "scene.ply")
        shutil.copy2(metadata_path, outputs_dir / "metadata.json")
        logger.info("export.copied_to_outputs", dest=str(outputs_dir))

    result = ExportResult(
        output_ply=target_ply,
        metadata_path=metadata_path,
        size_bytes=target_ply.stat().st_size,
        duration_s=time.monotonic() - t0,
    )
    logger.info(
        "export.done",
        output_ply=str(result.output_ply),
        size_bytes=result.size_bytes,
        duration_s=result.duration_s,
    )
    return result
