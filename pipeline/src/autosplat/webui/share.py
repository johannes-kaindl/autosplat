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
from collections.abc import Callable

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
