# SPDX-License-Identifier: AGPL-3.0-or-later

import time
from pathlib import Path

from autosplat.compress import CompressResult
from autosplat.config import load_config
from autosplat.webui.share_runner import ShareJobRunner


def _fake_embed(root: Path) -> Path:
    e = root / "embed"
    e.mkdir()
    (e / "index.html").write_text("<html>e</html>")
    return e


def _wait(job, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.02)


def test_share_job_compresses_and_bundles(tmp_path: Path) -> None:
    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY" * 5000)

    def fake_compress(ply: Path, out_dir: Path, *, fmt: str = "sog", quality: str = "medium"):
        out_dir.mkdir(parents=True, exist_ok=True)
        sog = out_dir / f"{ply.stem}.sog"
        sog.write_bytes(b"SOG" * 100)
        return CompressResult(
            output_path=sog,
            backend_used="fake",
            quality="medium",
            duration_s=0.1,
            input_bytes=15000,
            output_bytes=300,
        )

    cfg = load_config(include_xdg=False)
    cfg.share.base_url = "https://splat.example"
    cfg.share.embed_src_path = embed
    runner = ShareJobRunner(cfg, compressor=fake_compress)

    job = runner.start("2026-07-10_lgs", capture_dir)
    _wait(job)

    assert job.status == "done"
    assert job.token and job.token.startswith("lgs-")
    assert job.zip_path is not None and job.zip_path.exists()
    assert (capture_dir / "share" / job.token / "c" / "scene.sog").exists()
    assert job.output_bytes == 300 and job.input_bytes == 15000
    assert job.link == f"https://splat.example/{job.token}/?src=c/scene.sog"


def test_share_job_cleans_up_tmp_dir_after_success(tmp_path: Path) -> None:
    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY" * 5000)

    def fake_compress(ply: Path, out_dir: Path, *, fmt: str = "sog", quality: str = "medium"):
        out_dir.mkdir(parents=True, exist_ok=True)
        sog = out_dir / f"{ply.stem}.sog"
        sog.write_bytes(b"SOG" * 100)
        return CompressResult(
            output_path=sog,
            backend_used="fake",
            quality="medium",
            duration_s=0.1,
            input_bytes=15000,
            output_bytes=300,
        )

    cfg = load_config(include_xdg=False)
    cfg.share.embed_src_path = embed
    runner = ShareJobRunner(cfg, compressor=fake_compress)

    job = runner.start("2026-07-10_lgs", capture_dir)
    _wait(job)

    assert job.status == "done"
    assert not (capture_dir / "share" / "_tmp").exists()


def test_share_job_fails_without_ply(tmp_path: Path) -> None:
    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_empty"
    capture_dir.mkdir()
    cfg = load_config(include_xdg=False)
    cfg.share.embed_src_path = embed
    runner = ShareJobRunner(cfg)

    job = runner.start("2026-07-10_empty", capture_dir)
    _wait(job)

    assert job.status == "failed"
    assert job.error and "scene.ply" in job.error


def test_share_job_compresses_reviewed_ply_when_present(tmp_path: Path) -> None:
    import json

    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    output_dir = capture_dir / "output"
    output_dir.mkdir(parents=True)
    scene_ply = output_dir / "scene.ply"
    scene_ply.write_bytes(b"PLY" * 5000)
    reviewed_ply = output_dir / "scene_reviewed.ply"
    reviewed_ply.write_bytes(b"PLY-CLEANED" * 5000)
    (output_dir / ".review.json").write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": "2026-07-19T00:00:00",
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        )
    )

    compressed_paths = []

    def fake_compress(ply: Path, out_dir: Path, *, fmt: str = "sog", quality: str = "medium"):
        compressed_paths.append(ply)
        out_dir.mkdir(parents=True, exist_ok=True)
        sog = out_dir / f"{ply.stem}.sog"
        sog.write_bytes(b"SOG" * 100)
        return CompressResult(
            output_path=sog,
            backend_used="fake",
            quality="medium",
            duration_s=0.1,
            input_bytes=15000,
            output_bytes=300,
        )

    cfg = load_config(include_xdg=False)
    cfg.share.embed_src_path = embed
    runner = ShareJobRunner(cfg, compressor=fake_compress)

    job = runner.start("2026-07-10_lgs", capture_dir)
    _wait(job)

    assert job.status == "done"
    assert compressed_paths == [reviewed_ply]
