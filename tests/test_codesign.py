"""Tests for cursor_gui_patch.codesign."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

from cursor_gui_patch.codesign import (
    _find_app_bundle,
    _parse_security_identities,
    _resolve_preferred_identity,
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
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "linux"), \
             mock.patch("cursor_gui_patch.codesign.subprocess.run") as run_mock:
            res = codesign_app(app_root)
        assert res.success is False
        assert res.skipped_reason == "not macOS"
        run_mock.assert_not_called()

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

    def test_uses_explicit_identity_from_env(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        proc = subprocess.CompletedProcess(args=["codesign"], returncode=0, stdout="", stderr="")
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", return_value="/usr/bin/codesign"), \
             mock.patch.dict("cursor_gui_patch.codesign.os.environ", {"CGP_CODESIGN_IDENTITY": "My Stable ID"}, clear=False), \
             mock.patch("cursor_gui_patch.codesign.subprocess.run", return_value=proc) as run_mock:
            res = codesign_app(app_root)
        assert res.success is True
        assert res.identity_used == "My Stable ID"
        cmd = run_mock.call_args_list[0].args[0]
        assert "--sign" in cmd
        assert "My Stable ID" in cmd

    def test_falls_back_to_adhoc_when_preferred_identity_fails(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        fail_proc = subprocess.CompletedProcess(args=["codesign"], returncode=1, stdout="", stderr="bad id")
        ok_proc = subprocess.CompletedProcess(args=["codesign"], returncode=0, stdout="", stderr="")
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", side_effect=lambda n: f"/usr/bin/{n}"), \
             mock.patch("cursor_gui_patch.codesign.subprocess.run", side_effect=[
                 # security find-identity
                 subprocess.CompletedProcess(
                     args=["security"], returncode=0, stdout='  1) HASH "CGP Cursor Patch"\n', stderr=""
                 ),
                 # preferred identity fails
                 fail_proc,
                 # ad-hoc fallback succeeds
                 ok_proc,
             ]):
            res = codesign_app(app_root)
        assert res.success is True
        assert res.identity_requested == "CGP Cursor Patch"
        assert res.identity_used == "-"
        assert "fell back to ad-hoc" in res.warning

    def test_auto_uses_stable_identity_when_detected(self, tmp_path: Path):
        app_root, _ = _make_app_root(tmp_path)
        with mock.patch("cursor_gui_patch.codesign.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.codesign.shutil.which", side_effect=lambda n: f"/usr/bin/{n}"), \
             mock.patch("cursor_gui_patch.codesign.subprocess.run", side_effect=[
                 subprocess.CompletedProcess(
                     args=["security"], returncode=0, stdout='  1) HASH "CGP Cursor Patch"\n', stderr=""
                 ),
                 subprocess.CompletedProcess(args=["codesign"], returncode=0, stdout="", stderr=""),
             ]) as run_mock:
            res = codesign_app(app_root)
        assert res.success is True
        assert res.identity_requested == "CGP Cursor Patch"
        assert res.identity_used == "CGP Cursor Patch"
        cmd = run_mock.call_args_list[1].args[0]
        assert "--sign" in cmd
        assert "CGP Cursor Patch" in cmd


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


class TestIdentityHelpers:
    def test_parse_security_identities(self):
        out = '  1) ABC "CGP Cursor Patch"\n  2) DEF "Apple Development: X"\n'
        assert _parse_security_identities(out) == ["CGP Cursor Patch", "Apple Development: X"]

    def test_resolve_prefers_env(self):
        with mock.patch.dict("cursor_gui_patch.codesign.os.environ", {"CGP_CODESIGN_IDENTITY": "Pinned ID"}, clear=False):
            ident, source = _resolve_preferred_identity()
        assert ident == "Pinned ID"
        assert source == "env:CGP_CODESIGN_IDENTITY"

    def test_resolve_uses_stable_identity_name(self):
        with mock.patch.dict(
            "cursor_gui_patch.codesign.os.environ",
            {"CGP_CODESIGN_STABLE_IDENTITY_NAME": "My Stable"},
            clear=False,
        ), \
             mock.patch(
                 "cursor_gui_patch.codesign._available_codesign_identities",
                 return_value=["Apple Dev", "My Stable Identity"],
             ):
            ident, source = _resolve_preferred_identity()
        assert ident == "My Stable Identity"
        assert source == "auto:stable-identity"
