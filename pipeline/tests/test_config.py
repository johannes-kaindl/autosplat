# SPDX-License-Identifier: AGPL-3.0-or-later

"""Config loading, merging, and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from autosplat.config import (
    PACKAGED_DEFAULT_CONFIG,
    Config,
    _deep_merge,
    apply_override,
    dump_default_config,
    load_config,
)


def test_packaged_default_config_exists() -> None:
    assert PACKAGED_DEFAULT_CONFIG.exists(), "Default config must ship with the repo"


def test_load_default_config_parses_cleanly() -> None:
    cfg = load_config(include_xdg=False)
    assert isinstance(cfg, Config)
    assert cfg.preprocess.target_frames == 250
    assert cfg.colmap.matcher == "sequential"
    assert cfg.brush.max_steps == 30000
    assert cfg.viewer.target == "supersplat"
    assert cfg.obsidian.enabled is False


def test_paths_expand_tilde() -> None:
    cfg = load_config(include_xdg=False)
    assert "~" not in str(cfg.paths.captures_dir)
    assert "~" not in str(cfg.paths.brush_binary)


def test_user_override_wins(tmp_path: Path) -> None:
    user = tmp_path / "u.toml"
    user.write_text(
        """
[preprocess]
target_frames = 99
""",
        encoding="utf-8",
    )
    cfg = load_config(user_config_path=user, include_xdg=False)
    assert cfg.preprocess.target_frames == 99
    # Untouched fields keep defaults
    assert cfg.preprocess.blur_threshold == 100.0


def test_invalid_matcher_rejected(tmp_path: Path) -> None:
    user = tmp_path / "u.toml"
    user.write_text(
        """
[colmap]
matcher = "telepathy"
""",
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        load_config(user_config_path=user, include_xdg=False)


def test_deep_merge_nested() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    over = {"a": {"y": 20, "z": 30}}
    assert _deep_merge(base, over) == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3}


def test_dump_default_config(tmp_path: Path) -> None:
    target = tmp_path / "out.toml"
    dump_default_config(target)
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("# auto-splat-pipeline")


# ─── Phase-3 sections + override helper ─────────────────────────────────────


def test_default_includes_phase3_sections() -> None:
    cfg = load_config(include_xdg=False)
    assert cfg.quality_gate.enabled is True
    assert cfg.quality_gate.min_camera_ratio == 0.5
    assert cfg.quality_gate.min_points == 5000
    assert cfg.retry.enabled is True
    assert cfg.retry.max_retries == 3
    assert cfg.status.max_history == 50


def test_apply_override_swaps_matcher() -> None:
    cfg = load_config(include_xdg=False)
    assert cfg.colmap.matcher == "sequential"
    new_cfg = apply_override(cfg, {"colmap": {"matcher": "exhaustive"}})
    assert new_cfg.colmap.matcher == "exhaustive"
    # Unrelated values untouched
    assert new_cfg.brush.max_steps == cfg.brush.max_steps
    # Original cfg unmutated
    assert cfg.colmap.matcher == "sequential"


def test_apply_override_empty_returns_original_cfg() -> None:
    cfg = load_config(include_xdg=False)
    assert apply_override(cfg, {}) is cfg


def test_apply_override_validates_invalid_matcher() -> None:
    import pytest

    cfg = load_config(include_xdg=False)
    with pytest.raises(Exception):
        apply_override(cfg, {"colmap": {"matcher": "telepathy"}})


def test_phase3_config_loads_old_toml_without_sections(tmp_path: Path) -> None:
    """A pre-Phase-3 user config (no [quality_gate]/[retry]/[status]) still loads
    — the missing sections fall back to packaged defaults via the merge."""
    user = tmp_path / "u.toml"
    user.write_text(
        """
[brush]
max_steps = 1000
""",
        encoding="utf-8",
    )
    cfg = load_config(user_config_path=user, include_xdg=False)
    assert cfg.brush.max_steps == 1000
    assert cfg.quality_gate.enabled is True  # came from packaged default
    assert cfg.retry.max_retries == 3


# ─── v1.4 — Auto-Bisection-Rescue config ────────────────────────────────────


def test_default_includes_v14_bisect_fields() -> None:
    cfg = load_config(include_xdg=False)
    assert cfg.retry.bisect_enabled is True
    assert cfg.retry.bisect_min_clip_s == 60.0
    assert cfg.retry.bisect_max_depth == 3


def test_bisect_max_depth_rejects_zero(tmp_path: Path) -> None:
    user = tmp_path / "u.toml"
    user.write_text(
        """
[retry]
bisect_max_depth = 0
""",
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        load_config(user_config_path=user, include_xdg=False)


def test_bisect_min_clip_s_rejects_too_small(tmp_path: Path) -> None:
    user = tmp_path / "u.toml"
    user.write_text(
        """
[retry]
bisect_min_clip_s = 5.0
""",
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        load_config(user_config_path=user, include_xdg=False)


def test_apply_override_can_disable_bisect() -> None:
    cfg = load_config(include_xdg=False)
    new_cfg = apply_override(cfg, {"retry": {"bisect_enabled": False}})
    assert new_cfg.retry.bisect_enabled is False
    # Other retry fields untouched
    assert new_cfg.retry.max_retries == cfg.retry.max_retries
