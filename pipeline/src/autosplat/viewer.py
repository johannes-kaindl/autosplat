"""Local HTTP server + browser-open for SuperSplat / PlayCanvas viewing.

Opens the configured viewer in the user's default browser, pointed at a local
HTTP server that serves the freshly trained .ply.
"""

from __future__ import annotations

import http.server
import socketserver
import threading
import urllib.parse
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import ViewerConfig
from .logging import get_logger

logger = get_logger(__name__)

SUPERSPLAT_URL = "https://playcanvas.com/supersplat/editor"
PLAYCANVAS_VIEWER_URL = "https://playcanvas.com/viewer"


class _ReuseAddrTCPServer(socketserver.ThreadingTCPServer):
    """ThreadingTCPServer with SO_REUSEADDR set before socket bind."""

    allow_reuse_address = True


def _make_handler(serve_root: Path) -> type[http.server.SimpleHTTPRequestHandler]:
    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            super().end_headers()

        def log_message(self, format: str, *args) -> None:
            logger.debug("viewer.http", line=format % args)

    return _Handler


@contextmanager
def serve_directory(directory: Path, port: int) -> Iterator[str]:
    """Run a threaded HTTP server in the background, serving `directory`."""
    handler = _make_handler(directory)
    try:
        httpd = _ReuseAddrTCPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        raise RuntimeError(f"Port {port} already in use — use --ply-port / --supersplat-port to choose a different port") from exc
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    actual_port = httpd.server_address[1]
    base_url = f"http://127.0.0.1:{actual_port}"
    logger.info("viewer.serving", url=base_url, directory=str(directory))
    try:
        yield base_url
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


@contextmanager
def serve_supersplat_local(
    supersplat_dist: Path,
    supersplat_port: int,
    ply_dir: Path,
    ply_port: int,
) -> Iterator[dict[str, str]]:
    """Start SuperSplat static server + PLY server. Yields URL dict."""
    with serve_directory(supersplat_dist, supersplat_port) as ss_base:
        with serve_directory(ply_dir, ply_port) as ply_base:
            yield {"supersplat": ss_base, "ply": ply_base}


def open_in_viewer(ply_path: Path, cfg: ViewerConfig) -> None:
    """Open `ply_path` in the configured viewer. No-op if `target == "none"`."""
    if not cfg.auto_open or cfg.target == "none":
        logger.info("viewer.skip", auto_open=cfg.auto_open, target=cfg.target)
        return

    if not ply_path.exists():
        logger.warning("viewer.ply_missing", path=str(ply_path))
        return

    if cfg.target == "supersplat-local":
        # No browser open — the local SuperSplat server is not running at pipeline
        # exit time. Phase 9.2 adds `autosplat serve` which starts both servers.
        logger.info(
            "viewer.local_hint",
            command=f"autosplat serve {ply_path.parent} --with-supersplat",
        )
        return

    # Remote targets: serve the .ply via a short-lived local server and embed its
    # URL in the viewer URL.
    ply_url = f"http://127.0.0.1:{cfg.local_http_port}/{ply_path.name}"
    viewer_url = _build_viewer_url(cfg, ply_path)

    logger.info("viewer.open", viewer=cfg.target, url=viewer_url, ply_url=ply_url)
    webbrowser.open(viewer_url)


def _build_viewer_url(cfg: ViewerConfig, ply_path: Path) -> str:
    """Return the full viewer URL for the given PLY path and config.

    Returns None-equivalent (empty string) only when target is unrecognised.
    For ``supersplat-local`` callers should check the target before calling this
    function; it will still return a well-formed URL for testing convenience.
    """
    ply_name = ply_path.name
    target = cfg.target

    if target == "supersplat-local":
        return (
            f"http://localhost:{cfg.supersplat_local_port}"
            f"?load=http://127.0.0.1:{cfg.local_http_port}/{ply_name}"
        )

    ply_url = f"http://127.0.0.1:{cfg.local_http_port}/{ply_name}"
    encoded = urllib.parse.quote(ply_url, safe="")

    if target == "supersplat":
        return f"{SUPERSPLAT_URL}?load={encoded}"
    if target == "playcanvas":
        return f"{PLAYCANVAS_VIEWER_URL}?load={encoded}"
    return ply_url
