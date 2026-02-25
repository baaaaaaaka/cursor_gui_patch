"""Tests for cursor_gui_patch.update."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

import pytest

from cursor_gui_patch.update import (
    UPDATE_CHECK_INTERVAL_S,
    UpdateStatus,
    _last_check_path,
    _record_check_time,
    _should_check_update,
    auto_update_if_needed,
    check_for_update,
    perform_update,
)


class TestShouldCheckUpdate:
    def test_no_file(self, tmp_path: Path):
        with mock.patch("cursor_gui_patch.update._last_check_path", return_value=tmp_path / "nofile"):
            assert _should_check_update() is True

    def test_recent_check(self, tmp_path: Path):
        p = tmp_path / ".last-update-check"
        p.write_text(str(time.time()), encoding="utf-8")
        with mock.patch("cursor_gui_patch.update._last_check_path", return_value=p):
            assert _should_check_update() is False

    def test_old_check(self, tmp_path: Path):
        p = tmp_path / ".last-update-check"
        p.write_text(str(time.time() - UPDATE_CHECK_INTERVAL_S - 10), encoding="utf-8")
        with mock.patch("cursor_gui_patch.update._last_check_path", return_value=p):
            assert _should_check_update() is True


class TestCheckForUpdate:
    def test_not_frozen(self):
        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=False):
            result = check_for_update()
            assert result is not None
            assert result.supported is False
            assert "not a frozen binary" in (result.error or "")

    def test_frozen_newer_available(self, tmp_path: Path):
        body = json.dumps({"tag_name": "v0.2.0"}).encode()

        def fake_fetch(url, timeout_s, headers):
            return body

        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch("cursor_gui_patch.update.select_release_asset_name", return_value="cgp-linux-x86_64.tar.gz"), \
             mock.patch("cursor_gui_patch.update._last_check_path", return_value=tmp_path / ".ts"):
            result = check_for_update(fetch=fake_fetch)
            assert result is not None
            assert result.update_available is True
            assert result.remote_version == "0.2.0"

    def test_frozen_same_version(self, tmp_path: Path):
        from cursor_gui_patch import __version__
        body = json.dumps({"tag_name": f"v{__version__}"}).encode()

        def fake_fetch(url, timeout_s, headers):
            return body

        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch("cursor_gui_patch.update.select_release_asset_name", return_value="cgp-linux-x86_64.tar.gz"), \
             mock.patch("cursor_gui_patch.update._last_check_path", return_value=tmp_path / ".ts"):
            result = check_for_update(fetch=fake_fetch)
            assert result is not None
            assert result.update_available is False

    def test_network_error(self, tmp_path: Path):
        def failing_fetch(url, timeout_s, headers):
            raise ConnectionError("no internet")

        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch("cursor_gui_patch.update._last_check_path", return_value=tmp_path / ".ts"):
            result = check_for_update(fetch=failing_fetch)
            assert result is not None
            assert result.supported is False
            assert "no internet" in (result.error or "")


class TestAutoUpdateIfNeeded:
    def test_skips_if_not_frozen(self):
        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=False):
            auto_update_if_needed(["cgp", "patch"])
            # Should return without doing anything

    def test_skips_if_env_set(self):
        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch.dict("os.environ", {"CGP_NO_AUTO_UPDATE": "1"}):
            auto_update_if_needed(["cgp", "patch"])

    def test_skips_if_already_updated(self):
        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch.dict("os.environ", {"_CGP_UPDATED": "1"}, clear=False):
            auto_update_if_needed(["cgp", "patch"])

    def test_skips_if_recent_check(self):
        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch("cursor_gui_patch.update._should_check_update", return_value=False):
            auto_update_if_needed(["cgp", "patch"])


class TestPerformUpdate:
    def test_not_frozen(self):
        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=False):
            ok, msg = perform_update()
            assert ok is False
            assert "not a frozen binary" in msg
