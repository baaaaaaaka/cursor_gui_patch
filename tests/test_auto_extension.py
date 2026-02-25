"""Tests for cursor_gui_patch.auto_extension."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursor_gui_patch import __version__
from cursor_gui_patch.auto_extension import (
    EXTENSION_NAME,
    GITHUB_REPO,
    _ext_dir_name,
    _find_existing,
    _generate_extension_js,
    _generate_package_json,
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

    def test_idempotent(self, tmp_path: Path):
        msg1 = install(extensions_root=tmp_path)
        msg2 = install(extensions_root=tmp_path)
        assert "Installed" in msg1
        assert "Installed" in msg2
        # Only one directory should exist
        dirs = list(tmp_path.iterdir())
        assert len(dirs) == 1

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
        assert not list(tmp_path.iterdir())

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
