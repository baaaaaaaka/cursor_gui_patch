"""Tests for the auto-run controls patch."""

import unittest

from cursor_gui_patch.patches.autorun import AutoRunPatch

# Sample extracted from cursor-agent-exec/dist/main.js
SAMPLE_METHOD = (
    'async getAutoRunControls(){const e=await this.getTeamAdminSettings();'
    'if(e?.autoRunControls?.enabled)return{enabled:e.autoRunControls.enabled,'
    'allowed:e.autoRunControls.allowed??[],blocked:e.autoRunControls.blocked??[],'
    'enableRunEverything:e.autoRunControls.enableRunEverything??!1,'
    'mcpToolAllowlist:e.autoRunControls.mcpToolAllowlist??[]}}'
)

SAMPLE_CALL_1 = (
    'const h=await this.teamSettingsService.getAutoRunControls(),'
    'p={type:"insecure_none"}'
)

SAMPLE_CALL_2 = (
    'const l=await this.teamSettingsService.getAutoRunControls(),'
    'u=!0===l?.enabled'
)

SAMPLE_FULL = f"prefix;{SAMPLE_METHOD};middle;{SAMPLE_CALL_1};between;{SAMPLE_CALL_2};suffix"


class TestAutoRunPatch(unittest.TestCase):
    def setUp(self):
        self.patch = AutoRunPatch()

    def test_name(self):
        self.assertEqual(self.patch.name, "autorun")

    def test_marker(self):
        self.assertEqual(self.patch.marker, "CGP_PATCH_AUTORUN_DISABLED")

    def test_is_applicable_true(self):
        self.assertTrue(self.patch.is_applicable(SAMPLE_FULL))

    def test_is_applicable_false(self):
        self.assertFalse(self.patch.is_applicable("some random code"))

    def test_is_applicable_needs_method(self):
        # Has getAutoRunControls as a string but no method definition
        self.assertFalse(self.patch.is_applicable("getAutoRunControls"))

    def test_apply_injects_early_return(self):
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertTrue(result.applied)
        self.assertIn("CGP_PATCH_AUTORUN_DISABLED", new_content)
        # The method should have an early return injected
        self.assertIn(
            "async getAutoRunControls(){return void 0/* CGP_PATCH_AUTORUN_DISABLED */;",
            new_content,
        )
        # Original method body is preserved (unreachable but still present)
        self.assertIn("getTeamAdminSettings", new_content)

    def test_apply_preserves_call_sites(self):
        """New approach: call sites are NOT modified."""
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertTrue(result.applied)
        # Call sites should remain untouched
        self.assertIn("this.teamSettingsService.getAutoRunControls()", new_content)

    def test_apply_replacement_count(self):
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertEqual(result.replacements, 1)  # 1 method injection only

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

    def test_method_only(self):
        """Test with just the method, no call sites."""
        content = f"prefix;{SAMPLE_METHOD};suffix"
        new_content, result = self.patch.apply(content)
        self.assertTrue(result.applied)
        self.assertEqual(result.replacements, 1)

    def test_minimal_change(self):
        """The patch should only add bytes, not remove any."""
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertTrue(result.applied)
        # Patched content should be longer (we injected, not replaced)
        self.assertGreater(len(new_content), len(SAMPLE_FULL))


if __name__ == "__main__":
    unittest.main()
