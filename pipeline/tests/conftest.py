# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared test fixtures for the autosplat test suite."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from autosplat import cleanup as cleanup_mod
from autosplat import cli as cli_mod
from autosplat import migration as migration_mod
from autosplat.webui import share as share_mod
from autosplat.webui import share_runner as share_runner_mod
from autosplat.webui.routes import captures as captures_mod


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def packaged_default_config(repo_root: Path) -> Path:
    return repo_root / "config" / "default.toml"


@pytest.fixture
def tmp_capture_dir(tmp_path: Path) -> Path:
    d = tmp_path / "capture"
    d.mkdir()
    return d


# --- Structural backstop: no test may ever reclaim real captures ------------
#
# Tests redirecting `captures_dir` to a temp dir is protection by convention:
# it only helps if every test (present and future) actually does it. Given what
# is at stake — the maintainer's real, irreplaceable ~/AutoSplat (19 GB) — it is
# enforced here too. A near-miss already occurred: a dry-run preview launched
# against the real $HOME.
#
# This lives in `tests/conftest.py`, not `tests/webui/conftest.py`, because the
# risk is suite-wide: `tests/test_cleanup.py` calls `sweep_expired` directly and
# `tests/test_cli_migrate_storage.py` drives a CLI that rmtrees config-supplied
# paths — neither was covered while the guard sat under `tests/webui/`.
#
# Two `cleanup` functions and five independent `shutil.rmtree` bindings are
# wrapped, covering every way the suite can delete a capture tree:
# `cleanup.sweep_expired`, `cleanup.prune_intermediates` (which every
# deletion path except the ones below goes through), and `shutil.rmtree`
# bound separately in `cli_mod`, `migration_mod`, `captures_mod`, `share_mod`
# and `share_runner_mod` — each of those five does its own `import shutil`
# and so holds its own independent module-level binding; patching fewer than
# all five leaves the others' call sites invisible to this guard. Each binds:
#   - `cli_mod.shutil`: `cli.py`'s own `clean-bisection-probes` command.
#   - `migration_mod.shutil`: `migration.apply_migration`'s `outputs_reclaim`
#     branch — what both `migrate-storage --apply` and the WebUI's
#     `/storage/reclaim` button call.
#   - `captures_mod.shutil`: `webui/routes/captures.py`'s `POST
#     /captures/{id}/delete` — a full capture-tree deletion, not bounded to
#     any subdirectory.
#   - `share_mod.shutil`: `webui/share.py`'s `assemble_bundle`, which clears
#     a stale `share/<token>/` folder before rebuilding it. Bounded to
#     `share/`.
#   - `share_runner_mod.shutil`: `webui/share_runner.py`'s
#     `build_share_bundle`, which clears `share/_tmp/`. Also bounded to
#     `share/`.
# (round-2 review finding: a self-test asserted on the `cli_mod.shutil`
# wrapper directly, which made it pass whether or not `migration_mod.shutil`
# was actually guarded — see
# `test_guard_blocks_migration_apply_migration_rmtree_outside_the_pytest_temp_root`
# in `tests/test_cleanup.py`. A later review round found `captures_mod`,
# `share_mod` and `share_runner_mod` still unguarded one module over — see
# `test_guard_blocks_capture_delete_route_rmtree_outside_the_pytest_temp_root`
# in the same file, which drives the production `POST
# /captures/{id}/delete` route rather than the wrapper.)
# Each call with a path outside pytest's temp root raises immediately — before a
# single file is touched — and is recorded; `_fail_on_recorded_storage_violations`
# turns that into a hard test failure even if the raise happened on a background
# thread whose exception nobody observes.

_SWEEP_THREAD_NAME = "autosplat-grace-sweep"
_RECLAIM_THREAD_NAME = "autosplat-reclaim"
_GUARDED_THREAD_NAMES = (_SWEEP_THREAD_NAME, _RECLAIM_THREAD_NAME)
_violations: list[str] = []
_violations_lock = threading.Lock()


