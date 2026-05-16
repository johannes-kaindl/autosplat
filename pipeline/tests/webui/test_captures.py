# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for capture discovery and detail routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autosplat.webui.state import list_captures


def test_list_captures_empty_dir(tmp_path: Path) -> None:
    captures = list_captures(tmp_path)
    assert captures == []


def test_list_captures_with_fixture(tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-16_test_video"
    capture_dir.mkdir()
    (capture_dir / "output").mkdir()
    ply = capture_dir / "output" / "scene.ply"
    ply.write_bytes(b"ply\n")

    captures = list_captures(tmp_path)
    assert len(captures) == 1
    assert captures[0].id == "2026-05-16_test_video"
    assert captures[0].has_ply is True
    assert captures[0].ply_size_bytes == 4


def test_capture_ply_route_returns_200(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-16_ply_smoke"
    capture_dir.mkdir()
    output_dir = capture_dir / "output"
    output_dir.mkdir()
    ply = output_dir / "scene.ply"
    ply.write_bytes(b"ply\nformat binary 1.0\n")

    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.get("/captures/2026-05-16_ply_smoke/ply")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"


def test_capture_ply_route_returns_404_when_no_ply(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-16_no_ply"
    capture_dir.mkdir()

    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.get("/captures/2026-05-16_no_ply/ply")
    assert response.status_code == 404


def test_capture_detail_route_returns_200(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-16_smoke"
    capture_dir.mkdir()
    (capture_dir / "output").mkdir()
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n")

    # Override captures_dir in app config for this test
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.get("/captures/2026-05-16_smoke")
    assert response.status_code == 200
    assert "2026-05-16_smoke" in response.text
