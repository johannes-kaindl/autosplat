# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for COLMAP command builders. No real COLMAP invoked."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from autosplat.config import ColmapConfig
from autosplat.sfm import (
    _parse_mapper_stats,
    build_feature_extractor_command,
    build_mapper_command,
    build_matcher_command,
)


@pytest.fixture
def cfg() -> ColmapConfig:
    return ColmapConfig(matcher="sequential", quality="medium", single_camera=True)


def test_feature_extractor_command(tmp_path: Path, cfg: ColmapConfig) -> None:
    cmd = build_feature_extractor_command(tmp_path / "db.db", tmp_path / "frames", cfg)
    assert cmd[0] == "colmap"
    assert "feature_extractor" in cmd
    assert "--database_path" in cmd
    assert "--ImageReader.single_camera" in cmd
    # medium preset
    idx = cmd.index("--SiftExtraction.max_num_features")
    assert cmd[idx + 1] == "8192"
    # COLMAP 4.0 surface: max_image_size belongs to FeatureExtraction, not SiftExtraction
    assert "--FeatureExtraction.max_image_size" in cmd
    # GPU off — Homebrew COLMAP is built without CUDA
    idx_gpu = cmd.index("--FeatureExtraction.use_gpu")
    assert cmd[idx_gpu + 1] == "0"


def test_matcher_command_sequential(tmp_path: Path, cfg: ColmapConfig) -> None:
    cmd = build_matcher_command(tmp_path / "db.db", cfg)
    assert "sequential_matcher" in cmd


def test_matcher_command_exhaustive(tmp_path: Path) -> None:
    cfg = ColmapConfig(matcher="exhaustive", quality="high", single_camera=False)
    cmd = build_matcher_command(tmp_path / "db.db", cfg)
    assert "exhaustive_matcher" in cmd


def test_mapper_command(tmp_path: Path) -> None:
    cmd = build_mapper_command(tmp_path / "db.db", tmp_path / "frames", tmp_path / "sparse")
    assert cmd[0] == "colmap"
    assert "mapper" in cmd
    assert str(tmp_path / "sparse") in cmd


def test_single_camera_flag_off(tmp_path: Path) -> None:
    cfg = ColmapConfig(matcher="sequential", quality="low", single_camera=False)
    cmd = build_feature_extractor_command(tmp_path / "db.db", tmp_path / "frames", cfg)
    idx = cmd.index("--ImageReader.single_camera")
    assert cmd[idx + 1] == "0"


def test_parse_mapper_stats_returns_zero_when_no_sparse(tmp_path: Path) -> None:
    assert _parse_mapper_stats(tmp_path / "missing") == (0, 0)


def test_parse_mapper_stats_binary(tmp_path: Path) -> None:
    """COLMAP 4.0+ defaults: images.bin / points3D.bin with uint64 count header."""
    out = tmp_path / "sparse" / "0"
    out.mkdir(parents=True)
    (out / "images.bin").write_bytes(struct.pack("<Q", 42) + b"\0" * 16)
    (out / "points3D.bin").write_bytes(struct.pack("<Q", 1234) + b"\0" * 16)
    assert _parse_mapper_stats(tmp_path / "sparse") == (42, 1234)


def test_parse_mapper_stats_text(tmp_path: Path) -> None:
    """Older COLMAP / --Mapper.bin 0: images.txt and points3D.txt."""
    out = tmp_path / "sparse" / "0"
    out.mkdir(parents=True)
    # 3 images = 6 non-comment lines (metadata line + points line per image)
    (out / "images.txt").write_text(
        "# header\n"
        "1 0 0 0 0 0 0 0 1 a.jpg\n"
        "10 20 30\n"
        "2 0 0 0 0 0 0 0 1 b.jpg\n"
        "10 20 30\n"
        "3 0 0 0 0 0 0 0 1 c.jpg\n"
        "10 20 30\n",
        encoding="utf-8",
    )
    (out / "points3D.txt").write_text(
        "# header\n1 x y z r g b err 1 2\n2 x y z r g b err 1 2\n",
        encoding="utf-8",
    )
    assert _parse_mapper_stats(tmp_path / "sparse") == (3, 2)
