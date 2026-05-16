# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared test fixtures for the autosplat test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def packaged_default_config(repo_root: Path) -> Path:
    return repo_root / "config" / "default.toml"


@pytest.fixture
def tmp_capture_dir(tmp_path: Path) -> Path:
    d = tmp_path / "capture"
    d.mkdir()
    return d
