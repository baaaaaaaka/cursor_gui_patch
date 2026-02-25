"""Tests for the workbench autorun patch."""

import unittest

from cursor_gui_patch.patches.autorun_workbench import AutoRunWorkbenchPatch

# Sample extracted from workbench.desktop.main.js (minified)
SAMPLE = (
    'prefix;r=void 0}const s=r?.autoRunControls?.enabled??!1;BNp(s);let o;'
    'if(s){const v=r?.autoRunControls?.allowed??[]};suffix'
)


class TestAutoRunWorkbenchPatch(unittest.TestCase):
    def setUp(self):
        self.patch = AutoRunWorkbenchPatch()

    def test_name(self):
        self.assertEqual(self.patch.name, "autorun_workbench")

    def test_marker(self):
        self.assertEqual(self.patch.marker, "CGP_PATCH_AUTORUN_WORKBENCH")

    def test_is_applicable_true(self):
        self.assertTrue(self.patch.is_applicable(SAMPLE))

    def test_is_applicable_false(self):
        self.assertFalse(self.patch.is_applicable("some random code"))

    def test_apply_disables_enabled_check(self):
        new_content, result = self.patch.apply(SAMPLE)
        self.assertTrue(result.applied)
        self.assertEqual(result.replacements, 1)
        self.assertIn("CGP_PATCH_AUTORUN_WORKBENCH", new_content)
        # The enabled check should be replaced with !1 (false)
        self.assertNotIn("r?.autoRunControls?.enabled", new_content)
        self.assertIn("const s=!1/* CGP_PATCH_AUTORUN_WORKBENCH */;", new_content)

    def test_apply_preserves_surrounding_code(self):
        new_content, result = self.patch.apply(SAMPLE)
        self.assertTrue(result.applied)
        self.assertIn("prefix;", new_content)
        self.assertIn(";suffix", new_content)
        # The if(s) branch is still there, just s is always false
        self.assertIn("if(s){", new_content)

    def test_idempotent(self):
        new_content, result1 = self.patch.apply(SAMPLE)
        self.assertTrue(result1.applied)

        new_content2, result2 = self.patch.apply(new_content)
        self.assertTrue(result2.already_patched)
        self.assertFalse(result2.applied)
        self.assertEqual(new_content, new_content2)

    def test_not_applicable(self):
        content = "function foo() { return 42; }"
        new_content, result = self.patch.apply(content)
        self.assertTrue(result.not_applicable)
        self.assertFalse(result.applied)
        self.assertEqual(content, new_content)


if __name__ == "__main__":
    unittest.main()
