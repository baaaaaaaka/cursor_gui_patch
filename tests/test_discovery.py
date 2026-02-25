"""Tests for installation discovery."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from cursor_gui_patch.discovery import (
    CursorInstallation,
    EXTENSION_TARGETS,
    _is_cursor_app_root,
    discover_server_installations,
    discover_gui_installations,
)


def _make_fake_installation(root: Path, extensions: list[str] | None = None) -> None:
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


if __name__ == "__main__":
    unittest.main()
