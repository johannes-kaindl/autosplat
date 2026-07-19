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

from autosplat.compress import CompressResult, compress_ply
from autosplat.config import Config
from autosplat.logging import get_logger
from autosplat.webui.share import assemble_bundle, make_share_token, share_link
from autosplat.webui.state import _review_status, resolve_publish_ply

logger = get_logger(__name__)

ShareStatus = Literal["running", "done", "failed"]

Compressor = Callable[..., CompressResult]


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
            review_status = _review_status(capture_dir)
            ply = resolve_publish_ply(capture_dir, review_status)
            if ply is None or not ply.exists():
                raise FileNotFoundError(f"No output/scene.ply in {capture_dir}")

            result = self._compress(
                ply,
                capture_dir / "share" / "_tmp",
                fmt="sog",
                quality=self._cfg.compress.quality,
            )
            token = make_share_token(job.capture_id)
            embed_src = self._resolve_embed_src()
            paths = assemble_bundle(result.output_path, embed_src, capture_dir / "share", token)
            shutil.rmtree(capture_dir / "share" / "_tmp", ignore_errors=True)

            job.token = token
            job.zip_path = paths.zip_path
            job.output_bytes = result.output_bytes
            job.input_bytes = result.input_bytes
            job.link = share_link(self._cfg.share.base_url, token)
            job.status = "done"
            logger.info("share.done", capture_id=job.capture_id, token=token)
        except Exception as e:  # surfaced on the job, not raised
            job.status = "failed"
            job.error = str(e)
            logger.error("share.failed", capture_id=job.capture_id, error=str(e))

    def _resolve_embed_src(self) -> Path:
        p = self._cfg.share.embed_src_path
        return p if p.is_absolute() else (Path.cwd() / p)
