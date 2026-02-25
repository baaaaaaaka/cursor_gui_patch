"""Tests for the patching engine."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional

import base64

from cursor_gui_patch.discovery import CursorInstallation, EXTENSION_TARGETS, WORKBENCH_TARGETS
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

# Realistic sample content for workbench.desktop.main.js (autorun_workbench patch target)
WORKBENCH_CONTENT = (
    'prefix;{isAdminControlled:!1,isDisabledByAdmin:!0,allowed:[],blocked:[]};'
    'o={isAdminControlled:!0,isDisabledByAdmin:v.length+w.length===0&&!S&&k.length===0&&!D,browserFeatures:r?.browserFeatures};'
    'suffix;'
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


def _add_workbench_file(root: Path, content: str = WORKBENCH_CONTENT) -> Path:
    """Create workbench.desktop.main.js under the installation root."""
    info = WORKBENCH_TARGETS["workbench.desktop.main.js"]
    wb_path = root / str(info["file"])
    wb_path.parent.mkdir(parents=True, exist_ok=True)
    wb_path.write_text(content)
    return wb_path


def _b64sha256(data: bytes) -> str:
    """Compute base64(sha256(data)) without padding — same format as product.json."""
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")


def _add_product_json_with_checksums(root: Path, files: Dict[str, Path]) -> Path:
    """Rewrite product.json to include a checksums dict.

    *files* maps relative-to-out/ POSIX paths to their absolute file paths.
    """
    product_json = root / "product.json"
    data = json.loads(product_json.read_text())
    checksums: Dict[str, str] = {}
    for rel_posix, abs_path in files.items():
        checksums[rel_posix] = _b64sha256(abs_path.read_bytes())
    data["checksums"] = checksums
    product_json.write_bytes(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    return product_json


class TestWorkbenchPatch(unittest.TestCase):
    """Integration tests for the autorun_workbench patch via the patching engine."""

    def test_workbench_patch_applies(self):
        """Workbench file should be patched when present."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inst = _make_test_installation(root)
            wb = _add_workbench_file(root)

            report = patch(installations=[inst])
            self.assertTrue(report.ok)
            self.assertIn(wb, report.patched)

            content = wb.read_text()
            self.assertIn("isDisabledByAdmin:!1", content)
            self.assertNotIn("isDisabledByAdmin:!0", content)
            self.assertNotIn("isAdminControlled:!0", content)
            self.assertIn("CGP_PATCH_AUTORUN_WORKBENCH", content)

    def test_workbench_patch_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inst = _make_test_installation(root)
            _add_workbench_file(root)

            patch(installations=[inst])
            report2 = patch(installations=[inst], force=True)
            self.assertEqual(len([p for p in report2.patched
                                  if p.name == "workbench.desktop.main.js"]), 0)

    def test_workbench_skipped_when_absent(self):
        """Server installs without workbench file should not error."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inst = _make_test_installation(root)
            # No workbench file
            report = patch(installations=[inst])
            self.assertTrue(report.ok)
            self.assertEqual(len(report.patched), 2)  # only extension files

    def test_unpatch_restores_workbench(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inst = _make_test_installation(root)
            wb = _add_workbench_file(root)
            original = wb.read_text()

            patch(installations=[inst])
            self.assertNotEqual(wb.read_text(), original)

            report = unpatch(installations=[inst])
            self.assertTrue(report.ok)
            self.assertIn(wb, report.restored)
            self.assertEqual(wb.read_text(), original)


class TestProductJsonChecksums(unittest.TestCase):
    """Tests for product.json checksums update."""

    def test_checksums_updated_after_patch(self):
        """After patching, product.json checksums should match the new file contents."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            contents = {
                "cursor-agent-exec": AUTORUN_CONTENT,
                "cursor-always-local": MODELS_CONTENT,
            }
            inst = _make_test_installation(root, contents)
            ext_host = _add_ext_host_with_hashes(root, contents)
            wb = _add_workbench_file(root)

            # Build checksums for ext_host and workbench
            out_dir = root / "out"
            checksum_files = {
                ext_host.relative_to(out_dir).as_posix(): ext_host,
                wb.relative_to(out_dir).as_posix(): wb,
            }
            product_json = _add_product_json_with_checksums(root, checksum_files)
            original_pj = product_json.read_bytes()

            report = patch(installations=[inst])
            self.assertTrue(report.ok)

            # product.json should have been modified
            updated_pj = product_json.read_bytes()
            self.assertNotEqual(original_pj, updated_pj)

            # Verify checksums match actual file contents
            data = json.loads(updated_pj)
            checksums = data["checksums"]
            for rel_posix, abs_path in checksum_files.items():
                expected = _b64sha256(abs_path.read_bytes())
                self.assertEqual(checksums[rel_posix], expected,
                                 f"Checksum mismatch for {rel_posix}")

    def test_checksums_backup_created(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            contents = {
                "cursor-agent-exec": AUTORUN_CONTENT,
                "cursor-always-local": MODELS_CONTENT,
            }
            inst = _make_test_installation(root, contents)
            _add_ext_host_with_hashes(root, contents)
            wb = _add_workbench_file(root)

            out_dir = root / "out"
            ext_host = root / _EXT_HOST_RELPATH
            _add_product_json_with_checksums(root, {
                ext_host.relative_to(out_dir).as_posix(): ext_host,
                wb.relative_to(out_dir).as_posix(): wb,
            })

            product_json = root / "product.json"
            patch(installations=[inst])
            self.assertTrue(has_backup(product_json))

    def test_unpatch_restores_product_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            contents = {
                "cursor-agent-exec": AUTORUN_CONTENT,
                "cursor-always-local": MODELS_CONTENT,
            }
            inst = _make_test_installation(root, contents)
            ext_host = _add_ext_host_with_hashes(root, contents)
            wb = _add_workbench_file(root)

            out_dir = root / "out"
            _add_product_json_with_checksums(root, {
                ext_host.relative_to(out_dir).as_posix(): ext_host,
                wb.relative_to(out_dir).as_posix(): wb,
            })

            product_json = root / "product.json"
            original_pj = product_json.read_bytes()

            patch(installations=[inst])
            self.assertNotEqual(product_json.read_bytes(), original_pj)

            report = unpatch(installations=[inst])
            self.assertTrue(report.ok)
            self.assertIn(product_json, report.restored)
            self.assertEqual(product_json.read_bytes(), original_pj)
            self.assertFalse(has_backup(product_json))

    def test_empty_checksums_skipped(self):
        """Server installs with empty checksums should not modify product.json."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            contents = {
                "cursor-agent-exec": AUTORUN_CONTENT,
                "cursor-always-local": MODELS_CONTENT,
            }
            inst = _make_test_installation(root, contents)
            _add_ext_host_with_hashes(root, contents)

            # Default product.json has no checksums field → treated as empty
            product_json = root / "product.json"
            original_pj = product_json.read_bytes()

            patch(installations=[inst])
            # product.json should not have a backup (no checksums to update)
            self.assertFalse(has_backup(product_json))


if __name__ == "__main__":
    unittest.main()
