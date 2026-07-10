# SPDX-License-Identifier: AGPL-3.0-or-later

"""Assemble a self-contained, self-hostable share bundle from a compressed splat.

A bundle is a folder named by an unguessable token containing a copy of the
viewer runtime plus the client's `.sog` at `c/scene.sog`, entered via an
`index.html` redirect to `viewer.html?src=c/scene.sog`. The whole folder is also
zipped for one-click download. "Unlisted" = the token is unguessable; this is
not access control.
"""

from __future__ import annotations

import re
import secrets
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# base32 alphabet without padding — URL-safe, case-insensitive
_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_SUFFIX_LEN = 10  # ~50 bits of entropy


def _default_rand(n: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")


def make_share_token(capture_id: str, *, rand: Callable[[int], str] | None = None) -> str:
    """Return a URL-safe token: slugified capture stem + random base32 suffix.

    The leading ``YYYY-MM-DD_`` date prefix of the capture id is dropped so the
    readable part is the scene name, e.g. ``lgs-pv-20260610-k7m2a9x4qz``.
    """
    rand = rand or _default_rand
    stem = capture_id.split("_", 1)[1] if "_" in capture_id else capture_id
    prefix = _slugify(stem) or "scene"
    return f"{prefix}-{rand(_SUFFIX_LEN)}"


def share_link(base_url: str, token: str) -> str | None:
    """Full ``{base_url}/{token}/`` link, or None when base_url is unset."""
    if not base_url.strip():
        return None
    return f"{base_url.rstrip('/')}/{token}/"


# Top-level viewer entries copied into a bundle. Allowlist (not denylist) so a
# future stray file in viewer/ never leaks into a client's public bundle.
_VIEWER_ALLOWLIST = (
    "viewer.html",
    "js",
    "css",
    "icons",
    "manifest.webmanifest",
    "service-worker.js",
    "LICENSE",
)

_INDEX_REDIRECT = (
    "<!doctype html><meta charset=utf-8>"
    '<meta http-equiv=refresh content="0; url=viewer.html?src=c/scene.sog">'
    '<link rel=canonical href="viewer.html?src=c/scene.sog">'
    '<a href="viewer.html?src=c/scene.sog">Open viewer</a>'
)


@dataclass
class BundlePaths:
    folder: Path
    zip_path: Path


def assemble_bundle(
    sog_path: Path, viewer_src: Path, share_dir: Path, token: str
) -> BundlePaths:
    """Build ``share_dir/<token>/`` (self-contained viewer + splat) and its zip.

    Raises FileNotFoundError if ``viewer_src`` is missing its ``viewer.html``
    (surfaces the monorepo-source requirement clearly).
    """
    if not (viewer_src / "viewer.html").exists():
        raise FileNotFoundError(f"viewer sources not found at {viewer_src}")

    folder = share_dir / token
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    for name in _VIEWER_ALLOWLIST:
        src = viewer_src / name
        if not src.exists():
            continue  # optional entries (e.g. service-worker) tolerated
        dest = folder / name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)

    c_dir = folder / "c"
    c_dir.mkdir()
    shutil.copy2(sog_path, c_dir / "scene.sog")

    (folder / "index.html").write_text(_INDEX_REDIRECT, encoding="utf-8")

    zip_path = share_dir / f"{token}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            zf.write(path, path.relative_to(share_dir))

    return BundlePaths(folder=folder, zip_path=zip_path)
