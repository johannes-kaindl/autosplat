# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared fixtures for WebUI tests."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI

from autosplat import cleanup as cleanup_mod
from autosplat.cleanup import PruneResult
from autosplat.config import load_config
from autosplat.webui import create_app


@pytest.fixture()
def app(tmp_path_factory: pytest.TempPathFactory) -> FastAPI:
    """FastAPI app built from the packaged default config.

    captures_dir is redirected to a temp dir: tests must never read — let alone
    reclaim — the real ~/AutoSplat/captures. Individual tests still override it
    with their own tmp_path where they need to place fixtures.
    """
    cfg = load_config(include_xdg=False)
    cfg.paths.captures_dir = tmp_path_factory.mktemp("captures")
    return create_app(cfg)


# --- Structural backstop for the fixture above -----------------------------
#
# The `app` fixture redirecting captures_dir to a temp dir is protection by
# convention: it only helps if every test (present and future) actually goes
# through it, or overrides captures_dir itself before entering a TestClient.
# Given what's at stake — the maintainer's real, irreplaceable captures — that
# is enforced here too: `cleanup.sweep_expired` is wrapped for the whole
# session so any call with a captures_dir outside pytest's own temp root
# raises immediately (blocking the reclaim before it can touch a single file)
# and is recorded; `_fail_on_recorded_sweep_violations` turns that into a hard
# test failure.

_SWEEP_THREAD_NAME = "autosplat-grace-sweep"
_sweep_violations: list[str] = []
_sweep_violations_lock = threading.Lock()


@pytest.fixture(scope="session", autouse=True)
def _guard_sweep_never_touches_real_captures(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    real_sweep_expired = cleanup_mod.sweep_expired
    base_temp = tmp_path_factory.getbasetemp().resolve()

    def _guarded(captures_dir: Path, *, grace_days: int, now: datetime) -> list[PruneResult]:
        resolved = Path(captures_dir).resolve()
        if resolved != base_temp and base_temp not in resolved.parents:
            msg = (
                f"cleanup.sweep_expired called with captures_dir={resolved!s}, "
                f"which is outside the pytest temp root ({base_temp!s}). This "
                "would reclaim REAL captures — fix the test to redirect "
                "captures_dir to a tmp_path before entering a TestClient."
            )
            with _sweep_violations_lock:
                _sweep_violations.append(msg)
            raise RuntimeError(msg)
        return real_sweep_expired(captures_dir, grace_days=grace_days, now=now)

    cleanup_mod.sweep_expired = _guarded
    try:
        yield
    finally:
        cleanup_mod.sweep_expired = real_sweep_expired


@pytest.fixture(autouse=True)
def _fail_on_recorded_sweep_violations() -> Iterator[None]:
    """Per test: join any sweep thread it started, then surface a hard
    failure if the guard above recorded an out-of-temp-dir call.

    The sweep runs on a background daemon thread (task 7), so without the
    join, a violation recorded just after the test body returns would race
    this check and could slip past undetected.
    """
    yield
    for thread in threading.enumerate():
        if thread.name == _SWEEP_THREAD_NAME:
            thread.join(timeout=2)
    with _sweep_violations_lock:
        violations, _sweep_violations[:] = list(_sweep_violations), []
    if violations:
        pytest.fail("\n".join(violations))
