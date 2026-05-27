# SPDX-License-Identifier: AGPL-3.0-or-later

"""Local HTTP server + browser-open for SuperSplat / PlayCanvas viewing.

Opens the configured viewer in the user's default browser, pointed at a local
HTTP server that serves the freshly trained .ply.
"""

from __future__ import annotations

import http.server
import signal
import socketserver
import threading
import urllib.parse
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from rich.console import Console

from .config import ViewerConfig
from .logging import get_logger

logger = get_logger(__name__)
_user_console = Console()

SUPERSPLAT_URL = "https://playcanvas.com/supersplat/editor"
PLAYCANVAS_VIEWER_URL = "https://playcanvas.com/viewer"


class _ReuseAddrTCPServer(socketserver.ThreadingTCPServer):
    """ThreadingTCPServer with SO_REUSEADDR set before socket bind."""

    allow_reuse_address = True


def _make_handler(serve_root: Path) -> type[http.server.SimpleHTTPRequestHandler]:
    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(serve_root), **kwargs)  # type: ignore[arg-type]

        def end_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            super().end_headers()

        def log_message(self, format: str, *args: object) -> None:
            logger.debug("viewer.http", line=format % args)

    return _Handler


@contextmanager
def serve_directory(directory: Path, port: int) -> Iterator[str]:
    """Run a threaded HTTP server in the background, serving `directory`."""
    handler = _make_handler(directory)
    try:
        httpd = _ReuseAddrTCPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        raise RuntimeError(
            f"Port {port} already in use — use --ply-port / --supersplat-port to choose a different port"
        ) from exc
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
    with (
        serve_directory(supersplat_dist, supersplat_port) as ss_base,
        serve_directory(ply_dir, ply_port) as ply_base,
    ):
        yield {"supersplat": ss_base, "ply": ply_base}


def _serve_local_and_block(
    ply_path: Path,
    cfg: ViewerConfig,
    dist_path: Path,
    stop_event: threading.Event | None,
    *,
    open_browser: bool = True,
) -> None:
    """v1.4.4 — start local SuperSplat dist + PLY server, open browser, block.

    Same building blocks as `cli.serve --with-supersplat` but invoked
    inline at the end of `autosplat process` / `rescue` so the user gets
    one-step "video → viewable splat" without a second command. Avoids
    the Mixed-Content blocking the remote `target=supersplat` path
    suffers from (HTTPS editor refuses to fetch HTTP localhost PLY).

    Blocks until SIGINT/SIGTERM (or pre-set `stop_event` for tests). The
    two ThreadingTCPServers are torn down cleanly via the nested
    context managers.

    v1.4.5 — `open_browser=False` allows `cli.serve --no-open-browser`
    to share this helper (DRY) without firing a browser tab.
    """
    with serve_supersplat_local(
        supersplat_dist=dist_path,
        supersplat_port=cfg.supersplat_local_port,
        ply_dir=ply_path.parent,
        ply_port=cfg.local_http_port,
    ) as urls:
        viewer_url = f"{urls['supersplat']}?load={urls['ply']}/{ply_path.name}"
        logger.info(
            "viewer.open_local",
            url=viewer_url,
            supersplat=urls["supersplat"],
            ply=urls["ply"],
        )
        if open_browser:
            webbrowser.open(viewer_url)
        _user_console.print(
            f"[green]Viewer:[/green] {viewer_url}\n"
            f"[dim]SuperSplat: {urls['supersplat']}\n"
            f"PLY server: {urls['ply']}/{ply_path.name}\n"
            "Press [bold]Ctrl-C[/bold] when finished to stop the local servers.[/dim]"
        )

        event = stop_event if stop_event is not None else _install_stop_handler()
        with suppress(KeyboardInterrupt):
            event.wait()
        _user_console.print("[dim]Viewer servers stopped.[/dim]")


def _install_stop_handler() -> threading.Event:
    """Install SIGINT/SIGTERM handler that sets a fresh Event. Returns it.

    Used by `open_in_viewer` to wait until the user presses Ctrl-C without
    busy-looping. The handler replaces (does not chain) any existing one
    for the duration of the wait — viewer.open_in_viewer is always the
    outermost blocking call at that point in the CLI lifecycle, so we don't
    need to preserve a prior handler.
    """
    event = threading.Event()

    def _handler(signum: int, frame: object) -> None:
        event.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    return event


