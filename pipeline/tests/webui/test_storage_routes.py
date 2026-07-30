# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient


def _settled_capture(captures: Path, name: str) -> Path:
    capture = captures / name
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 100)
    (capture / "frames").mkdir()
    (capture / "frames" / "0001.png").write_bytes(b"x" * 5000)
    ts = time.time() - 2 * 3600
    for p in [capture, *capture.rglob("*")]:
        os.utime(p, (ts, ts))
    return capture


def test_get_storage_previews_and_never_deletes(app: FastAPI, tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"
    capture = _settled_capture(captures, "2026-05-01_demo")

    with TestClient(app) as client:
        r = client.get("/storage")

    assert r.status_code == 200
    assert "2026-05-01_demo" in r.text
    assert (capture / "frames").exists(), "GET must never mutate"


def test_get_storage_shows_kept_rows_with_a_reason(app: FastAPI, tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    outputs = tmp_path / "outputs"
    orphan = outputs / "2026-04-01_gone"
    orphan.mkdir(parents=True)
    (orphan / "scene.ply").write_bytes(b"ply\n" + b"x" * 900)
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = outputs

    with TestClient(app) as client:
        body = client.get("/storage").text

    assert "orphaned" in body
    assert orphan.exists()


def test_post_reclaim_frees_space(app: FastAPI, tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"
    capture = _settled_capture(captures, "2026-05-02_demo")

    with TestClient(app) as client:
        r = client.post("/storage/reclaim", follow_redirects=False)
        assert r.status_code == 303
        job = app.state.reclaim_job
        assert job.thread is not None
        job.thread.join(timeout=30)

    assert job.status == "done", job.error
    assert job.failures == ()
    assert not (capture / "frames").exists()
    assert (capture / "output" / "scene.ply").exists()


def test_reclaim_reports_progress_without_blocking_the_request(
    app: FastAPI, tmp_path: Path
) -> None:
    """The apply runs off-request: a multi-GB rmtree in a WKWebView window
    would otherwise look exactly like a frozen app."""
    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"
    _settled_capture(captures, "2026-05-03_demo")

    with TestClient(app) as client:
        client.post("/storage/reclaim", follow_redirects=False)
        app.state.reclaim_job.thread.join(timeout=30)
        r = client.get("/partials/storage-status")

    assert r.status_code == 200
    assert "done" in r.text.lower() or "reclaimed" in r.text.lower()


def test_second_reclaim_while_one_runs_is_refused(app: FastAPI, tmp_path: Path) -> None:
    import threading

    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"

    from autosplat.webui.routes import storage

    app.state.reclaim_job = storage.ReclaimJob(status="running", thread=threading.Thread(target=lambda: None))

    with TestClient(app) as client:
        r = client.post("/storage/reclaim", follow_redirects=False)

    assert r.status_code == 409


def test_nav_links_to_storage(app: FastAPI) -> None:
    with TestClient(app) as client:
        assert 'href="/storage"' in client.get("/").text
