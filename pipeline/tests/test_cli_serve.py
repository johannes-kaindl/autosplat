# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI `autosplat serve` — v1.4.3 viewer-URL behaviour."""

from __future__ import annotations

from autosplat.cli import _remote_supersplat_url_for


def test_remote_supersplat_url_for_wraps_local_ply_url() -> None:
    """v1.4.3: serve (without --with-supersplat) must open the REMOTE
    SuperSplat editor with ?load=<our-server-url>, not the raw PLY URL —
    opening the raw URL triggers a browser download instead of rendering
    the splat."""
    url = _remote_supersplat_url_for("http://127.0.0.1:8765/scene.ply")
    assert url.startswith("https://playcanvas.com/supersplat/editor")
    assert "?load=" in url
    # URL-encoded form of http://127.0.0.1:8765/scene.ply
    assert "http%3A%2F%2F127.0.0.1%3A8765%2Fscene.ply" in url


def test_remote_supersplat_url_for_handles_high_port() -> None:
    """Non-default ports survive the round-trip."""
    url = _remote_supersplat_url_for("http://127.0.0.1:54321/output/foo.ply")
    assert "54321" in url
    assert "foo.ply" in url