def open_in_viewer(
    ply_path: Path,
    cfg: ViewerConfig,
    *,
    stop_event: threading.Event | None = None,
) -> None:
    """Open `ply_path` in the configured viewer.

    Behaviour by target:
      • `none` / `auto_open=false` — no-op.
      • `supersplat-local` — log a hint, return immediately. The local
        SuperSplat dist needs its own server, started by `autosplat serve`.
      • `supersplat` / `playcanvas` — start a local HTTP server serving
        `ply_path.parent`, open the viewer URL (`?load=…127.0.0.1:port/…`)
        in the browser, then **block** until the user sends SIGINT
        (Ctrl-C) or `stop_event` is set. The server is shut down cleanly
        on exit so the port is reusable.

    Pre-v1.4.2 this function was fire-and-forget for remote targets: it
    constructed the URL with `?load=http://127.0.0.1:8765/…` but never
    started a server on 8765. SuperSplat's load attempt silently failed
    and the editor opened empty — drag-and-drop the file manually was the
    only workaround. The blocking-server fix restores the originally-meant
    behaviour at the cost of one extra Ctrl-C at the end of `autosplat
    process`.

    `stop_event` is injection-only for tests. Production callers omit it;
    the function installs its own SIGINT handler and creates a fresh Event.
    """
    if not cfg.auto_open or cfg.target == "none":
        logger.info("viewer.skip", auto_open=cfg.auto_open, target=cfg.target)
        return

    if not ply_path.exists():
        logger.warning("viewer.ply_missing", path=str(ply_path))
        return

    if cfg.target == "supersplat-local":
        # v1.4.4 — when the local SuperSplat dist is built, run both servers
        # and open the browser inline, just like `autosplat serve --with-supersplat`
        # does. Falls back to the old hint-only path if the dist isn't there.
        dist_path = cfg.supersplat_dist_path
        if not dist_path.is_absolute():
            dist_path = Path.cwd() / dist_path
        if dist_path.is_dir() and (dist_path / "index.html").is_file():
            _serve_local_and_block(ply_path, cfg, dist_path, stop_event)
            return
        logger.info(
            "viewer.local_dist_missing",
            command=f"autosplat serve {ply_path.parent} --with-supersplat",
            expected_path=str(dist_path),
        )
        _user_console.print(
            "[dim]Local SuperSplat dist not built. "
            f"Run [bold]bash scripts/setup_supersplat.sh[/bold] once, then "
            "the auto-open will work. For now, drag the PLY into "
            f"[bold]{SUPERSPLAT_URL}[/bold] manually.[/dim]"
        )
        return

    # v1.4.5 — modern browsers block HTTPS pages from fetching HTTP
    # localhost resources (Mixed-Content). The remote SuperSplat target
    # therefore opens an empty editor in practice; we keep the path for
    # backwards-compat but nudge the user toward the local default.
    if cfg.target == "supersplat":
        logger.warning(
            "viewer.remote_supersplat_deprecated",
            recommendation="target='supersplat-local'",
        )
        _user_console.print(
            "[yellow]Warning:[/yellow] target='supersplat' may leave the "
            "editor empty because modern browsers block HTTPS→HTTP fetches. "
            "Run [bold]bash scripts/setup_supersplat.sh[/bold] once, then "
            'set [bold][viewer] target = "supersplat-local"[/bold] for a '
            "fully-local, blocking-server-free experience."
        )

    # Remote targets — serve the .ply locally so SuperSplat's ?load= URL
    # actually resolves, instead of silently failing to fetch.
    viewer_url = _build_viewer_url(cfg, ply_path)
    with serve_directory(ply_path.parent, cfg.local_http_port) as ply_base:
        ply_url = f"{ply_base}/{ply_path.name}"
        logger.info(
            "viewer.open",
            viewer=cfg.target,
            url=viewer_url,
            ply_url=ply_url,
        )
        webbrowser.open(viewer_url)
        _user_console.print(
            f"[green]Viewer:[/green] {viewer_url}\n"
            f"[dim]Serving PLY at {ply_url}. "
            "Press [bold]Ctrl-C[/bold] when finished to stop the local server.[/dim]"
        )

        event = stop_event if stop_event is not None else _install_stop_handler()
        # Belt-and-braces — _install_stop_handler swallows SIGINT into the
        # event, but a test pre-passing an Event may not have installed a
        # handler, in which case Ctrl-C surfaces here.
        with suppress(KeyboardInterrupt):
            event.wait()
        _user_console.print("[dim]Viewer server stopped.[/dim]")


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
