"""Tests for installation discovery."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional
from unittest import mock

from cursor_gui_patch.discovery import (
    CursorInstallation,
    EXTENSION_TARGETS,
    _get_server_data_folder_name,
    _gui_candidates,
    _is_cursor_app_root,
    _is_wsl,
    _version_id_from_path,
    discover_all,
    discover_gui_installations,
    discover_server_installations,
)


def _make_fake_installation(root: Path, extensions: Optional[List[str]] = None) -> None:
    """Create a minimal fake Cursor installation directory."""
    root.mkdir(parents=True, exist_ok=True)
    product_json = root / "product.json"
    product_json.write_text(json.dumps({
        "applicationName": "cursor",
        "serverDataFolderName": ".cursor-server",
    }))
    if extensions is None:
        extensions = list(EXTENSION_TARGETS.keys())
    ext_dir = root / "extensions"
    for ext in extensions:
        info = EXTENSION_TARGETS.get(ext)
        if info:
            target_file = ext_dir / ext / str(info["file"])
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text("// placeholder JS content")


class TestIsCursorAppRoot(unittest.TestCase):
    def test_valid_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_fake_installation(root)
            self.assertTrue(_is_cursor_app_root(root))

    def test_missing_product_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertFalse(_is_cursor_app_root(root))

    def test_wrong_application_name(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "product.json").write_text(json.dumps({
                "applicationName": "vscode",
            }))
            self.assertFalse(_is_cursor_app_root(root))

    def test_malformed_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "product.json").write_text("not json")
            self.assertFalse(_is_cursor_app_root(root))


class TestCursorInstallation(unittest.TestCase):
    def test_target_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_fake_installation(root)
            inst = CursorInstallation(kind="server", root=root, version_id="test123")
            targets = inst.target_files()
            self.assertEqual(len(targets), len(EXTENSION_TARGETS))
            names = {t.extension for t in targets}
            self.assertEqual(names, set(EXTENSION_TARGETS.keys()))

    def test_target_files_partial(self):
        """Only some extensions present."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_fake_installation(root, extensions=["cursor-agent-exec"])
            inst = CursorInstallation(kind="server", root=root, version_id="test123")
            targets = inst.target_files()
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0].extension, "cursor-agent-exec")
            self.assertEqual(targets[0].patch_names, ["autorun"])


class TestDiscoverServer(unittest.TestCase):
    def test_explicit_dir(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_fake_installation(root)
            results = discover_server_installations(explicit_dir=str(root))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].kind, "server")
            self.assertEqual(results[0].root, root)

    def test_explicit_dir_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            results = discover_server_installations(explicit_dir=d)
            self.assertEqual(len(results), 0)

    def test_env_var_override(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_fake_installation(root)
            old = os.environ.get("CGP_CURSOR_SERVER_DIR")
            try:
                os.environ["CGP_CURSOR_SERVER_DIR"] = str(root)
                results = discover_server_installations()
                self.assertEqual(len(results), 1)
            finally:
                if old is None:
                    os.environ.pop("CGP_CURSOR_SERVER_DIR", None)
                else:
                    os.environ["CGP_CURSOR_SERVER_DIR"] = old


class TestDiscoverGui(unittest.TestCase):
    def test_explicit_dir(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_fake_installation(root)
            results = discover_gui_installations(explicit_dir=str(root))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].kind, "gui")

    def test_explicit_dir_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            results = discover_gui_installations(explicit_dir=d)
            self.assertEqual(len(results), 0)


# ── New tests (pytest-style) ────────────────────────────────────


