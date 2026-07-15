# SPDX-License-Identifier: AGPL-3.0-or-later

"""Assemble a self-contained, self-hostable share bundle from a compressed splat.

A bundle is a folder named by an unguessable token containing a copy of the
embed viewer runtime plus the client's `.sog` at `c/scene.sog`. `embed/index.html`
is itself the entry point (`?src=c/scene.sog`), so no redirect file is written.
"Unlisted" = the token is unguessable; this is not access control.
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
    """Full ``{base_url}/{token}/?src=c/scene.sog`` link, or None when base_url is unset.

    embed/index.html is the bundle's entry point and needs the ``src`` query
    param to load the scene (no redirect file is written into the bundle).
    """
    if not base_url.strip():
        return None
    return f"{base_url.rstrip('/')}/{token}/?src=c/scene.sog"


# Top-level embed entries copied into a bundle. Allowlist (not denylist) so a
# future stray file in embed/ never leaks into a client's public bundle.
_EMBED_ALLOWLIST = (
    "index.html",
    "js",
    "css",
    "vendor",
)


@dataclass
class BundlePaths:
    folder: Path
    zip_path: Path


def assemble_bundle(
    sog_path: Path, embed_src: Path, share_dir: Path, token: str
) -> BundlePaths:
    """Build ``share_dir/<token>/`` (self-contained embed viewer + splat) and its zip.

    Raises FileNotFoundError if ``embed_src`` is missing its ``index.html``
    (surfaces the monorepo-source / frozen-bundle requirement clearly).
    """
    if not (embed_src / "index.html").exists():
        raise FileNotFoundError(f"embed viewer sources not found at {embed_src}")

    folder = share_dir / token
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    for name in _EMBED_ALLOWLIST:
        src = embed_src / name
        if not src.exists():
            continue  # optional entries tolerated
        dest = folder / name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)

    c_dir = folder / "c"
    c_dir.mkdir()
    shutil.copy2(sog_path, c_dir / "scene.sog")

    zip_path = share_dir / f"{token}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            zf.write(path, path.relative_to(share_dir))

    return BundlePaths(folder=folder, zip_path=zip_path)
