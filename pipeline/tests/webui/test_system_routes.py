# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autosplat.doctor import CheckResult
from autosplat.webui.routes import system as system_route


def test_system_page_lists_external_tools(app: FastAPI) -> None:
    with TestClient(app) as client:
        r = client.get("/system")
    assert r.status_code == 200
    body = r.text
    for tool in ("ffmpeg", "colmap", "brush"):
        assert tool in body


def test_system_page_reports_a_missing_bundled_viewer(app: FastAPI, tmp_path: Path) -> None:
    """The defect this page exists for: a missing viewer used to be invisible."""
    app.state.cfg.viewer.supersplat_dist_path = tmp_path / "nope"
    with TestClient(app) as client:
        r = client.get("/system")
    assert r.status_code == 200
    assert "supersplat" in r.text.lower()
    assert "missing" in r.text.lower()


def test_system_page_names_the_role_of_each_viewer(app: FastAPI) -> None:
    with TestClient(app) as client:
        body = client.get("/system").text
    # The charter, rendered: three viewers, three jobs.
    assert "clean up" in body.lower()
    assert "share" in body.lower()
    assert "walk" in body.lower()


def test_nav_links_to_system(app: FastAPI) -> None:
    """Trailing slash matches `/system`'s canonical `APIRouter(prefix="/system")`
    + `"/"` route — same shape as `/captures/` and `/jobs/` in this nav, which
    both already carry it. Linking the bare path costs an extra 307 per click."""
    with TestClient(app) as client:
        body = client.get("/").text
    assert 'href="/system/"' in body


def test_setup_button_hidden_when_no_tool_is_missing(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repair button on a healthy system is noise — it must only appear
    when `missing_required_tools`'s underlying checks actually report one."""
    monkeypatch.setattr(
        system_route,
        "run_doctor",
        lambda cfg: [CheckResult(name="colmap", ok=True, detail="1.2.3")],
    )
    with TestClient(app) as client:
        body = client.get("/system/").text
    assert "Run setup" not in body
    assert 'action="/system/setup"' not in body


def test_setup_button_shown_when_a_required_tool_is_missing(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        system_route,
        "run_doctor",
        lambda cfg: [CheckResult(name="colmap", ok=False, detail="not in PATH")],
    )
    with TestClient(app) as client:
        body = client.get("/system/").text
    assert "Run setup" in body
    assert 'action="/system/setup"' in body
    # The user must not be surprised by a Terminal window appearing.
    assert "Terminal" in body
    assert "password" in body.lower()


def test_setup_post_triggers_run_first_run_setup_once_with_bundled_script(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The POST must never itself shell out to osascript — only the injected
    stand-in is allowed to see the call. If this test opened a real Terminal
    window, it would be wrong."""
    script = tmp_path / "install_deps.sh"
    calls: list[Path] = []
    monkeypatch.setattr(system_route.desktop, "_bundled_install_script", lambda: script)
    monkeypatch.setattr(
        system_route.desktop, "run_first_run_setup", lambda s: calls.append(s)
    )

    with TestClient(app) as client:
        r = client.post("/system/setup")

    assert r.status_code == 200  # redirect to /system/ followed
    assert calls == [script]
    assert "Terminal" in r.text


def test_setup_post_surfaces_missing_install_script(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing resource is displayed, never silently hidden — even when the
    resource is the install script itself."""
    monkeypatch.setattr(system_route.desktop, "_bundled_install_script", lambda: None)
    triggered = False

    def _fail_if_called(*args: object, **kwargs: object) -> None:
        nonlocal triggered
        triggered = True

    monkeypatch.setattr(system_route.desktop, "run_first_run_setup", _fail_if_called)

    with TestClient(app) as client:
        r = client.post("/system/setup")

    assert r.status_code == 200
    assert triggered is False
    assert "install_deps.sh" in r.text
    assert "did not start" in r.text.lower() or "could not find" in r.text.lower()
