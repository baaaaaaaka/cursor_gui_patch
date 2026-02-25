"""Tests for the workbench autorun patch."""

import unittest

from cursor_gui_patch.patches.autorun_workbench import AutoRunWorkbenchPatch

# Sample extracted from workbench.desktop.main.js (minified)
SAMPLE_DEFAULT = "isAdminControlled:!1,isDisabledByAdmin:!0"
SAMPLE_COMPUTED = "isDisabledByAdmin:v.length+w.length===0&&!S&&k.length===0&&!D"

SAMPLE_FULL = (
    f"prefix;{{{SAMPLE_DEFAULT},allowed:[],blocked:[]}};"
    f"function compute(v,w,S,k,D){{return{{{SAMPLE_COMPUTED}}}}}"
    "suffix;"
)


class TestAutoRunWorkbenchPatch(unittest.TestCase):
    def setUp(self):
        self.patch = AutoRunWorkbenchPatch()

    def test_name(self):
        self.assertEqual(self.patch.name, "autorun_workbench")

    def test_marker(self):
        self.assertEqual(self.patch.marker, "CGP_PATCH_AUTORUN_WORKBENCH")

    def test_is_applicable_both_patterns(self):
        self.assertTrue(self.patch.is_applicable(SAMPLE_FULL))

    def test_is_applicable_default_only(self):
        self.assertTrue(self.patch.is_applicable(f"prefix;{SAMPLE_DEFAULT};suffix"))

    def test_is_applicable_computed_only(self):
        self.assertTrue(self.patch.is_applicable(f"prefix;{SAMPLE_COMPUTED};suffix"))

    def test_is_applicable_false(self):
        self.assertFalse(self.patch.is_applicable("some random code"))

    def test_apply_patches_both(self):
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertTrue(result.applied)
        self.assertEqual(result.replacements, 2)
        self.assertIn("CGP_PATCH_AUTORUN_WORKBENCH", new_content)
        # Default should be patched: !0 → !1
        self.assertIn("isAdminControlled:!1,isDisabledByAdmin:!1", new_content)
        # Computed should be simplified
        self.assertNotIn("v.length+w.length===0", new_content)
        # Old default value gone
        self.assertNotIn("isDisabledByAdmin:!0", new_content)

    def test_apply_default_only(self):
        content = f"prefix;{SAMPLE_DEFAULT};suffix"
        new_content, result = self.patch.apply(content)
        self.assertTrue(result.applied)
        self.assertEqual(result.replacements, 1)
        self.assertIn("CGP_PATCH_AUTORUN_WORKBENCH", new_content)
        self.assertIn("isAdminControlled:!1,isDisabledByAdmin:!1", new_content)

    def test_apply_computed_only(self):
        content = f"prefix;{SAMPLE_COMPUTED};suffix"
        new_content, result = self.patch.apply(content)
        self.assertTrue(result.applied)
        self.assertEqual(result.replacements, 1)
        self.assertIn("CGP_PATCH_AUTORUN_WORKBENCH", new_content)
        self.assertNotIn("v.length+w.length===0", new_content)

    def test_idempotent(self):
        new_content, result1 = self.patch.apply(SAMPLE_FULL)
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
