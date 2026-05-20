# SPDX-License-Identifier: AGPL-3.0-or-later

"""WebUI smoke tests — verify all KSP-migrated surfaces render correctly.

Covers the seven Kuro Signal Protocol surfaces (dashboard, captures-list,
jobs, source + the base.html shell), the vendored static assets, and the
HTMX partial routes. Each test boots the FastAPI app via the shared `app`
fixture and asserts status code plus a markup marker.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.testclient import TestClient


def test_dashboard_renders_ksp(app: FastAPI) -> None:
    """GET / → 200, contains KSP shell markers."""
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    assert 'class="as-top"' in r.text
    assert 'class="as-side"' in r.text
    assert "as-frame" in r.text
    assert 'data-aspect="shugo"' in r.text


def test_captures_list_renders_ksp(app: FastAPI) -> None:
    """GET /captures/ → 200, contains as-poll-region with 3s polling."""
    with TestClient(app) as client:
        r = client.get("/captures/")
    assert r.status_code == 200
    assert 'class="as-poll-region"' in r.text
    assert 'hx-trigger="every 3s"' in r.text


def test_jobs_renders_ksp(app: FastAPI) -> None:
    """GET /jobs/ → 200, contains as-poll-region with 2s polling."""
    with TestClient(app) as client:
        r = client.get("/jobs/")
    assert r.status_code == 200
    assert 'class="as-poll-region"' in r.text
    assert 'hx-trigger="every 2s"' in r.text


def test_source_renders_ksp(app: FastAPI) -> None:
    """GET /source → 200, contains AGPL text + Codeberg link."""
    with TestClient(app) as client:
        r = client.get("/source")
    assert r.status_code == 200
    assert "AGPL-3.0-or-later" in r.text
    assert "codeberg.org/jkaindl/video-to-3d-gaussian-splat" in r.text


def test_static_tokens_css(app: FastAPI) -> None:
    """GET /static/css/tokens.css → 200, contains a KSP signal token."""
    with TestClient(app) as client:
        r = client.get("/static/css/tokens.css")
    assert r.status_code == 200
    assert "--signal-phosphor" in r.text


def test_static_autosplat_css(app: FastAPI) -> None:
    """GET /static/css/autosplat.css → 200, contains the frame grid class."""
    with TestClient(app) as client:
        r = client.get("/static/css/autosplat.css")
    assert r.status_code == 200
    assert ".as-frame" in r.text


def test_static_htmx_js(app: FastAPI) -> None:
    """GET /static/js/htmx.min.js → 200 (vendored locally, no CDN)."""
    with TestClient(app) as client:
        r = client.get("/static/js/htmx.min.js")
    assert r.status_code == 200
    assert len(r.text) > 10_000


def test_partial_dashboard(app: FastAPI) -> None:
    """GET /partials/dashboard → 200, HTML fragment with as-main-inner."""
    with TestClient(app) as client:
        r = client.get("/partials/dashboard")
    assert r.status_code == 200
    assert 'class="as-main-inner"' in r.text


def test_partial_jobs(app: FastAPI) -> None:
    """GET /partials/jobs → 200, HTML fragment with as-main-inner."""
    with TestClient(app) as client:
        r = client.get("/partials/jobs")
    assert r.status_code == 200
    assert 'class="as-main-inner"' in r.text


def test_partial_jobs_renders_cancelled_status(app: FastAPI) -> None:
    """SF-G3-2: a cancelled JobState renders an explicit 'cancelled' badge.

    Before the fix, capture_badge (which jobs_inner.html used) had no branch
    for JobState.status == 'cancelled', so cancelled jobs rendered as a
    grey 'ready' badge — misleading because the run had actually been
    aborted, not idle.
    """
    from autosplat.webui.jobs_runner import JobState

    runner = app.state.job_runner
    aborted = JobState(capture_id="2026-05-20_user_abort", status="cancelled")
    runner._history.append(aborted)

    with TestClient(app) as client:
        r = client.get("/partials/jobs")
    assert r.status_code == 200
    # Badge text appears inside as-stage-badge span — check the label, not
    # the capture id, by anchoring on the closing </span>.
    assert "cancelled</span>" in r.text, (
        "Expected a 'cancelled' badge label; got body without it. "
        "capture_badge probably still falls through to 's-ready'."
    )


def test_partial_captures(app: FastAPI) -> None:
    """GET /partials/captures → 200, HTML fragment (HTMX self-renewal target)."""
    with TestClient(app) as client:
        r = client.get("/partials/captures")
    assert r.status_code == 200
    assert 'class="as-main-inner"' in r.text