class TestIsWsl:
    @mock.patch("cursor_gui_patch.discovery.Path")
    def test_detects_microsoft_in_proc_version(self, MockPath):
        MockPath.return_value.read_text.return_value = (
            "Linux version 5.15.90.1-microsoft-standard-WSL2"
        )
        assert _is_wsl() is True

    @mock.patch("cursor_gui_patch.discovery.Path")
    def test_detects_wsl_keyword(self, MockPath):
        MockPath.return_value.read_text.return_value = (
            "Linux version 5.15.90.1-WSL2-custom"
        )
        assert _is_wsl() is True

    @mock.patch("cursor_gui_patch.discovery.Path")
    def test_returns_false_for_native_linux(self, MockPath):
        MockPath.return_value.read_text.return_value = (
            "Linux version 6.5.0-44-generic (buildd@bos03-amd64-075)"
        )
        assert _is_wsl() is False

    @mock.patch("cursor_gui_patch.discovery.Path")
    def test_returns_false_on_read_error(self, MockPath):
        MockPath.return_value.read_text.side_effect = FileNotFoundError
        assert _is_wsl() is False

    @mock.patch("cursor_gui_patch.discovery.Path")
    def test_returns_false_on_permission_error(self, MockPath):
        MockPath.return_value.read_text.side_effect = PermissionError
        assert _is_wsl() is False


class TestVersionIdFromPath:
    def test_bin_parent_uses_hash(self):
        p = Path("/home/user/.cursor-server/bin/abc123def456")
        assert _version_id_from_path(p) == "abc123def456"

    def test_non_bin_parent_uses_dir_name(self):
        p = Path("/opt/cursor/resources/app")
        assert _version_id_from_path(p) == "app"

    def test_root_path_returns_unknown(self):
        p = Path("/")
        assert _version_id_from_path(p) == "unknown"


class TestGetServerDataFolderName:
    def test_reads_custom_folder_name(self, tmp_path: Path):
        (tmp_path / "product.json").write_text(
            json.dumps({"applicationName": "cursor", "serverDataFolderName": ".my-server"})
        )
        assert _get_server_data_folder_name(tmp_path) == ".my-server"

    def test_default_when_key_missing(self, tmp_path: Path):
        (tmp_path / "product.json").write_text(
            json.dumps({"applicationName": "cursor"})
        )
        assert _get_server_data_folder_name(tmp_path) == ".cursor-server"

    def test_default_on_missing_file(self, tmp_path: Path):
        assert _get_server_data_folder_name(tmp_path) == ".cursor-server"

    def test_default_on_invalid_json(self, tmp_path: Path):
        (tmp_path / "product.json").write_text("not json{{{")
        assert _get_server_data_folder_name(tmp_path) == ".cursor-server"


class TestGuiCandidates:
    @mock.patch("cursor_gui_patch.discovery.sys")
    def test_darwin_returns_app_bundle_paths(self, mock_sys):
        mock_sys.platform = "darwin"
        candidates = _gui_candidates()
        paths = [str(c) for c in candidates]
        assert any("Cursor.app/Contents/Resources/app" in p for p in paths)
        assert len(candidates) == 2

    @mock.patch.dict(os.environ, {"LOCALAPPDATA": "/fake/AppData/Local"})
    @mock.patch("cursor_gui_patch.discovery.sys")
    def test_win32_returns_program_paths(self, mock_sys):
        mock_sys.platform = "win32"
        candidates = _gui_candidates()
        paths = [str(c) for c in candidates]
        assert any("cursor" in p.lower() and "resources" in p for p in paths)
        assert len(candidates) == 2

    @mock.patch.dict(os.environ, {"LOCALAPPDATA": ""})
    @mock.patch("cursor_gui_patch.discovery.sys")
    def test_win32_empty_localappdata_returns_nothing(self, mock_sys):
        mock_sys.platform = "win32"
        candidates = _gui_candidates()
        assert len(candidates) == 0

    @mock.patch("cursor_gui_patch.discovery._is_wsl", return_value=False)
    @mock.patch("cursor_gui_patch.discovery.sys")
    def test_linux_returns_standard_paths(self, mock_sys, _):
        mock_sys.platform = "linux"
        candidates = _gui_candidates()
        paths = [str(c) for c in candidates]
        assert any("/opt/cursor" in p for p in paths)
        assert any("/usr/share/cursor" in p for p in paths)
        assert any("/snap/cursor" in p for p in paths)
        # Should NOT include WSL paths
        assert not any("/mnt/c/" in p for p in paths)

    @mock.patch(
        "cursor_gui_patch.discovery._wsl_gui_candidates",
        return_value=[Path("/mnt/c/Users/test/AppData/Local/Programs/cursor/resources/app")],
    )
    @mock.patch("cursor_gui_patch.discovery._is_wsl", return_value=True)
    @mock.patch("cursor_gui_patch.discovery.sys")
    def test_linux_wsl_appends_windows_paths(self, mock_sys, _, __):
        mock_sys.platform = "linux"
        candidates = _gui_candidates()
        paths = [str(c) for c in candidates]
        # Should include both Linux standard paths AND WSL Windows paths
        assert any("/opt/cursor" in p for p in paths)
        assert any("/mnt/c/" in p for p in paths)


