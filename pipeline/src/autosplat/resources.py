# SPDX-License-Identifier: AGPL-3.0-or-later

"""Resolution of resource trees bundled into the frozen app.

One resolver for every asset directory that ships inside AutoSplat.app
(`embed/`, `supersplat/`, `viewer/`). Before this module each caller rolled
its own: `config.py` checked `sys.frozen`, while `webui/app.py` resolved the
SuperSplat dist against `Path.cwd()` — which is meaningless for a Finder
launch, so the shipped app silently had no review viewer at all.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autosplat.config import Config

# resources.py → autosplat → src → pipeline → repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


def bundled_path(name: str) -> Path:
    """Directory of the bundled resource `name`.

    Frozen (PyInstaller) → `sys._MEIPASS/<name>`, where AutoSplat.spec stages
    it. Otherwise the monorepo checkout's `<repo root>/<name>`.

    `name` is a single path segment by contract; anything else would let a
    caller escape the bundle root.
    """
    if "/" in name or name in ("", ".", ".."):
        raise ValueError(f"resource name must be a single path segment, got {name!r}")
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / name  # type: ignore[attr-defined]
    return REPO_ROOT / name


@dataclass(frozen=True)
class ResourceStatus:
    """A bundled viewer, its one job, and whether it is actually there."""

    name: str
    role: str
    path: Path
    present: bool


# The charter of viewer roles (AGENTS.md), as data. The three overlap only on
# plain viewing; each entry's `role` is why it exists. A fourth entry is a
# design decision, not a detail.
_VIEWER_ROLES: tuple[tuple[str, str, str], ...] = (
    ("supersplat", "clean up — the review-gate editor", "index.html"),
    ("embed", "share — the runtime inside share bundles", "index.html"),
    ("viewer", "walk — first-person walking mode", "viewer.html"),
)


def viewer_status(cfg: Config | None) -> list[ResourceStatus]:
    """Each bundled viewer's role and whether its sentinel file is present.

    Single source of truth for two callers that must not disagree: `webui/app.py`
    decides what to mount, `/system` reports what is missing. Config overrides
    win where they exist, so a locally built SuperSplat dist is honoured.
    """
    statuses = []
    for name, role, sentinel in _VIEWER_ROLES:
        root = _root_for(cfg, name)
        statuses.append(
            ResourceStatus(name=name, role=role, path=root, present=(root / sentinel).is_file())
        )
    return statuses


def _root_for(cfg: Config | None, name: str) -> Path:
    """Where a bundled viewer lives — an explicit config override wins."""
    if cfg is not None:
        if name == "supersplat":
            return cfg.viewer.supersplat_dist_path
        if name == "embed":
            return cfg.share.embed_src_path
    return bundled_path(name)
