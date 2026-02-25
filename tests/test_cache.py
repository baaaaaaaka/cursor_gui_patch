"""Tests for the file-stat cache."""

import os
import tempfile
import unittest
from pathlib import Path

from cursor_gui_patch.cache import (
    STATUS_NOT_APPLICABLE,
    STATUS_PATCHED,
    cache_entry_matches,
    cache_path,
    load_cache,
    make_cache_entry,
    make_cache_key,
    save_cache,
)


class TestCachePath(unittest.TestCase):
    def test_cache_path(self):
        root = Path("/some/dir")
        self.assertEqual(cache_path(root), Path("/some/dir/.cgp-patch-cache.json"))


class TestCacheKey(unittest.TestCase):
    def test_relative(self):
        root = Path("/a/b")
        path = Path("/a/b/c/d.js")
        self.assertEqual(make_cache_key(path, root), "c/d.js")

    def test_absolute_fallback(self):
        root = Path("/x/y")
        path = Path("/a/b/c.js")
        key = make_cache_key(path, root)
        self.assertIn("c.js", key)


class TestCacheEntryMatches(unittest.TestCase):
    def test_matches(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            f.flush()
            try:
                st = os.stat(f.name)
                entry = make_cache_entry(STATUS_PATCHED, st)
                self.assertTrue(cache_entry_matches(entry, st))
            finally:
                os.unlink(f.name)

    def test_mismatch_after_modify(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".js") as f:
            f.write("original")
            f.flush()
            try:
                st1 = os.stat(f.name)
                entry = make_cache_entry(STATUS_PATCHED, st1)

                # Modify file
                with open(f.name, "w") as f2:
                    f2.write("modified content that is different length")
                st2 = os.stat(f.name)

                self.assertFalse(cache_entry_matches(entry, st2))
            finally:
                os.unlink(f.name)


class TestSaveLoadCache(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            files = {
                "ext/main.js": make_cache_entry(STATUS_PATCHED, os.stat(d)),
                "ext2/main.js": make_cache_entry(STATUS_NOT_APPLICABLE, os.stat(d)),
            }
            save_cache(root, files)

            loaded = load_cache(root)
            self.assertIsNotNone(loaded)
            self.assertIn("ext/main.js", loaded)
            self.assertEqual(loaded["ext/main.js"]["status"], STATUS_PATCHED)
            self.assertIn("ext2/main.js", loaded)

    def test_load_missing(self):
        with tempfile.TemporaryDirectory() as d:
            loaded = load_cache(Path(d))
            self.assertIsNone(loaded)

    def test_load_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".cgp-patch-cache.json").write_text("not json")
            loaded = load_cache(root)
            self.assertIsNone(loaded)

    def test_load_wrong_version(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".cgp-patch-cache.json").write_text(
                '{"version": 999, "signature": "wrong", "files": {}}'
            )
            loaded = load_cache(root)
            self.assertIsNone(loaded)


if __name__ == "__main__":
    unittest.main()
