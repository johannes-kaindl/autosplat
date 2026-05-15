"""Structure-from-Motion via COLMAP.

Three stages:
  1. feature_extractor — SIFT features from each frame
  2. matcher — `sequential` (default for video) or `exhaustive`
  3. mapper — sparse reconstruction

Quality presets control feature counts and matcher parameters.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import ColmapConfig
from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class SfmResult:
    workspace: Path
    database_path: Path
    sparse_dir: Path
    cameras_registered: int
    points: int
    duration_s: float


_QUALITY_PRESETS = {
    "low": {"max_image_size": 1200, "max_num_features": 4096},
    "medium": {"max_image_size": 1600, "max_num_features": 8192},
    "high": {"max_image_size": 2400, "max_num_features": 16384},
}


def _run_logged(cmd: list[str]) -> None:
    """Run a subprocess; surface stderr on failure (otherwise it gets swallowed)."""
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.error(
            "sfm.subprocess_failed",
            cmd=cmd,
            returncode=res.returncode,
            stderr=(res.stderr or "")[-2000:],
            stdout=(res.stdout or "")[-2000:],
        )
        raise subprocess.CalledProcessError(
            res.returncode, cmd, output=res.stdout, stderr=res.stderr
        )


def build_feature_extractor_command(
    database: Path,
    images: Path,
    cfg: ColmapConfig,
) -> list[str]:
    """Build the `colmap feature_extractor` command for COLMAP 4.0+.

    Note: `max_image_size` lives under `FeatureExtraction.` (not `SiftExtraction.`)
    in 4.0. We also force `use_gpu=0` because Homebrew's COLMAP is built without
    CUDA and the GPU code path is fragile on Apple Silicon.
    """
    preset = _QUALITY_PRESETS[cfg.quality]
    return [
        "colmap",
        "feature_extractor",
        "--database_path",
        str(database),
        "--image_path",
        str(images),
        "--ImageReader.single_camera",
        "1" if cfg.single_camera else "0",
        "--ImageReader.camera_model",
        "OPENCV",
        "--FeatureExtraction.use_gpu",
        "0",
        "--FeatureExtraction.max_image_size",
        str(preset["max_image_size"]),
        "--SiftExtraction.max_num_features",
        str(preset["max_num_features"]),
    ]


def build_matcher_command(database: Path, cfg: ColmapConfig) -> list[str]:
    matcher_cmd = {
        "sequential": "sequential_matcher",
        "exhaustive": "exhaustive_matcher",
        "spatial": "spatial_matcher",
        "vocab_tree": "vocab_tree_matcher",
    }[cfg.matcher]
    return ["colmap", matcher_cmd, "--database_path", str(database)]


def build_mapper_command(database: Path, images: Path, sparse_dir: Path) -> list[str]:
    return [
        "colmap",
        "mapper",
        "--database_path",
        str(database),
        "--image_path",
        str(images),
        "--output_path",
        str(sparse_dir),
    ]


def _parse_mapper_stats(sparse_dir: Path) -> tuple[int, int]:
    """Return (cameras_registered, points). Best-effort — falls back to 0/0.

    COLMAP 4.0+ writes binary `.bin` files by default; older versions and
    `--Mapper.bin 0` produce text `.txt`. We support both.
    """
    out_dir = sparse_dir / "0"
    if not out_dir.exists():
        return (0, 0)

    cams = _count_images(out_dir)
    pts = _count_points(out_dir)
    return (cams, pts)


def _count_images(out_dir: Path) -> int:
    binary = out_dir / "images.bin"
    if binary.exists():
        return _read_uint64_header(binary)

    text = out_dir / "images.txt"
    if text.exists():
        # COLMAP images.txt: every non-comment line pair is one image; we count
        # half (the metadata lines, not the feature-points lines).
        non_comment = sum(
            1
            for line in text.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        return non_comment // 2

    return 0


def _count_points(out_dir: Path) -> int:
    binary = out_dir / "points3D.bin"
    if binary.exists():
        return _read_uint64_header(binary)

    text = out_dir / "points3D.txt"
    if text.exists():
        return sum(
            1
            for line in text.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    return 0


def _read_uint64_header(path: Path) -> int:
    """COLMAP's binary `.bin` files start with a little-endian uint64 count."""
    import struct

    try:
        with path.open("rb") as f:
            head = f.read(8)
        if len(head) < 8:
            return 0
        return int(struct.unpack("<Q", head)[0])
    except OSError:
        return 0


def run_colmap(
    frames_dir: Path,
    workspace: Path,
    cfg: ColmapConfig,
) -> SfmResult:
    """Full SfM pipeline. Workspace must already exist; will be populated in place."""
    t0 = time.monotonic()
    workspace.mkdir(parents=True, exist_ok=True)

    database = workspace / "database.db"
    sparse_dir = workspace / "sparse"
    sparse_dir.mkdir(exist_ok=True)

    # 1. Feature extraction
    cmd = build_feature_extractor_command(database, frames_dir, cfg)
    logger.info("sfm.feature_extractor.start", cmd=cmd)
    _run_logged(cmd)

    # 2. Matching
    cmd = build_matcher_command(database, cfg)
    logger.info("sfm.matcher.start", matcher=cfg.matcher, cmd=cmd)
    _run_logged(cmd)

    # 3. Mapper
    cmd = build_mapper_command(database, frames_dir, sparse_dir)
    logger.info("sfm.mapper.start", cmd=cmd)
    _run_logged(cmd)

    cameras, points = _parse_mapper_stats(sparse_dir)
    result = SfmResult(
        workspace=workspace,
        database_path=database,
        sparse_dir=sparse_dir,
        cameras_registered=cameras,
        points=points,
        duration_s=time.monotonic() - t0,
    )
    logger.info(
        "sfm.done",
        cameras_registered=result.cameras_registered,
        points=result.points,
        duration_s=result.duration_s,
    )
    return result
