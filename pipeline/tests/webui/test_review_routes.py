# SPDX-License-Identifier: AGPL-3.0-or-later

import json
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient


def _make_capture(tmp_path: Path, capture_id: str = "2026-07-19_lgs") -> Path:
    capture_dir = tmp_path / capture_id
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 1000)
    (capture_dir / "pipeline.log").write_text("done\n")
    return capture_dir


def _settle(capture_dir: Path) -> None:
    """Age everything past `lifecycle.recently_active`'s 1h window.

    A freshly-written fixture is indistinguishable from a capture with a CLI
    `resume`/`add-video` writing into it right now, and the review-triggered
    prune (correctly) defers on that — see
    `test_confirm_does_not_reclaim_while_a_cli_run_is_in_flight`. Tests that
    want the prune to actually run have to represent a settled capture.
    """
    import os
    import time

    ts = time.time() - 2 * 3600
    for p in [capture_dir, *capture_dir.rglob("*")]:
        os.utime(p, (ts, ts))


def test_confirm_writes_review_marker(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post("/captures/2026-07-19_lgs/review/confirm", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/captures/2026-07-19_lgs"
    marker = capture_dir / "output" / ".review.json"
    assert marker.exists()
    data = json.loads(marker.read_text())
    assert data["status"] == "reviewed"
    assert data["source_ply_mtime"] == (capture_dir / "output" / "scene.ply").stat().st_mtime
    assert not (capture_dir / "output" / "scene_reviewed.ply").exists()


def test_confirm_after_rebuild_removes_stale_reviewed_ply(app: FastAPI, tmp_path: Path) -> None:
    """Reproduces the stale-scene_reviewed.ply bug: upload a cleaned PLY (v1),
    simulate a rebuild that changes scene.ply's mtime (v2, review auto-
    invalidates), then confirm-unchanged on v2. The leftover v1
    scene_reviewed.ply must not linger and get silently re-published."""
    import time

    from autosplat.webui.state import _review_status, resolve_publish_ply

    capture_id = "2026-07-19_lgs"
    capture_dir = _make_capture(tmp_path, capture_id)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        # 1. Upload a cleaned PLY -> scene_reviewed.ply (v1) written + marker recorded.
        r = client.post(
            f"/captures/{capture_id}/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"ply\nv1-cleaned", "application/octet-stream")},
            follow_redirects=False,
        )
        assert r.status_code == 303
        reviewed = capture_dir / "output" / "scene_reviewed.ply"
        assert reviewed.read_bytes() == b"ply\nv1-cleaned"

        # 2. Simulate a rebuild: scene.ply gets new content + a later mtime.
        time.sleep(0.01)
        (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n" + b"y" * 1000)
        assert _review_status(capture_dir) == "unreviewed"

        # 3. User reviews the rebuilt v2 scene and confirms it unchanged.
        r = client.post(f"/captures/{capture_id}/review/confirm", follow_redirects=False)
        assert r.status_code == 303

    # The stale v1 cleaned file must be gone, not silently re-published.
    assert not reviewed.exists()
    status = _review_status(capture_dir)
    assert status == "reviewed"
    assert resolve_publish_ply(capture_dir, status) == capture_dir / "output" / "scene.ply"


def test_confirm_unknown_capture_404s(app: FastAPI, tmp_path: Path) -> None:
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        r = client.post("/captures/does-not-exist/review/confirm")
    assert r.status_code == 404


def test_confirm_no_ply_at_all_409s(app: FastAPI, tmp_path: Path) -> None:
    """Test that confirm returns 409 when capture has no PLY (not even legacy)."""
    capture_id = "2026-07-19_no_ply"
    capture_dir = tmp_path / capture_id
    capture_dir.mkdir(parents=True)
    (capture_dir / "pipeline.log").write_text("done\n")
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(f"/captures/{capture_id}/review/confirm", follow_redirects=False)

    assert r.status_code == 409
    assert "output/scene.ply" in r.json()["detail"]


def test_confirm_legacy_layout_409s(app: FastAPI, tmp_path: Path) -> None:
    """Test that confirm returns 409 for legacy layout (scene.ply at root, no output/)."""
    capture_id = "2026-07-19_legacy"
    capture_dir = tmp_path / capture_id
    capture_dir.mkdir(parents=True)
    # Legacy layout: PLY at root, not in output/
    (capture_dir / "scene.ply").write_bytes(b"ply\n" + b"x" * 1000)
    (capture_dir / "pipeline.log").write_text("done\n")
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(f"/captures/{capture_id}/review/confirm", follow_redirects=False)

    # Should return 409, not 500 (unhandled FileNotFoundError)
    assert r.status_code == 409
    assert "output/scene.ply" in r.json()["detail"]


def test_upload_valid_ply_saves_reviewed_file_and_marker(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={
                "reviewed_ply": ("cleaned.ply", b"ply\ncleaned-data", "application/octet-stream")
            },
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/captures/2026-07-19_lgs"
    reviewed = capture_dir / "output" / "scene_reviewed.ply"
    assert reviewed.exists()
    assert reviewed.read_bytes() == b"ply\ncleaned-data"
    marker = capture_dir / "output" / ".review.json"
    assert json.loads(marker.read_text())["status"] == "reviewed"


def test_upload_rejects_non_ply_extension(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.txt", b"ply\ndata", "text/plain")},
        )

    assert r.status_code == 400
    assert "Unsupported file type" in r.text


def test_upload_rejects_missing_ply_header(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"not a ply file", "application/octet-stream")},
        )

    assert r.status_code == 400
    assert "PLY" in r.text


def test_upload_rejects_empty_file(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"", "application/octet-stream")},
        )

    assert r.status_code == 400
    assert "empty" in r.text.lower()


