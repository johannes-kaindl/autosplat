# SPDX-License-Identifier: AGPL-3.0-or-later

"""Background runner for share-bundle jobs.

Kept separate from the pipeline JobRunner: a share job must NOT flip the
capture's status to 'running' — the capture stays 'done' and only the share
card reflects bundle progress.
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from autosplat import resources
from autosplat.compress import CompressResult, compress_ply
from autosplat.config import Config
from autosplat.lifecycle import resolve_publish_ply, review_status
from autosplat.logging import get_logger
from autosplat.webui.share import assemble_bundle, make_share_token, share_link

logger = get_logger(__name__)

ShareStatus = Literal["running", "done", "failed"]

Compressor = Callable[..., CompressResult]


class UnreviewedCapture(Exception):
    """Raised when a capture is asked to be shared before it was reviewed.

    The publish quality gate used to live only in `capture_share`, while this
    module would bundle an unreviewed capture without complaint. That was
    survivable while the WebUI was the only caller; it stops being survivable
    the moment a CLI command exists.
    """


@dataclass(frozen=True)
class ShareResult:
    token: str
    zip_path: Path
    output_bytes: int
    input_bytes: int
    link: str | None


def build_share_bundle(
    cfg: Config,
    capture_dir: Path,
    capture_id: str,
    *,
    compressor: Compressor = compress_ply,
) -> ShareResult:
    """Compress to SOG and assemble a share bundle. Synchronous; raises.

    Refuses an unreviewed capture — the gate lives here so that every
    surface inherits it instead of re-implementing it.
    """
    status = review_status(capture_dir)
    if status == "unreviewed":
        raise UnreviewedCapture(
            f"{capture_dir.name} has not been reviewed — review it before sharing"
        )
    ply = resolve_publish_ply(capture_dir, status)
    if ply is None or not ply.exists():
        raise FileNotFoundError(f"No output/scene.ply in {capture_dir}")

    # The SOG is a durable artifact under output/, kept per the retention
    # policy and reused by later shares — a repeat share becomes seconds.
    sog = capture_dir / "output" / "scene.sog"
    if sog.exists() and sog.stat().st_mtime >= ply.stat().st_mtime:
        logger.info("share.sog_reused", capture_id=capture_id)
    else:
        result = compressor(ply, capture_dir / "output", fmt="sog", quality=cfg.compress.quality)
        # compress_ply names its output after the input stem, so a reviewed
        # capture would yield scene_reviewed.sog. The canonical name is
        # scene.sog regardless of which PLY was published.
        if result.output_path != sog:
            result.output_path.replace(sog)

    token = make_share_token(capture_id)
    embed_src = cfg.share.embed_src_path
    if not embed_src.is_absolute():
        embed_src = resources.REPO_ROOT / embed_src
    paths = assemble_bundle(sog, embed_src, capture_dir / "share", token)
    shutil.rmtree(capture_dir / "share" / "_tmp", ignore_errors=True)

    return ShareResult(
        token=token,
        zip_path=paths.zip_path,
        output_bytes=sog.stat().st_size,
        input_bytes=ply.stat().st_size,
        link=share_link(cfg.share.base_url, token),
    )


@dataclass
class ShareJob:
    capture_id: str
    status: ShareStatus = "running"
    token: str | None = None
    zip_path: Path | None = None
    output_bytes: int | None = None
    input_bytes: int | None = None
    link: str | None = None
    error: str | None = None
    _thread: threading.Thread | None = field(default=None, repr=False)


class ShareJobRunner:
    def __init__(self, cfg: Config, compressor: Compressor = compress_ply) -> None:
        self._cfg = cfg
        self._compress = compressor
        self._jobs: dict[str, ShareJob] = {}

    def get(self, capture_id: str) -> ShareJob | None:
        return self._jobs.get(capture_id)

    def start(self, capture_id: str, capture_dir: Path) -> ShareJob:
        existing = self._jobs.get(capture_id)
        if existing is not None and existing.status == "running":
            return existing
        job = ShareJob(capture_id=capture_id)
        self._jobs[capture_id] = job
        thread = threading.Thread(
            target=self._run,
            args=(job, capture_dir),
            daemon=True,
            name=f"autosplat-share-{capture_id}",
        )
        job._thread = thread
        thread.start()
        return job

    def _run(self, job: ShareJob, capture_dir: Path) -> None:
        try:
            result = build_share_bundle(
                self._cfg, capture_dir, job.capture_id, compressor=self._compress
            )
        except Exception as e:  # surfaced on the job, not raised
            job.status = "failed"
            job.error = str(e)
            logger.error("share.failed", capture_id=job.capture_id, error=str(e))
            return
        job.token = result.token
        job.zip_path = result.zip_path
        job.output_bytes = result.output_bytes
        job.input_bytes = result.input_bytes
        job.link = result.link
        job.status = "done"
        logger.info("share.done", capture_id=job.capture_id, token=result.token)
