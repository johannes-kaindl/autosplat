# SPDX-License-Identifier: AGPL-3.0-or-later

import time
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from autosplat.compress import CompressResult
from autosplat.webui.share_runner import ShareJobRunner


def _fake_embed(root: Path) -> Path:
    e = root / "embed"
    e.mkdir()
    (e / "index.html").write_text("<html>e</html>")
    return e


def _mark_reviewed(capture_dir: Path) -> None:
    import json

    scene_ply = capture_dir / "output" / "scene.ply"
    marker = capture_dir / "output" / ".review.json"
    marker.write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": "2026-07-19T00:00:00",
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        )
    )


def _install(app: FastAPI, tmp_path: Path, *, reviewed: bool = True) -> Path:
    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY" * 5000)
    (capture_dir / "pipeline.log").write_text("done\n")
    app.state.cfg.paths.captures_dir = tmp_path
    app.state.cfg.share.embed_src_path = embed
    app.state.cfg.share.base_url = "https://splat.example"
    if reviewed:
        _mark_reviewed(capture_dir)

    def fake_compress(ply, out_dir, *, fmt="sog", quality="medium"):
        out_dir.mkdir(parents=True, exist_ok=True)
        sog = out_dir / f"{ply.stem}.sog"
        sog.write_bytes(b"SOG")
        return CompressResult(sog, "fake", "medium", 0.1, 15000, 3)

    app.state.share_runner = ShareJobRunner(app.state.cfg, compressor=fake_compress)
    return capture_dir


def test_post_share_starts_job_and_partial_shows_link(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path)
    with TestClient(app) as client:
        r = client.post("/captures/2026-07-10_lgs/share", follow_redirects=False)
        assert r.status_code == 303
        # let the background thread finish
        body = ""
        for _ in range(150):
            body = client.get("/partials/capture/2026-07-10_lgs/share").text
            if "https://splat.example/" in body:
                break
            time.sleep(0.02)
        assert "https://splat.example/lgs-" in body
        assert "share/lgs-" in body and ".zip" in body


def test_detail_page_shows_share_card_for_done_capture(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path)
    with TestClient(app) as client:
        body = client.get("/captures/2026-07-10_lgs").text
    assert "Create share bundle" in body
    assert "anyone with this link" in body.lower()


def test_share_zip_downloads(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path)
    with TestClient(app) as client:
        client.post("/captures/2026-07-10_lgs/share", follow_redirects=False)
        token = None
        for _ in range(150):
            job = app.state.share_runner.get("2026-07-10_lgs")
            if job and job.status == "done":
                token = job.token
                break
            time.sleep(0.02)
        assert token is not None
        r = client.get(f"/captures/2026-07-10_lgs/share/{token}.zip")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"


def test_post_share_redirects_to_view_when_unreviewed(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path, reviewed=False)
    with TestClient(app) as client:
        r = client.post("/captures/2026-07-10_lgs/share", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/captures/2026-07-10_lgs/view"
    # no share job was started
    assert app.state.share_runner.get("2026-07-10_lgs") is None