def test_view_page_shows_review_panel_when_unreviewed(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        body = client.get("/captures/2026-07-19_lgs/view").text

    assert 'action="/captures/2026-07-19_lgs/review/upload"' in body
    assert 'action="/captures/2026-07-19_lgs/review/confirm"' in body
    assert "Confirm unchanged" in body


def test_view_page_hides_review_panel_when_reviewed(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    scene_ply = capture_dir / "output" / "scene.ply"
    (capture_dir / "output" / ".review.json").write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": "2026-07-19T00:00:00",
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        )
    )
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        body = client.get("/captures/2026-07-19_lgs/view").text

    assert 'action="/captures/2026-07-19_lgs/review/upload"' not in body


def test_confirm_reclaims_intermediates(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    (capture_dir / "colmap").mkdir()
    (capture_dir / "rescue" / "probes").mkdir(parents=True)
    (capture_dir / "rescue" / "clips").mkdir()
    (capture_dir / "rescue" / "clips" / "0.mp4").write_bytes(b"m" * 10)
    _settle(capture_dir)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post("/captures/2026-07-19_lgs/review/confirm", follow_redirects=False)

    assert r.status_code == 303
    assert not (capture_dir / "colmap").exists()
    assert not (capture_dir / "rescue" / "probes").exists()
    # C1: the leaf-clip sources a bisected capture was rebuilt from survive —
    # add-video/resume re-extract from them.
    assert (capture_dir / "rescue" / "clips" / "0.mp4").exists()
    assert (capture_dir / "output" / ".review.json").exists()


def test_confirm_does_not_reclaim_while_job_runs(app: FastAPI, tmp_path: Path) -> None:
    # resume/add-video need colmap/ and frames/ — reclaiming underneath a live
    # job would make it unrecoverable.
    capture_dir = _make_capture(tmp_path)
    (capture_dir / "colmap").mkdir()
    app.state.cfg.paths.captures_dir = tmp_path

    class _LiveJob:
        status = "running"

    app.state.job_runner.get_job = lambda _id: _LiveJob()

    with TestClient(app) as client:
        r = client.post("/captures/2026-07-19_lgs/review/confirm", follow_redirects=False)

    assert r.status_code == 303
    assert (capture_dir / "colmap").exists()  # deferred, not lost
    assert (capture_dir / "output" / ".review.json").exists()  # the sign-off still counts


def test_upload_reclaims_intermediates(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    (capture_dir / "colmap").mkdir()
    _settle(capture_dir)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("clean.ply", b"ply\ncleaned", "application/octet-stream")},
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert not (capture_dir / "colmap").exists()


def test_confirm_does_not_reclaim_while_a_cli_run_is_in_flight(
    app: FastAPI, tmp_path: Path
) -> None:
    """C2: `_prune_after_review` guarded only on the JobRunner, which knows
    nothing about CLI processes. A CLI `resume`/`add-video` touches neither
    the JobRunner nor WatcherState, so the WebUI shows the capture as `done`
    and offers the review button — and confirming rmtree'd frames/ and colmap/
    out from under the running process. Task 7 fixed exactly this class of bug
    for the grace sweep with `lifecycle.recently_active`; this route was
    written before that helper existed and never revisited.

    The review itself must still stand: a discarded sign-off is lost manual
    work, unreclaimed space is cosmetic (and the sweep retries it later).
    """
    capture_dir = _make_capture(tmp_path)
    (capture_dir / "colmap").mkdir()
    # Fresh mtime — indistinguishable from a CLI rebuild writing right now.
    (capture_dir / "colmap" / "blob").write_bytes(b"x" * 10)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post("/captures/2026-07-19_lgs/review/confirm", follow_redirects=False)

    assert r.status_code == 303
    assert (capture_dir / "colmap" / "blob").exists()
    assert (capture_dir / "output" / ".review.json").exists()


def test_upload_does_not_reclaim_while_a_cli_run_is_in_flight(app: FastAPI, tmp_path: Path) -> None:
    """Same guard on the other review entry point."""
    capture_dir = _make_capture(tmp_path)
    (capture_dir / "colmap").mkdir()
    (capture_dir / "colmap" / "blob").write_bytes(b"x" * 10)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"ply\ncleaned", "application/octet-stream")},
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert (capture_dir / "colmap" / "blob").exists()
    assert (capture_dir / "output" / "scene_reviewed.ply").exists()
