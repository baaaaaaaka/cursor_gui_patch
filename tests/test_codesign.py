"""Tests for cursor_gui_patch.codesign."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

from cursor_gui_patch.codesign import (
    _find_app_bundle,
    codesign_app,
    needs_codesign,
    remove_quarantine,
)


def _make_app_root(tmp_path: Path) -> tuple[Path, Path]:
    app_bundle = tmp_path / "Cursor.app"
    app_root = app_bundle / "Contents" / "Resources" / "app"
    app_root.mkdir(parents=True)
    (app_bundle / "Contents" / "Info.plist").write_text("plist", encoding="utf-8")
    return app_root, app_bundle


class TestFindAppBundle:
    def test_finds_bundle_upwards(self, tmp_path: Path):
        app_root, app_bundle = _make_app_root(tmp_path)
        assert _find_app_bundle(app_root) == app_bundle

    def test_returns_none_if_not_inside_app(self, tmp_path: Path):
        root = tmp_path / "not-app" / "resources" / "app"
        root.mkdir(parents=True)
        assert _find_app_bundle(root) is None


class TestNeedsCodesign:
    def test_false_on_non_macos(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "linux"):
            assert needs_codesign(app_root, "gui") is False

    def test_false_for_server(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"):
            assert needs_codesign(app_root, "server") is False

    def test_true_for_gui_app_on_macos(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"):
            assert needs_codesign(app_root, "gui") is True


class TestCodesignApp:
    def test_skips_on_non_macos(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "linux"):
            res = codesign_app(app_root)
        assert res.success is False
        assert res.skipped_reason == "not macOS"

    def test_missing_codesign_binary(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", return_value=None):
            res = codesign_app(app_root)
        assert res.needed is True
        assert "not found" in res.error

    def test_no_app_bundle_found(self, tmp_path: Path):
        root = tmp_path / "plain-dir"
        root.mkdir()
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", return_value="/usr/bin/codesign"):
            res = codesign_app(root)
        assert res.success is False
        assert res.skipped_reason == "no .app bundle found"

    def test_codesign_success(self, tmp_path: Path):
        app_root, app_bundle = _make_app_root(tmp_path)
        proc = subprocess.CompletedProcess(args=["codesign"], returncode=0, stdout="", stderr="")
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", return_value="/usr/bin/codesign"), \
             mock.patch("cursor_gui_patch.codesign.subprocess.run", return_value=proc):
            res = codesign_app(app_root)
        assert res.needed is True
        assert res.success is True
        assert res.app_path == app_bundle

    def test_codesign_failure(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        proc = subprocess.CompletedProcess(args=["codesign"], returncode=1, stdout="", stderr="boom")
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", return_value="/usr/bin/codesign"), \
             mock.patch("cursor_gui_patch.codesign.subprocess.run", return_value=proc):
            res = codesign_app(app_root)
        assert res.success is False
        assert res.error == "boom"

    def test_codesign_timeout(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", return_value="/usr/bin/codesign"), \
             mock.patch(
                 "cursor_gui_patch.codesign.subprocess.run",
                 side_effect=subprocess.TimeoutExpired(cmd="codesign", timeout=120),
             ):
            res = codesign_app(app_root)
        assert res.success is False
        assert "timed out" in res.error


class TestRemoveQuarantine:
    def test_false_on_non_macos(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "linux"):
            assert remove_quarantine(app_root) is False

    def test_false_when_xattr_missing(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", return_value=None):
            assert remove_quarantine(app_root) is False

    def test_true_when_xattr_runs(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", return_value="/usr/bin/xattr"), \
             mock.patch("cursor_gui_patch.codesign.subprocess.run", return_value=None):
            assert remove_quarantine(app_root) is True

    def test_false_when_xattr_raises(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", return_value="/usr/bin/xattr"), \
             mock.patch("cursor_gui_patch.codesign.subprocess.run", side_effect=RuntimeError("xattr failed")):
            assert remove_quarantine(app_root) is False
