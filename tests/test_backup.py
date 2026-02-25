"""Tests for backup/restore."""

import tempfile
import unittest
from pathlib import Path

from cursor_gui_patch.backup import (
    backup_path,
    create_backup,
    has_backup,
    remove_backup,
    restore_backup,
)


class TestBackup(unittest.TestCase):
    def test_backup_path(self):
        p = Path("/some/file.js")
        self.assertEqual(backup_path(p), Path("/some/file.js.cgp.bak"))

    def test_create_and_restore(self):
        with tempfile.TemporaryDirectory() as d:
            original = Path(d) / "test.js"
            original.write_text("original content")

            # Create backup
            bak = create_backup(original)
            self.assertIsNotNone(bak)
            self.assertTrue(bak.exists())
            self.assertEqual(bak.read_text(), "original content")

            # Modify original
            original.write_text("modified content")
            self.assertEqual(original.read_text(), "modified content")

            # Restore
            self.assertTrue(restore_backup(original))
            self.assertEqual(original.read_text(), "original content")

    def test_create_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            original = Path(d) / "test.js"
            original.write_text("original content")

            bak1 = create_backup(original)
            original.write_text("modified content")
            bak2 = create_backup(original)

            # Backup should still contain original content
            self.assertEqual(bak1, bak2)
            self.assertEqual(bak1.read_text(), "original content")

    def test_has_backup(self):
        with tempfile.TemporaryDirectory() as d:
            original = Path(d) / "test.js"
            original.write_text("content")

            self.assertFalse(has_backup(original))
            create_backup(original)
            self.assertTrue(has_backup(original))

    def test_remove_backup(self):
        with tempfile.TemporaryDirectory() as d:
            original = Path(d) / "test.js"
            original.write_text("content")

            create_backup(original)
            self.assertTrue(has_backup(original))
            self.assertTrue(remove_backup(original))
            self.assertFalse(has_backup(original))

    def test_restore_no_backup(self):
        with tempfile.TemporaryDirectory() as d:
            original = Path(d) / "test.js"
            original.write_text("content")
            self.assertFalse(restore_backup(original))

    def test_remove_no_backup(self):
        with tempfile.TemporaryDirectory() as d:
            original = Path(d) / "test.js"
            original.write_text("content")
            self.assertFalse(remove_backup(original))


if __name__ == "__main__":
    unittest.main()
