# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for viewer URL builder, open_in_viewer behaviour, and config roundtrip."""

from __future__ import annotations

import http.client
from pathlib import Path
from unittest.mock import patch

import pytest

from autosplat.config import ViewerConfig, load_config
from autosplat.viewer import (
    PLAYCANVAS_VIEWER_URL,
    SUPERSPLAT_URL,
    _build_viewer_url,
    open_in_viewer,
    serve_directory,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _pick_free_port() -> int:
    """Bind to 0 → kernel picks a free high port; close, return it.

    Slightly race-y in theory (the port could be claimed between close and
    re-bind), but `_ReuseAddrTCPServer.allow_reuse_address` handles the case
    in practice — and ViewerConfig.local_http_port forbids 0 directly so we
    can't pass through.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_cfg(**overrides) -> ViewerConfig:
    """Return a ViewerConfig with sensible defaults, accepting field overrides."""
    defaults = dict(
        auto_open=True,
        local_http_port=8765,
        target="supersplat",
        supersplat_local_port=3000,
        supersplat_dist_path=Path("target/supersplat/dist"),
    )
    defaults.update(overrides)
    return ViewerConfig(**defaults)


# ─── _build_viewer_url ────────────────────────────────────────────────────────


def test_build_url_supersplat_local() -> None:
    cfg = _make_cfg(target="supersplat-local", supersplat_local_port=3000, local_http_port=8765)
    ply = Path("/some/dir/scene.ply")
    url = _build_viewer_url(cfg, ply)
    assert url == "http://localhost:3000?load=http://127.0.0.1:8765/scene.ply"


def test_build_url_supersplat_local_custom_ports() -> None:
    cfg = _make_cfg(target="supersplat-local", supersplat_local_port=4000, local_http_port=9000)
    ply = Path("/run/output.ply")
    url = _build_viewer_url(cfg, ply)
    assert url == "http://localhost:4000?load=http://127.0.0.1:9000/output.ply"


def test_build_url_supersplat_remote() -> None:
    cfg = _make_cfg(target="supersplat")
    ply = Path("/some/dir/scene.ply")
    url = _build_viewer_url(cfg, ply)
    assert "playcanvas.com" in url
    assert SUPERSPLAT_URL in url or url.startswith(SUPERSPLAT_URL)
    # The remote PLY URL must be encoded in the query param
    assert "scene.ply" in url


def test_build_url_supersplat_remote_has_load_param() -> None:
    cfg = _make_cfg(target="supersplat")
    ply = Path("/data/capture/splat.ply")
    url = _build_viewer_url(cfg, ply)
    assert url.startswith(f"{SUPERSPLAT_URL}?load=")


def test_build_url_playcanvas() -> None:
    cfg = _make_cfg(target="playcanvas")
    ply = Path("/data/capture/splat.ply")
    url = _build_viewer_url(cfg, ply)
    assert "playcanvas.com/viewer" in url
    assert url.startswith(f"{PLAYCANVAS_VIEWER_URL}?load=")


# ─── open_in_viewer behaviour ─────────────────────────────────────────────────


def test_open_in_viewer_supersplat_local_no_browser_when_dist_missing(
    tmp_path: Path,
) -> None:
    """v1.4.4 — supersplat-local without a built dist falls back to a
    console hint and does NOT open a browser."""
    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply")
    # Point dist_path at a tmp dir that doesn't have index.html
    cfg = _make_cfg(target="supersplat-local", supersplat_dist_path=tmp_path / "no_dist")

    with patch("autosplat.viewer.webbrowser.open") as mock_open:
        open_in_viewer(ply, cfg)

    mock_open.assert_not_called()


def test_open_in_viewer_supersplat_local_opens_local_servers_when_dist_present(
    tmp_path: Path,
) -> None:
    """v1.4.4 — supersplat-local WITH a built dist starts both local
    servers, opens the browser at the local SuperSplat URL with ?load=
    pointing at the local PLY server, and blocks until stop_event is set."""
    import threading

    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"\x00ply")

    # Fake "built" dist
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>fake supersplat</html>", encoding="utf-8")

    cfg = _make_cfg(
        target="supersplat-local",
        supersplat_dist_path=dist,
        local_http_port=_pick_free_port(),
        supersplat_local_port=_pick_free_port(),
    )

    stop = threading.Event()
    stop.set()  # don't actually block

    with patch("autosplat.viewer.webbrowser.open") as mock_open:
        open_in_viewer(ply, cfg, stop_event=stop)

    mock_open.assert_called_once()
    called = mock_open.call_args[0][0]
    # Local SuperSplat URL with ?load=<local PLY URL>
    assert called.startswith("http://127.0.0.1:")
    assert "?load=http://127.0.0.1:" in called
    assert "/scene.ply" in called


def test_open_in_viewer_auto_open_false_no_browser(tmp_path: Path) -> None:
    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply")
    cfg = _make_cfg(auto_open=False, target="supersplat")

    with patch("autosplat.viewer.webbrowser.open") as mock_open:
        open_in_viewer(ply, cfg)

    mock_open.assert_not_called()


def test_open_in_viewer_target_none_no_browser(tmp_path: Path) -> None:
    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply")
    cfg = _make_cfg(target="none")

    with patch("autosplat.viewer.webbrowser.open") as mock_open:
        open_in_viewer(ply, cfg)

    mock_open.assert_not_called()


def test_open_in_viewer_supersplat_opens_browser_and_serves_ply(tmp_path: Path) -> None:
    """v1.4.2: open_in_viewer must (a) open browser at viewer URL,
    (b) actually serve the PLY on local_http_port so SuperSplat's
    ?load= fetch resolves, (c) block until stop_event is set."""
    import threading

    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply")
    cfg = _make_cfg(target="supersplat", local_http_port=_pick_free_port())

    stop = threading.Event()
    stop.set()  # don't actually block

    from contextlib import contextmanager as _ctx

    served_paths: list[str] = []
    real_serve_directory = serve_directory

    @_ctx
    def tracking_serve(directory, port):
        with real_serve_directory(directory, port) as base:
            served_paths.append(f"{base}/{ply.name}")
            yield base

    with (
        patch("autosplat.viewer.webbrowser.open") as mock_open,
        patch("autosplat.viewer.serve_directory", tracking_serve),
    ):
        open_in_viewer(ply, cfg, stop_event=stop)

    mock_open.assert_called_once()
    called_url: str = mock_open.call_args[0][0]
    assert "playcanvas.com" in called_url
    # The ply server was actually started — its base-url appears in the
    # tracking list. Without the v1.4.2 fix this list would be empty.
    assert len(served_paths) == 1


def test_open_in_viewer_serves_ply_reachable_via_http(tmp_path: Path) -> None:
    """End-to-end: the PLY is actually fetchable from the served URL during
    the block (otherwise SuperSplat's ?load= would silently fail like
    pre-v1.4.2)."""
    import threading
    import urllib.parse
    from urllib.request import urlopen

    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"\x00\x01\x02ply-content")
    cfg = _make_cfg(target="supersplat", local_http_port=_pick_free_port())

    stop = threading.Event()
    fetched: dict[str, bytes] = {}

    def consumer() -> None:
        # Sleep briefly so the server is up before we hit it
        import time as _t

        _t.sleep(0.2)
        # Recover the actual ply URL from mock_open call
        url = mock_open.call_args[0][0]
        parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        ply_url = urllib.parse.unquote(parsed["load"][0])
        fetched["body"] = urlopen(ply_url).read()
        stop.set()

    with patch("autosplat.viewer.webbrowser.open") as mock_open:
        consumer_thread = threading.Thread(target=consumer, daemon=True)
        consumer_thread.start()
        open_in_viewer(ply, cfg, stop_event=stop)
        consumer_thread.join(timeout=5)

    assert fetched["body"] == b"\x00\x01\x02ply-content"


def test_open_in_viewer_missing_ply_no_browser(tmp_path: Path) -> None:
    ply = tmp_path / "nonexistent.ply"
    cfg = _make_cfg(target="supersplat")

    with patch("autosplat.viewer.webbrowser.open") as mock_open:
        open_in_viewer(ply, cfg)

    mock_open.assert_not_called()


# ─── Config roundtrip ─────────────────────────────────────────────────────────


def test_viewer_config_supersplat_local_port_default() -> None:
    cfg = load_config(include_xdg=False)
    assert cfg.viewer.supersplat_local_port == 3000


def test_viewer_config_supersplat_dist_path_default() -> None:
    cfg = load_config(include_xdg=False)
    assert cfg.viewer.supersplat_dist_path == Path("target/supersplat/dist")


def test_viewer_config_supersplat_local_port_override(tmp_path: Path) -> None:
    user = tmp_path / "u.toml"
    user.write_text(
        """
[viewer]
supersplat_local_port = 4321
""",
        encoding="utf-8",
    )
    cfg = load_config(user_config_path=user, include_xdg=False)
    assert cfg.viewer.supersplat_local_port == 4321
    # Other viewer fields remain at defaults
    assert cfg.viewer.local_http_port == 8765


def test_viewer_config_supersplat_dist_path_override(tmp_path: Path) -> None:
    user = tmp_path / "u.toml"
    user.write_text(
        """
[viewer]
supersplat_dist_path = "/opt/supersplat/dist"
""",
        encoding="utf-8",
    )
    cfg = load_config(user_config_path=user, include_xdg=False)
    assert cfg.viewer.supersplat_dist_path == Path("/opt/supersplat/dist")


def test_viewer_config_target_accepts_supersplat_local(tmp_path: Path) -> None:
    user = tmp_path / "u.toml"
    user.write_text(
        """
[viewer]
target = "supersplat-local"
""",
        encoding="utf-8",
    )
    cfg = load_config(user_config_path=user, include_xdg=False)
    assert cfg.viewer.target == "supersplat-local"


def test_viewer_config_invalid_port_rejected() -> None:
    with pytest.raises(Exception):
        _make_cfg(supersplat_local_port=80)  # below ge=1024


# ─── serve_supersplat_local + _find_ply ──────────────────────────────────────


def test_serve_directory_sends_cors_header(tmp_path: Path) -> None:
    """serve_directory must include Access-Control-Allow-Origin: * so SuperSplat
    on :3000 can fetch the PLY from :8765 without CORS block."""
    (tmp_path / "test.ply").write_bytes(b"ply\nformat ascii 1.0\nend_header\n")
    with serve_directory(tmp_path, port=0) as base_url:
        port = int(base_url.rsplit(":", 1)[-1])
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/test.ply")
        res = conn.getresponse()
        assert res.status == 200
        assert res.getheader("Access-Control-Allow-Origin") == "*"


def test_serve_supersplat_local_yields_both_urls(tmp_path: Path) -> None:
    """Both servers start and URLs are returned."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html/>")
    ply_dir = tmp_path / "capture"
    ply_dir.mkdir()
    (ply_dir / "scene.ply").write_bytes(b"ply\n")

    from autosplat.viewer import serve_supersplat_local

    with serve_supersplat_local(dist, 0, ply_dir, 0) as urls:
        # port 0 = OS-assigned; servers are running
        assert "supersplat" in urls
        assert "ply" in urls
        assert urls["supersplat"].startswith("http://127.0.0.1:")
        assert urls["ply"].startswith("http://127.0.0.1:")


def test_find_ply_direct(tmp_path: Path) -> None:
    (tmp_path / "scene.ply").write_bytes(b"ply\n")
    from autosplat.cli import _find_ply

    assert _find_ply(tmp_path) == tmp_path / "scene.ply"


def test_find_ply_in_output_subdir(tmp_path: Path) -> None:
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "scene.ply").write_bytes(b"ply\n")
    from autosplat.cli import _find_ply

    assert _find_ply(tmp_path) == tmp_path / "output" / "scene.ply"


def test_find_ply_not_found(tmp_path: Path) -> None:
    from autosplat.cli import _find_ply

    assert _find_ply(tmp_path) is None
