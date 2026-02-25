"""Tests for the patching engine."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional

from cursor_gui_patch.discovery import CursorInstallation, EXTENSION_TARGETS
from cursor_gui_patch.patching import patch, unpatch, status, _EXT_HOST_RELPATH
from cursor_gui_patch.backup import has_backup

# Realistic sample content for cursor-agent-exec (autorun patch target)
AUTORUN_CONTENT = (
    'prefix;async getAutoRunControls(){const e=await this.getTeamAdminSettings();'
    'if(e?.autoRunControls?.enabled)return{enabled:e.autoRunControls.enabled,'
    'allowed:e.autoRunControls.allowed??[],blocked:e.autoRunControls.blocked??[],'
    'enableRunEverything:e.autoRunControls.enableRunEverything??!1,'
    'mcpToolAllowlist:e.autoRunControls.mcpToolAllowlist??[]}};'
    'const h=await this.teamSettingsService.getAutoRunControls(),p={type:"insecure_none"};'
    'const l=await this.teamSettingsService.getAutoRunControls(),u=!0===l?.enabled;suffix'
)

# Realistic sample content for model patch targets
MODELS_CONTENT = (
    'r.AvailableModelsRequest; r.AvailableModelsResponse; '
    'throwErrorCheck:{name:"ThrowErrorCheck",I:r.ThrowErrorCheckRequest,O:r.ThrowErrorCheckResponse,kind:s.MethodKind.Unary},'
    'availableModels:{name:"AvailableModels",I:r.AvailableModelsRequest,O:r.AvailableModelsResponse,kind:s.MethodKind.Unary},'
    'getUsableModels:{name:"GetUsableModels",I:r.GetUsableModelsRequest,O:r.GetUsableModelsResponse,kind:s.MethodKind.Unary},'
    'getDefaultModelForCli:{name:"GetDefaultModelForCli",I:r.GetDefaultModelForCliRequest,O:r.GetDefaultModelForCliResponse,kind:s.MethodKind.Unary}'
)

# Content with no patchable patterns
IRRELEVANT_CONTENT = "function foo() { return 42; }"


def _make_test_installation(root: Path, contents: Optional[Dict[str, str]] = None) -> CursorInstallation:
    """Create a test installation with specified file contents."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "product.json").write_text(json.dumps({
        "applicationName": "cursor",
        "serverDataFolderName": ".cursor-server",
    }))

    if contents is None:
        contents = {
            "cursor-agent-exec": AUTORUN_CONTENT,
            "cursor-always-local": MODELS_CONTENT,
        }

    for ext_name, content in contents.items():
        info = EXTENSION_TARGETS.get(ext_name, {"file": "dist/main.js"})
        target = root / "extensions" / ext_name / str(info["file"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    return CursorInstallation(kind="server", root=root, version_id="test")


class TestPatch(unittest.TestCase):
    def test_patch_applies(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            report = patch(installations=[inst])
            self.assertTrue(report.ok)
            self.assertEqual(len(report.patched), 2)

    def test_patch_creates_backups(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            patch(installations=[inst])
            for t in inst.target_files():
                self.assertTrue(has_backup(t.path), f"No backup for {t.path}")

    def test_patch_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            report1 = patch(installations=[inst])
            self.assertEqual(len(report1.patched), 2)

            # Second patch should skip (already patched)
            report2 = patch(installations=[inst], force=True)
            self.assertEqual(len(report2.patched), 0)
            self.assertGreater(report2.already_patched, 0)

    def test_patch_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            report = patch(installations=[inst], dry_run=True)
            self.assertEqual(len(report.patched), 2)
            # Files should not be modified
            for t in inst.target_files():
                self.assertFalse(has_backup(t.path))

    def test_patch_only_autorun(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            report = patch(installations=[inst], only_patches={"autorun"})
            # Only autorun should be patched
            patched_names = {t.path.parent.parent.name for t in inst.target_files()
                            if t.path in report.patched}
            # cursor-agent-exec has autorun, cursor-always-local has models (skipped)
            self.assertIn("cursor-agent-exec", patched_names)

    def test_patch_cache(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            # First patch
            patch(installations=[inst])
            # Second patch should use cache
            report2 = patch(installations=[inst])
            self.assertGreater(report2.skipped_cached, 0)
            self.assertEqual(len(report2.patched), 0)


class TestUnpatch(unittest.TestCase):
    def test_unpatch_restores(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            # Read original content
            originals = {}
            for t in inst.target_files():
                originals[str(t.path)] = t.path.read_text()

            # Patch
            patch(installations=[inst])

            # Unpatch
            report = unpatch(installations=[inst])
            self.assertTrue(report.ok)
            self.assertGreater(len(report.restored), 0)

            # Verify content restored
            for t in inst.target_files():
                current = t.path.read_text()
                original = originals[str(t.path)]
                self.assertEqual(current, original, f"{t.path} not restored")

    def test_unpatch_no_backup(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            report = unpatch(installations=[inst])
            self.assertGreater(len(report.no_backup), 0)


class TestStatus(unittest.TestCase):
    def test_status_unpatched(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            report = status(installations=[inst])
            self.assertEqual(len(report.installations), 1)
            for f in report.files:
                for pname, is_patched in f.patched.items():
                    self.assertFalse(is_patched)

    def test_status_patched(self):
        with tempfile.TemporaryDirectory() as d:
            inst = _make_test_installation(Path(d))
            patch(installations=[inst])
            report = status(installations=[inst])
            for f in report.files:
                for pname, is_patched in f.patched.items():
                    self.assertTrue(is_patched, f"{f.extension}:{pname} should be patched")


def _add_ext_host_with_hashes(root: Path, contents: Dict[str, str]) -> Path:
    """Create extensionHostProcess.js containing SHA-256 hashes of extension files."""
    ext_host = root / _EXT_HOST_RELPATH
    ext_host.parent.mkdir(parents=True, exist_ok=True)

    # Build a fake extensionHostProcess.js that embeds hashes of extension files
    hashes = []
    for ext_name, content in contents.items():
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        hashes.append(h)
    ext_host_content = "var krt={" + ",".join(f'"{h}":true' for h in hashes) + "};"
    ext_host.write_text(ext_host_content)
    return ext_host


class TestExtensionHostHashes(unittest.TestCase):
    def test_patch_updates_hashes(self):
        """Patching should replace old hashes with new hashes in extensionHostProcess.js."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            contents = {
                "cursor-agent-exec": AUTORUN_CONTENT,
                "cursor-always-local": MODELS_CONTENT,
            }
            inst = _make_test_installation(root, contents)
            ext_host = _add_ext_host_with_hashes(root, contents)

            original_ext_host = ext_host.read_text()

            report = patch(installations=[inst])
            self.assertTrue(report.ok)

            updated_ext_host = ext_host.read_text()
            # extensionHostProcess.js should have been modified
            self.assertNotEqual(original_ext_host, updated_ext_host)

            # Old hashes should be gone, new hashes should be present
            for ext_name, content in contents.items():
                old_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                self.assertNotIn(old_hash, updated_ext_host)

            # New hashes should match the actual patched file contents
            for t in inst.target_files():
                new_hash = hashlib.sha256(t.path.read_bytes()).hexdigest()
                self.assertIn(new_hash, updated_ext_host)

    def test_patch_creates_ext_host_backup(self):
        """Patching should create a backup of extensionHostProcess.js."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            contents = {
                "cursor-agent-exec": AUTORUN_CONTENT,
                "cursor-always-local": MODELS_CONTENT,
            }
            inst = _make_test_installation(root, contents)
            _add_ext_host_with_hashes(root, contents)

            ext_host = root / _EXT_HOST_RELPATH
            patch(installations=[inst])
            self.assertTrue(has_backup(ext_host))

    def test_unpatch_restores_ext_host(self):
        """Unpatching should restore extensionHostProcess.js from backup."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            contents = {
                "cursor-agent-exec": AUTORUN_CONTENT,
                "cursor-always-local": MODELS_CONTENT,
            }
            inst = _make_test_installation(root, contents)
            ext_host = _add_ext_host_with_hashes(root, contents)

            original_ext_host = ext_host.read_text()

            patch(installations=[inst])
            self.assertNotEqual(ext_host.read_text(), original_ext_host)

            report = unpatch(installations=[inst])
            self.assertTrue(report.ok)
            self.assertIn(ext_host, report.restored)
            self.assertEqual(ext_host.read_text(), original_ext_host)
            self.assertFalse(has_backup(ext_host))

    def test_no_ext_host_file_is_ok(self):
        """Patching should succeed even without extensionHostProcess.js."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inst = _make_test_installation(root)
            # No extensionHostProcess.js created
            report = patch(installations=[inst])
            self.assertTrue(report.ok)
            self.assertEqual(len(report.patched), 2)

    def test_ext_host_no_matching_hashes(self):
        """If extensionHostProcess.js has no matching hashes, it should not be modified."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inst = _make_test_installation(root)
            ext_host = root / _EXT_HOST_RELPATH
            ext_host.parent.mkdir(parents=True, exist_ok=True)
            ext_host.write_text("var krt={};")

            original = ext_host.read_text()
            patch(installations=[inst])
            self.assertEqual(ext_host.read_text(), original)
            self.assertFalse(has_backup(ext_host))


if __name__ == "__main__":
    unittest.main()
