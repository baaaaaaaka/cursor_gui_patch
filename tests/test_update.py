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

    def test_app_only_path(self, tmp_path: Path):
        rel = mock.Mock(tag="v0.2.0", version="0.2.0")
        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch("cursor_gui_patch.update.get_github_repo", return_value="owner/repo"), \
             mock.patch("cursor_gui_patch.update.fetch_latest_release", return_value=rel), \
             mock.patch(
                 "cursor_gui_patch.update._resolve_install_dirs",
                 return_value=(tmp_path / "bin", tmp_path / "root"),
             ), \
             mock.patch("cursor_gui_patch.update._try_app_only_update", return_value="app-only"), \
             mock.patch("cursor_gui_patch.update.download_and_install_release_bundle") as full_update:
            ok, msg = perform_update()

        assert ok is True
        assert "app-only" in msg
        full_update.assert_not_called()

    def test_full_update_path(self, tmp_path: Path):
        rel = mock.Mock(tag="v0.2.0", version="0.2.0")
        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch("cursor_gui_patch.update.get_github_repo", return_value="owner/repo"), \
             mock.patch("cursor_gui_patch.update.fetch_latest_release", return_value=rel), \
             mock.patch(
                 "cursor_gui_patch.update._resolve_install_dirs",
                 return_value=(tmp_path / "bin", tmp_path / "root"),
             ), \
             mock.patch("cursor_gui_patch.update._try_app_only_update", return_value=None), \
             mock.patch(
                 "cursor_gui_patch.update.select_release_asset_name",
                 return_value="cgp-linux-x86_64.tar.gz",
             ), \
             mock.patch("cursor_gui_patch.update.download_and_install_release_bundle") as full_update:
            ok, msg = perform_update()

        assert ok is True
        assert msg == "updated to 0.2.0"
        full_update.assert_called_once()

    def test_returns_error_on_exception(self):
        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch("cursor_gui_patch.update.get_github_repo", return_value="owner/repo"), \
             mock.patch("cursor_gui_patch.update.fetch_latest_release", side_effect=RuntimeError("boom")):
            ok, msg = perform_update()

        assert ok is False
        assert "boom" in msg


class TestAutoUpdateExec:
    def test_reexecs_on_unix_after_successful_update(self):
        status = UpdateStatus(
            supported=True,
            method="github_release",
            installed_version="0.1.0",
            remote_version="0.2.0",
            repo="owner/repo",
            asset_name="cgp-linux-x86_64.tar.gz",
            update_available=True,
            error=None,
        )

        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch("cursor_gui_patch.update._should_check_update", return_value=True), \
             mock.patch("cursor_gui_patch.update.check_for_update", return_value=status), \
             mock.patch("cursor_gui_patch.update.perform_update", return_value=(True, "ok")), \
             mock.patch("cursor_gui_patch.update.sys.platform", "linux"), \
             mock.patch("cursor_gui_patch.update.os.execvp", side_effect=RuntimeError("reexec")) as execvp:
            with pytest.raises(RuntimeError, match="reexec"):
                auto_update_if_needed(["cgp", "status"])

        execvp.assert_called_once()

    def test_reexecs_on_windows_after_successful_update(self):
        status = UpdateStatus(
            supported=True,
            method="github_release",
            installed_version="0.1.0",
            remote_version="0.2.0",
            repo="owner/repo",
            asset_name="cgp-windows-x86_64.zip",
            update_available=True,
            error=None,
        )

        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch("cursor_gui_patch.update._should_check_update", return_value=True), \
             mock.patch("cursor_gui_patch.update.check_for_update", return_value=status), \
             mock.patch("cursor_gui_patch.update.perform_update", return_value=(True, "ok")), \
             mock.patch("cursor_gui_patch.update.sys.platform", "win32"), \
             mock.patch("cursor_gui_patch.update.subprocess.call", return_value=7), \
             mock.patch("cursor_gui_patch.update.sys.exit", side_effect=SystemExit(7)) as exit_mock:
            with pytest.raises(SystemExit) as ex:
                auto_update_if_needed(["cgp", "status"])

        assert ex.value.code == 7
        exit_mock.assert_called_once_with(7)

    def test_no_reexec_when_update_fails(self):
        status = UpdateStatus(
            supported=True,
            method="github_release",
            installed_version="0.1.0",
            remote_version="0.2.0",
            repo="owner/repo",
            asset_name="cgp-linux-x86_64.tar.gz",
            update_available=True,
            error=None,
        )

        with mock.patch("cursor_gui_patch.update.is_frozen_binary", return_value=True), \
             mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch("cursor_gui_patch.update._should_check_update", return_value=True), \
             mock.patch("cursor_gui_patch.update.check_for_update", return_value=status), \
             mock.patch("cursor_gui_patch.update.perform_update", return_value=(False, "boom")), \
             mock.patch("cursor_gui_patch.update.os.execvp") as execvp, \
             mock.patch("cursor_gui_patch.update.subprocess.call") as sp_call:
            auto_update_if_needed(["cgp", "status"])

        execvp.assert_not_called()
        sp_call.assert_not_called()
