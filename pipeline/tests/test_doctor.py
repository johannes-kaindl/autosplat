"""Doctor: aggregation and required/optional handling."""

from __future__ import annotations

from pathlib import Path

from autosplat.config import load_config
from autosplat.doctor import CheckResult, _check_supersplat, all_required_passed


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_minimal_config(tmp_path: Path, *, viewer_target: str = "supersplat"):
    """Return a minimal Config with the given viewer target and default dist path."""
    user = tmp_path / "config.toml"
    user.write_text(
        f'[viewer]\ntarget = "{viewer_target}"\n',
        encoding="utf-8",
    )
    return load_config(user_config_path=user, include_xdg=False)


def make_config_with_supersplat_local(*, dist_path: Path, tmp_path: Path):
    """Return a Config with target=supersplat-local and the given dist path."""
    user = tmp_path / "config.toml"
    user.write_text(
        f'[viewer]\ntarget = "supersplat-local"\nsupersplat_dist_path = "{dist_path}"\n',
        encoding="utf-8",
    )
    return load_config(user_config_path=user, include_xdg=False)


def test_all_required_passed_true() -> None:
    results = [
        CheckResult(name="a", ok=True, detail="x", required=True),
        CheckResult(name="b", ok=False, detail="y", required=False),
    ]
    assert all_required_passed(results) is True


def test_all_required_passed_false() -> None:
    results = [
        CheckResult(name="a", ok=True, detail="x", required=True),
        CheckResult(name="b", ok=False, detail="y", required=True),
    ]
    assert all_required_passed(results) is False


def test_status_emoji_ok() -> None:
    r = CheckResult(name="a", ok=True, detail="x")
    assert r.status_emoji == "OK"


def test_status_emoji_missing_required() -> None:
    r = CheckResult(name="a", ok=False, detail="x", required=True)
    assert r.status_emoji == "MISSING"


def test_status_emoji_missing_optional() -> None:
    r = CheckResult(name="a", ok=False, detail="x", required=False)
    assert r.status_emoji == "WARN"


# ─── _check_supersplat ────────────────────────────────────────────────────────


def test_check_supersplat_ok(tmp_path: Path) -> None:
    """dist/index.html exists → OK."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html/>")
    cfg = make_config_with_supersplat_local(dist_path=dist, tmp_path=tmp_path)
    result = _check_supersplat(cfg)
    assert result is not None
    assert result.ok is True
    assert result.name == "supersplat"


def test_check_supersplat_warn_missing(tmp_path: Path) -> None:
    """dist/index.html missing → WARN (not required)."""
    dist = tmp_path / "dist"
    # don't create dist
    cfg = make_config_with_supersplat_local(dist_path=dist, tmp_path=tmp_path)
    result = _check_supersplat(cfg)
    assert result is not None
    assert result.ok is False
    assert result.required is False
    assert "setup_supersplat.sh" in result.detail


def test_check_supersplat_skipped_for_remote_target(tmp_path: Path) -> None:
    """target=supersplat (remote) → returns None (check skipped)."""
    cfg = _make_minimal_config(tmp_path, viewer_target="supersplat")
    result = _check_supersplat(cfg)
    assert result is None