class TestDiscoverServerAutoDiscover:
    def test_finds_installation_in_cursor_server_bin(self, tmp_path: Path):
        server_root = tmp_path / ".cursor-server" / "bin" / "abc123"
        _make_fake_installation(server_root)

        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            results = discover_server_installations()

        assert len(results) == 1
        assert results[0].kind == "server"
        assert results[0].version_id == "abc123"
        assert results[0].root == server_root

    def test_finds_multiple_versions(self, tmp_path: Path):
        bin_dir = tmp_path / ".cursor-server" / "bin"
        _make_fake_installation(bin_dir / "aaa111")
        _make_fake_installation(bin_dir / "bbb222")

        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            results = discover_server_installations()

        assert len(results) == 2
        ids = {r.version_id for r in results}
        assert ids == {"aaa111", "bbb222"}

    def test_empty_when_no_cursor_server_dir(self, tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            results = discover_server_installations()

        assert len(results) == 0

    def test_skips_non_cursor_dirs(self, tmp_path: Path):
        bin_dir = tmp_path / ".cursor-server" / "bin"
        non_cursor = bin_dir / "not-cursor"
        non_cursor.mkdir(parents=True)
        (non_cursor / "product.json").write_text('{"applicationName": "vscode"}')

        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            results = discover_server_installations()

        assert len(results) == 0

    def test_handles_permission_error(self, tmp_path: Path):
        bin_dir = tmp_path / ".cursor-server" / "bin"
        bin_dir.mkdir(parents=True)

        with mock.patch("pathlib.Path.home", return_value=tmp_path), \
             mock.patch.object(Path, "iterdir", side_effect=PermissionError):
            results = discover_server_installations()

        assert len(results) == 0


class TestDiscoverGuiAutoDiscover:
    def test_finds_from_candidates(self, tmp_path: Path):
        root = tmp_path / "cursor" / "resources" / "app"
        _make_fake_installation(root)

        with mock.patch(
            "cursor_gui_patch.discovery._gui_candidates",
            return_value=[root, tmp_path / "nonexistent"],
        ):
            results = discover_gui_installations()

        assert len(results) == 1
        assert results[0].kind == "gui"
        assert results[0].root == root

    def test_empty_when_no_candidates_match(self, tmp_path: Path):
        with mock.patch(
            "cursor_gui_patch.discovery._gui_candidates",
            return_value=[tmp_path / "nonexistent"],
        ):
            results = discover_gui_installations()

        assert len(results) == 0


class TestDiscoverAll:
    def test_combines_server_and_gui(self, tmp_path: Path):
        server_root = tmp_path / "server"
        gui_root = tmp_path / "gui"
        _make_fake_installation(server_root)
        _make_fake_installation(gui_root)

        results = discover_all(server_dir=str(server_root), gui_dir=str(gui_root))
        kinds = {r.kind for r in results}
        assert "server" in kinds
        assert "gui" in kinds
        assert len(results) == 2

    def test_empty_when_nothing_found(self, tmp_path: Path):
        results = discover_all(
            server_dir=str(tmp_path / "no-server"),
            gui_dir=str(tmp_path / "no-gui"),
        )
        assert len(results) == 0


if __name__ == "__main__":
    unittest.main()
