"""Tests for cursor_gui_patch.auto_extension."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from cursor_gui_patch import __version__
from cursor_gui_patch.auto_extension import (
    EXTENSION_ID,
    EXTENSION_NAME,
    GITHUB_REPO,
    _ext_dir_name,
    _extensions_root,
    _find_existing,
    _generate_extension_js,
    _generate_package_json,
    _make_registry_entry,
    _read_extensions_json,
    _to_vscode_uri_path,
    install,
    status,
    uninstall,
)


class TestGeneratePackageJson:
    def test_valid_json(self):
        raw = _generate_package_json("1.2.3")
        data = json.loads(raw)
        assert data["name"] == EXTENSION_NAME
        assert data["version"] == "1.2.3"

    def test_extension_kind_workspace(self):
        data = json.loads(_generate_package_json("0.1.0"))
        assert data["extensionKind"] == ["workspace"]

    def test_activation_events(self):
        data = json.loads(_generate_package_json("0.1.0"))
        assert "onStartupFinished" in data["activationEvents"]

    def test_main_entry(self):
        data = json.loads(_generate_package_json("0.1.0"))
        assert data["main"] == "./extension.js"


class TestGenerateExtensionJs:
    def test_contains_repo(self):
        js = _generate_extension_js()
        assert GITHUB_REPO in js

    def test_contains_activate(self):
        js = _generate_extension_js()
        assert "async function activate" in js

    def test_contains_deactivate_export(self):
        js = _generate_extension_js()
        assert "deactivate:" in js

    def test_contains_cgp_patch_call(self):
        js = _generate_extension_js()
        assert "['patch']" in js

    def test_contains_platform_detection(self):
        js = _generate_extension_js()
        assert "process.platform" in js
        assert "process.arch" in js

    def test_contains_select_asset(self):
        js = _generate_extension_js()
        assert "selectAsset" in js
        assert "cgp-linux-x86_64.tar.gz" in js
        assert "cgp-macos-arm64.tar.gz" in js
        assert "cgp-windows-x86_64.zip" in js

    def test_contains_redirect_handling(self):
        js = _generate_extension_js()
        assert "301" in js
        assert "302" in js
        assert "redirects" in js

    def test_windows_install_uses_copy_fallback(self):
        js = _generate_extension_js()
        assert "fs.cpSync" in js
        assert "fs.copyFileSync" in js
        assert "fs.statSync" in js


class TestExtensionsRoot:
    """Test _extensions_root() for all platform / target combinations."""

    def test_server_target_uses_linux_home(self):
        result = _extensions_root("server")
        assert result == Path.home() / ".cursor-server" / "extensions"

    @mock.patch("cursor_gui_patch.auto_extension.sys")
    def test_darwin_gui(self, mock_sys):
        mock_sys.platform = "darwin"
        result = _extensions_root("gui")
        assert result == Path.home() / ".cursor" / "extensions"

    @mock.patch.dict(os.environ, {"USERPROFILE": "/fake/windows/home"})
    @mock.patch("cursor_gui_patch.auto_extension.sys")
    def test_win32_gui(self, mock_sys):
        mock_sys.platform = "win32"
        result = _extensions_root("gui")
        assert result == Path("/fake/windows/home") / ".cursor" / "extensions"

    @mock.patch("cursor_gui_patch.auto_extension._is_wsl", return_value=False)
    @mock.patch("cursor_gui_patch.auto_extension.sys")
    def test_linux_gui_not_wsl(self, mock_sys, _):
        mock_sys.platform = "linux"
        result = _extensions_root("gui")
        assert result == Path.home() / ".cursor" / "extensions"

    @mock.patch(
        "cursor_gui_patch.auto_extension._wsl_gui_extensions_root",
        return_value=Path("/mnt/c/Users/testuser/.cursor/extensions"),
    )
    @mock.patch("cursor_gui_patch.auto_extension._is_wsl", return_value=True)
    @mock.patch("cursor_gui_patch.auto_extension.sys")
    def test_linux_gui_wsl_found(self, mock_sys, _, __):
        mock_sys.platform = "linux"
        result = _extensions_root("gui")
        assert result == Path("/mnt/c/Users/testuser/.cursor/extensions")

    @mock.patch(
        "cursor_gui_patch.auto_extension._wsl_gui_extensions_root",
        return_value=None,
    )
    @mock.patch("cursor_gui_patch.auto_extension._is_wsl", return_value=True)
    @mock.patch("cursor_gui_patch.auto_extension.sys")
    def test_linux_gui_wsl_fallback_when_no_windows_cursor(self, mock_sys, _, __):
        """WSL detected but no Windows Cursor found → fallback to Linux home."""
        mock_sys.platform = "linux"
        result = _extensions_root("gui")
        assert result == Path.home() / ".cursor" / "extensions"

    @mock.patch("cursor_gui_patch.auto_extension._is_wsl", return_value=True)
    def test_wsl_server_target_ignores_wsl(self, _):
        """Server target on WSL should use Linux home, not Windows path."""
        result = _extensions_root("server")
        assert result == Path.home() / ".cursor-server" / "extensions"

    @mock.patch("cursor_gui_patch.auto_extension.sys")
    def test_darwin_server(self, mock_sys):
        mock_sys.platform = "darwin"
        result = _extensions_root("server")
        assert result == Path.home() / ".cursor-server" / "extensions"

    @mock.patch("cursor_gui_patch.auto_extension.sys")
    def test_win32_server(self, mock_sys):
        mock_sys.platform = "win32"
        result = _extensions_root("server")
        assert result == Path.home() / ".cursor-server" / "extensions"


class TestToVscodeUriPath:
    def test_wsl_path(self):
        p = Path("/mnt/c/Users/baka/.cursor/extensions/foo-1.0")
        assert _to_vscode_uri_path(p) == "/c:/Users/baka/.cursor/extensions/foo-1.0"

    def test_wsl_drive_d(self):
        p = Path("/mnt/d/some/path")
        assert _to_vscode_uri_path(p) == "/d:/some/path"

    def test_linux_native_path(self):
        p = Path("/home/user/.cursor/extensions/foo-1.0")
        assert _to_vscode_uri_path(p) == "/home/user/.cursor/extensions/foo-1.0"

    def test_macos_path(self):
        p = Path("/Users/someone/.cursor/extensions/foo-1.0")
        assert _to_vscode_uri_path(p) == "/Users/someone/.cursor/extensions/foo-1.0"

    def test_short_mnt_path_not_treated_as_wsl(self):
        """Paths like /mnt/c (no trailing subpath) should not be WSL-converted."""
        p = Path("/mnt/c")
        assert _to_vscode_uri_path(p) == "/mnt/c"

    def test_mnt_non_drive_path(self):
        """/mnt/data/... should not be WSL-converted (s[6] != '/')."""
        p = Path("/mnt/data/something")
        # s = "/mnt/data/something", s[5]="a", s[6]="t" != "/"
        assert _to_vscode_uri_path(p) == "/mnt/data/something"

    def test_windows_native_drive_path(self):
        """Windows-style path C:/Users/... → /c:/Users/... (works on Linux as PosixPath)."""
        p = Path("C:/Users/baka/.cursor/extensions/foo-1.0")
        result = _to_vscode_uri_path(p)
        assert result == "/c:/Users/baka/.cursor/extensions/foo-1.0"

    def test_windows_native_drive_d(self):
        p = Path("D:/some/path")
        assert _to_vscode_uri_path(p) == "/d:/some/path"


class TestMakeRegistryEntry:
    def test_has_required_keys(self):
        ext_dir = Path("/tmp/extensions/cgp-auto-patcher-0.1.0")
        entry = _make_registry_entry("0.1.0", ext_dir)
        assert "identifier" in entry
        assert "version" in entry
        assert "location" in entry
        assert "relativeLocation" in entry
        assert "metadata" in entry

    def test_identifier(self):
        ext_dir = Path("/tmp/extensions/cgp-auto-patcher-0.1.0")
        entry = _make_registry_entry("0.1.0", ext_dir)
        assert entry["identifier"]["id"] == EXTENSION_ID

    def test_version(self):
        ext_dir = Path("/tmp/extensions/cgp-auto-patcher-0.2.0")
        entry = _make_registry_entry("0.2.0", ext_dir)
        assert entry["version"] == "0.2.0"

    def test_location_scheme(self):
        ext_dir = Path("/tmp/extensions/cgp-auto-patcher-0.1.0")
        entry = _make_registry_entry("0.1.0", ext_dir)
        assert entry["location"]["scheme"] == "file"
        assert entry["location"]["$mid"] == 1

    def test_location_path(self):
        ext_dir = Path("/tmp/extensions/cgp-auto-patcher-0.1.0")
        entry = _make_registry_entry("0.1.0", ext_dir)
        assert entry["location"]["path"] == "/tmp/extensions/cgp-auto-patcher-0.1.0"

    def test_relative_location(self):
        ext_dir = Path("/tmp/extensions/cgp-auto-patcher-0.1.0")
        entry = _make_registry_entry("0.1.0", ext_dir)
        assert entry["relativeLocation"] == "cgp-auto-patcher-0.1.0"

    def test_metadata_source_vsix(self):
        ext_dir = Path("/tmp/extensions/cgp-auto-patcher-0.1.0")
        entry = _make_registry_entry("0.1.0", ext_dir)
        assert entry["metadata"]["source"] == "vsix"
        assert entry["metadata"]["pinned"] is True

    def test_metadata_timestamp_is_millis(self):
        ext_dir = Path("/tmp/extensions/cgp-auto-patcher-0.1.0")
        entry = _make_registry_entry("0.1.0", ext_dir)
        ts = entry["metadata"]["installedTimestamp"]
        # Should be in milliseconds (> 1e12)
        assert ts > 1_000_000_000_000


class TestReadExtensionsJson:
    def test_missing_file(self, tmp_path: Path):
        assert _read_extensions_json(tmp_path) == []

    def test_valid_json(self, tmp_path: Path):
        entries = [{"identifier": {"id": "foo"}, "version": "1.0"}]
        (tmp_path / "extensions.json").write_text(json.dumps(entries))
        assert _read_extensions_json(tmp_path) == entries

    def test_invalid_json(self, tmp_path: Path):
        (tmp_path / "extensions.json").write_text("not json!!!")
        assert _read_extensions_json(tmp_path) == []

    def test_non_list_json(self, tmp_path: Path):
        (tmp_path / "extensions.json").write_text('{"key": "value"}')
        assert _read_extensions_json(tmp_path) == []


class TestInstall:
    def test_creates_extension_dir(self, tmp_path: Path):
        result = install(extensions_root=tmp_path)
        ext_dir = tmp_path / _ext_dir_name(__version__)
        assert ext_dir.is_dir()
        assert "Installed" in result

    def test_creates_package_json(self, tmp_path: Path):
        install(extensions_root=tmp_path)
        ext_dir = tmp_path / _ext_dir_name(__version__)
        pkg = json.loads((ext_dir / "package.json").read_text(encoding="utf-8"))
        assert pkg["name"] == EXTENSION_NAME
        assert pkg["version"] == __version__

    def test_creates_extension_js(self, tmp_path: Path):
        install(extensions_root=tmp_path)
        ext_dir = tmp_path / _ext_dir_name(__version__)
        js = (ext_dir / "extension.js").read_text(encoding="utf-8")
        assert "activate" in js
        assert GITHUB_REPO in js

    def test_creates_extensions_json(self, tmp_path: Path):
        install(extensions_root=tmp_path)
        json_path = tmp_path / "extensions.json"
        assert json_path.is_file()
        entries = json.loads(json_path.read_text(encoding="utf-8"))
        assert len(entries) == 1
        assert entries[0]["identifier"]["id"] == EXTENSION_ID
        assert entries[0]["version"] == __version__

    def test_preserves_existing_extensions_json(self, tmp_path: Path):
        # Pre-populate with another extension
        existing = [{"identifier": {"id": "other.ext"}, "version": "1.0"}]
        (tmp_path / "extensions.json").write_text(json.dumps(existing))

        install(extensions_root=tmp_path)

        entries = json.loads((tmp_path / "extensions.json").read_text(encoding="utf-8"))
        ids = [e["identifier"]["id"] for e in entries]
        assert "other.ext" in ids
        assert EXTENSION_ID in ids
        assert len(entries) == 2

    def test_idempotent(self, tmp_path: Path):
        msg1 = install(extensions_root=tmp_path)
        msg2 = install(extensions_root=tmp_path)
        assert "Installed" in msg1
        assert "Installed" in msg2
        # Only one directory should exist
        dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(dirs) == 1
        # Only one registry entry
        entries = json.loads((tmp_path / "extensions.json").read_text(encoding="utf-8"))
        cgp_entries = [e for e in entries if e["identifier"]["id"] == EXTENSION_ID]
        assert len(cgp_entries) == 1

    def test_cleans_old_versions(self, tmp_path: Path):
        # Simulate an older version
        old_dir = tmp_path / f"{EXTENSION_NAME}-0.0.1"
        old_dir.mkdir(parents=True)
        (old_dir / "package.json").write_text("{}", encoding="utf-8")

        install(extensions_root=tmp_path)

        assert not old_dir.exists()
        new_dir = tmp_path / _ext_dir_name(__version__)
        assert new_dir.is_dir()

    def test_returns_path_in_message(self, tmp_path: Path):
        result = install(extensions_root=tmp_path)
        assert str(tmp_path) in result


class TestUninstall:
    def test_removes_extension(self, tmp_path: Path):
        install(extensions_root=tmp_path)
        result = uninstall(extensions_root=tmp_path)
        assert "Uninstalled" in result
        dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(dirs) == 0

    def test_removes_registry_entry(self, tmp_path: Path):
        # Pre-populate with another extension + install ours
        existing = [{"identifier": {"id": "other.ext"}, "version": "1.0"}]
        (tmp_path / "extensions.json").write_text(json.dumps(existing))
        install(extensions_root=tmp_path)

        uninstall(extensions_root=tmp_path)

        entries = json.loads((tmp_path / "extensions.json").read_text(encoding="utf-8"))
        ids = [e["identifier"]["id"] for e in entries]
        assert EXTENSION_ID not in ids
        assert "other.ext" in ids

    def test_not_installed(self, tmp_path: Path):
        result = uninstall(extensions_root=tmp_path)
        assert "not installed" in result

    def test_removes_multiple_versions(self, tmp_path: Path):
        # Simulate multiple versions
        for v in ("0.0.1", "0.0.2", "0.0.3"):
            d = tmp_path / f"{EXTENSION_NAME}-{v}"
            d.mkdir(parents=True)
            (d / "package.json").write_text("{}", encoding="utf-8")

        result = uninstall(extensions_root=tmp_path)
        assert "Uninstalled" in result
        remaining = [p for p in tmp_path.iterdir() if p.name.startswith(EXTENSION_NAME)]
        assert len(remaining) == 0

    def test_cleans_orphan_registry(self, tmp_path: Path):
        """Uninstall cleans registry even if directory is already gone."""
        entries = [_make_registry_entry("0.1.0", tmp_path / "cgp-auto-patcher-0.1.0")]
        (tmp_path / "extensions.json").write_text(json.dumps(entries))

        result = uninstall(extensions_root=tmp_path)
        assert "not installed" in result
        # Registry should be cleaned
        remaining = json.loads((tmp_path / "extensions.json").read_text(encoding="utf-8"))
        assert len(remaining) == 0


class TestStatus:
    def test_installed(self, tmp_path: Path):
        install(extensions_root=tmp_path)
        result = status(extensions_root=tmp_path)
        assert "installed" in result
        assert __version__ in result

    def test_not_installed(self, tmp_path: Path):
        result = status(extensions_root=tmp_path)
        assert "not installed" in result

    def test_reports_target(self, tmp_path: Path):
        result = status(target="gui", extensions_root=tmp_path)
        assert "gui" in result

    def test_reports_server_target(self, tmp_path: Path):
        result = status(target="server", extensions_root=tmp_path)
        assert "server" in result


class TestFindExisting:
    def test_empty(self, tmp_path: Path):
        assert _find_existing(tmp_path) == []

    def test_finds_matching(self, tmp_path: Path):
        d = tmp_path / f"{EXTENSION_NAME}-1.0.0"
        d.mkdir()
        result = _find_existing(tmp_path)
        assert len(result) == 1
        assert result[0] == d

    def test_ignores_non_matching(self, tmp_path: Path):
        (tmp_path / "some-other-extension-1.0.0").mkdir()
        assert _find_existing(tmp_path) == []

    def test_ignores_files(self, tmp_path: Path):
        (tmp_path / f"{EXTENSION_NAME}-1.0.0").write_text("not a dir")
        assert _find_existing(tmp_path) == []


class TestExtDirName:
    def test_format(self):
        assert _ext_dir_name("0.1.3") == f"{EXTENSION_NAME}-0.1.3"


class TestCLIIntegration:
    """Test the CLI 'auto' subcommand routing."""

    def test_install_via_cli(self, tmp_path: Path):
        from unittest import mock

        with mock.patch(
            "cursor_gui_patch.auto_extension._extensions_root",
            return_value=tmp_path,
        ):
            from cursor_gui_patch.cli import main

            main(["auto", "install"])

        ext_dir = tmp_path / _ext_dir_name(__version__)
        assert ext_dir.is_dir()

    def test_status_via_cli(self, tmp_path: Path, capsys):
        from unittest import mock

        with mock.patch(
            "cursor_gui_patch.auto_extension._extensions_root",
            return_value=tmp_path,
        ):
            from cursor_gui_patch.cli import main

            main(["auto", "status"])

        captured = capsys.readouterr()
        assert "not installed" in captured.out

    def test_uninstall_via_cli(self, tmp_path: Path, capsys):
        from unittest import mock

        with mock.patch(
            "cursor_gui_patch.auto_extension._extensions_root",
            return_value=tmp_path,
        ):
            from cursor_gui_patch.cli import main

            main(["auto", "install"])
            main(["auto", "uninstall"])

        captured = capsys.readouterr()
        assert "Uninstalled" in captured.out
