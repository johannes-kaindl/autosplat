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
    """The thread backing the existing job must actually be alive for this
    refusal to be correct — a thread built but never started (the original
    version of this test) would make `existing.thread.is_alive()` False and
    so would no longer exercise the refusal after the wedged-job fix below."""
    import threading

    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"

    from autosplat.webui.routes import storage

    release = threading.Event()
    running_thread = threading.Thread(target=release.wait)
    running_thread.start()
    app.state.reclaim_job = storage.ReclaimJob(status="running", thread=running_thread)

    try:
        with TestClient(app) as client:
            r = client.post("/storage/reclaim", follow_redirects=False)
        assert r.status_code == 409
    finally:
        release.set()
        running_thread.join(timeout=5)


def test_reclaim_recovers_from_a_wedged_job_whose_thread_died(
    app: FastAPI, tmp_path: Path
) -> None:
    """A job stuck at status='running' whose backing thread has already
    exited (a crash mid-sweep, or any path that leaves status stale) must
    not permanently 409 every future reclaim attempt for the life of the
    process — that also means a hidden button and a busy 2s poll forever."""
    import threading

    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"
    _settled_capture(captures, "2026-05-04_demo")

    from autosplat.webui.routes import storage

    dead_thread = threading.Thread(target=lambda: None)
    dead_thread.start()
    dead_thread.join()
    assert not dead_thread.is_alive()
    app.state.reclaim_job = storage.ReclaimJob(status="running", thread=dead_thread)

    with TestClient(app) as client:
        r = client.post("/storage/reclaim", follow_redirects=False)
        assert r.status_code == 303
        new_job = app.state.reclaim_job
        assert new_job is not None
        assert new_job.thread is not None
        new_job.thread.join(timeout=30)

    assert new_job.status == "done", new_job.error


def test_wedged_job_offers_the_button_and_stops_polling(app: FastAPI, tmp_path: Path) -> None:
    """Round-2 re-review finding: fixing the route's 409 check alone left the
    templates still branching on raw `status == "running"`, so a wedged job
    (status stuck at "running", thread already dead) rendered a hidden
    Reclaim button *and* a busy `hx-trigger="every 2s"` poll that never
    self-terminates — the exact symptom `ReclaimJob.is_running`'s docstring
    names. `ReclaimJob.is_running` is what both `storage.html` (button) and
    `partials/storage_status.html` (poll) now gate on, same as the route.
    Asserted on the rendered HTML the browser actually receives, not on the
    dataclass."""
    import threading

    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"
    _settled_capture(captures, "2026-05-06_demo")

    from autosplat.webui.routes import storage

    dead_thread = threading.Thread(target=lambda: None)
    dead_thread.start()
    dead_thread.join()
    assert not dead_thread.is_alive()
    app.state.reclaim_job = storage.ReclaimJob(status="running", thread=dead_thread)

    with TestClient(app) as client:
        body = client.get("/storage").text

    assert "Reclaim now" in body
    # Not a bare "hx-trigger" substring check: base.html's own JS has a
    # comment mentioning "hx-trigger" (V12-4 dev overlay) that would make
    # that assertion pass unconditionally regardless of this fix. The
    # `hx-get` target is what actually drives the poll for this fragment.
    assert 'hx-get="/partials/storage-status"' not in body


def test_get_storage_refuses_an_unsafe_layout_and_hides_the_button(
    app: FastAPI, tmp_path: Path
) -> None:
    """outputs_dir nested inside captures_dir is the layout
    `refuse_if_unsafe_storage_layout` calls catastrophic. The preview must
    say so, in the page, rather than render a full plan with a working
    'Reclaim now' button that a POST would then refuse with raw JSON."""
    captures = tmp_path / "captures"
    outputs = captures / "outputs"
    outputs.mkdir(parents=True)
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = outputs

    with TestClient(app) as client:
        r = client.get("/storage")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Refusing" in r.text
    assert "Reclaim now" not in r.text


def test_post_reclaim_refuses_an_unsafe_layout(app: FastAPI, tmp_path: Path) -> None:
    """Belt and braces: the POST keeps its own guard even though the GET
    now also checks — a client that never loaded the preview (or hit the
    endpoint directly) must still be refused."""
    captures = tmp_path / "captures"
    outputs = captures / "outputs"
    outputs.mkdir(parents=True)
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = outputs

    with TestClient(app) as client:
        r = client.post("/storage/reclaim", follow_redirects=False)

    assert r.status_code == 400
    assert getattr(app.state, "reclaim_job", None) is None


def test_nav_links_to_storage(app: FastAPI) -> None:
    with TestClient(app) as client:
        assert 'href="/storage"' in client.get("/").text
