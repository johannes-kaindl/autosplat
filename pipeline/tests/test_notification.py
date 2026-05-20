# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for notification.py."""
from __future__ import annotations

from unittest.mock import patch

from autosplat.notification import notify_training_complete


def test_notify_calls_osascript_on_macos():
    with (
        patch("autosplat.notification.platform.system", return_value="Darwin"),
        patch("autosplat.notification.subprocess.run") as mock_run,
    ):
        notify_training_complete("test_capture", 120.0, gaussians=50000)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "osascript" in call_args
        assert "test_capture" in mock_run.call_args[0][0][2]  # the script arg

def test_notify_no_op_on_non_macos():
    with (
        patch("autosplat.notification.platform.system", return_value="Linux"),
        patch("autosplat.notification.subprocess.run") as mock_run,
    ):
        notify_training_complete("test_capture", 60.0)
        mock_run.assert_not_called()

def test_notify_graceful_on_subprocess_exception():
    with (
        patch("autosplat.notification.platform.system", return_value="Darwin"),
        patch(
            "autosplat.notification.subprocess.run",
            side_effect=FileNotFoundError("osascript not found"),
        ),
    ):
        # Should not raise
        notify_training_complete("test_capture", 30.0)

def test_notify_duration_formatting_minutes():
    with (
        patch("autosplat.notification.platform.system", return_value="Darwin"),
        patch("autosplat.notification.subprocess.run") as mock_run,
    ):
        notify_training_complete("cap", 185.0)  # 3m 5s
        script = mock_run.call_args[0][0][2]
        assert "3m 5s" in script

def test_notify_duration_formatting_seconds_only():
    with (
        patch("autosplat.notification.platform.system", return_value="Darwin"),
        patch("autosplat.notification.subprocess.run") as mock_run,
    ):
        notify_training_complete("cap", 45.0)
        script = mock_run.call_args[0][0][2]
        assert "45s" in script
        assert "0m" not in script