def _record_and_raise(what: str, path: Path, base_temp: Path) -> None:
    msg = (
        f"{what} called with path={path!s}, which is outside the pytest temp "
        f"root ({base_temp!s}). This would touch REAL captures — fix the test "
        "to redirect the path to a tmp_path."
    )
    with _violations_lock:
        _violations.append(msg)
    raise RuntimeError(msg)


@pytest.fixture(scope="session", autouse=True)
def _guard_reclaim_never_touches_real_captures(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    base_temp = tmp_path_factory.getbasetemp().resolve()

    def _check(what: str, path: Path) -> None:
        resolved = Path(path).resolve()
        if resolved != base_temp and base_temp not in resolved.parents:
            _record_and_raise(what, resolved, base_temp)

    real_sweep_expired = cleanup_mod.sweep_expired
    real_prune = cleanup_mod.prune_intermediates
    real_shutil = cli_mod.shutil

    def _guarded_sweep(captures_dir: Path, **kwargs: Any) -> Any:
        _check("cleanup.sweep_expired", captures_dir)
        return real_sweep_expired(captures_dir, **kwargs)

    def _guarded_prune(capture_dir: Path, **kwargs: Any) -> Any:
        _check("cleanup.prune_intermediates", capture_dir)
        for target in kwargs.get("targets") or []:
            _check("cleanup.prune_intermediates target", target)
        return real_prune(capture_dir, **kwargs)

    class _GuardedShutil:
        """Stands in for `shutil` inside `autosplat.cli` and `autosplat.migration`.

        Delegates everything but `rmtree`, and re-reads `rmtree` off the real
        module on each call so a test's own `monkeypatch.setattr(shutil,
        "rmtree", ...)` failure injection still takes effect underneath.
        """

        def rmtree(self, path: Any, *args: Any, **kwargs: Any) -> Any:
            _check("shutil.rmtree", path)
            return real_shutil.rmtree(path, *args, **kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(real_shutil, name)

    guarded_shutil = _GuardedShutil()

    cleanup_mod.sweep_expired = _guarded_sweep
    cleanup_mod.prune_intermediates = _guarded_prune
    cli_mod.shutil = guarded_shutil  # type: ignore[assignment]
    migration_mod.shutil = guarded_shutil  # type: ignore[assignment]
    captures_mod.shutil = guarded_shutil  # type: ignore[assignment]
    share_mod.shutil = guarded_shutil  # type: ignore[assignment]
    share_runner_mod.shutil = guarded_shutil  # type: ignore[assignment]
    try:
        yield
    finally:
        cleanup_mod.sweep_expired = real_sweep_expired
        cleanup_mod.prune_intermediates = real_prune
        cli_mod.shutil = real_shutil
        migration_mod.shutil = real_shutil
        captures_mod.shutil = real_shutil
        share_mod.shutil = real_shutil
        share_runner_mod.shutil = real_shutil


@pytest.fixture(autouse=True)
def _fail_on_recorded_storage_violations() -> Iterator[None]:
    """Per test: join any sweep/reclaim thread it started, then surface a hard
    failure if the guard above recorded an out-of-temp-dir call.

    Both the grace sweep (task 7) and the WebUI reclaim button (task 6) run on
    a background daemon thread, so without the join, a violation recorded
    just after the test body returns would race this check and could slip
    past undetected — doubly so for reclaim, whose `_run()` catches bare
    `Exception` and stashes it on the job instead of letting it surface, so
    the `_violations` list is the only signal left once that happens.
    """
    yield
    for thread in threading.enumerate():
        if thread.name in _GUARDED_THREAD_NAMES:
            thread.join(timeout=2)
    with _violations_lock:
        violations, _violations[:] = list(_violations), []
    if violations:
        pytest.fail("\n".join(violations))


@pytest.fixture
def storage_guard_violations() -> Iterator[list[str]]:
    """For the guard's own self-tests: exposes the recorded violations and
    drains them, so deliberately tripping the guard does not also fail the
    test via `_fail_on_recorded_storage_violations`."""
    with _violations_lock:
        _violations.clear()
    yield _violations
    with _violations_lock:
        _violations.clear()
