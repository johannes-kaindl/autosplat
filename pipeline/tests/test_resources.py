# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from autosplat import resources


def test_repo_checkout_resolves_relative_to_repo_root() -> None:
    # resources.py → autosplat → src → pipeline → repo root
    assert resources.bundled_path("embed") == resources.REPO_ROOT / "embed"
    assert (resources.REPO_ROOT / "embed" / "index.html").is_file()


def test_frozen_bundle_resolves_against_meipass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resources.bundled_path("supersplat") == tmp_path / "supersplat"


def test_name_must_be_a_single_segment() -> None:
    # A resource "name" is a bundle top-level dir, never a path — silently
    # accepting "../.." would resolve outside the bundle.
    with pytest.raises(ValueError):
        resources.bundled_path("../etc")


def test_viewer_status_names_all_three_roles() -> None:
    from autosplat.config import load_config

    statuses = resources.viewer_status(load_config(include_xdg=False))

    assert [s.name for s in statuses] == ["supersplat", "embed", "viewer"]
    roles = " ".join(s.role for s in statuses)
    assert "clean up" in roles and "share" in roles and "walk" in roles


def test_viewer_status_reports_absence(tmp_path: Path) -> None:
    """The defect this exists for: a missing viewer used to be invisible."""
    from autosplat.config import load_config

    cfg = load_config(include_xdg=False)
    cfg.viewer.supersplat_dist_path = tmp_path / "nope"

    supersplat = next(s for s in resources.viewer_status(cfg) if s.name == "supersplat")
    assert supersplat.present is False


def test_supersplat_default_does_not_depend_on_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The shipped app had no review viewer because this default was
    cwd-relative and a Finder launch has no meaningful cwd."""
    from autosplat.config import load_config

    monkeypatch.chdir(tmp_path)
    cfg = load_config(include_xdg=False)
    assert cfg.viewer.supersplat_dist_path.is_absolute()
    assert cfg.share.embed_src_path.is_absolute()
