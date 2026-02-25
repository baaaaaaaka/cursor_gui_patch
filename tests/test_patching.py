"""Tests for the patching engine."""

import json
import tempfile
import unittest
from pathlib import Path

from cursor_gui_patch.discovery import CursorInstallation, EXTENSION_TARGETS
from cursor_gui_patch.patching import patch, unpatch, status
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


def _make_test_installation(root: Path, contents: dict[str, str] | None = None) -> CursorInstallation:
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


if __name__ == "__main__":
    unittest.main()
