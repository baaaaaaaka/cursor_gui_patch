"""Tests for the auto-run controls patch."""

import unittest

from cursor_gui_patch.patches.autorun import AutoRunPatch

# Sample extracted from cursor-agent-exec/dist/main.js
# The caching layer's getTeamAdminSettings() that we target:
SAMPLE_METHOD = (
    'async getTeamAdminSettings(){return(Date.now()-this.lastFetchTime>ra||'
    'void 0===await this.settingsPromise)&&(this.settingsPromise=this.fetchSettings()),'
    'this.settingsPromise}'
)

# Downstream callers that read from getTeamAdminSettings — we do NOT touch these:
SAMPLE_CALLER_1 = (
    'async getAutoRunControls(){const e=await this.getTeamAdminSettings();'
    'if(e?.autoRunControls?.enabled)return{enabled:e.autoRunControls.enabled}}'
)
SAMPLE_CALLER_2 = (
    'async getShouldBlockMcp(){const e=await this.getTeamAdminSettings();'
    'return!(!e?.autoRunControls?.enabled||!e?.autoRunControls?.disableMcpAutoRun)}'
)

SAMPLE_FULL = f"prefix;{SAMPLE_METHOD};middle;{SAMPLE_CALLER_1};between;{SAMPLE_CALLER_2};suffix"


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
        # Has getTeamAdminSettings as a string but no async method definition
        self.assertFalse(self.patch.is_applicable("getTeamAdminSettings"))

    def test_apply_injects_early_return(self):
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertTrue(result.applied)
        self.assertIn("CGP_PATCH_AUTORUN_DISABLED", new_content)
        self.assertIn(
            "async getTeamAdminSettings(){return void 0/* CGP_PATCH_AUTORUN_DISABLED */;",
            new_content,
        )
        # Original method body is preserved (unreachable but still present)
        self.assertIn("this.lastFetchTime", new_content)

    def test_apply_preserves_callers(self):
        """Downstream methods that call getTeamAdminSettings remain untouched."""
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertTrue(result.applied)
        self.assertIn("getAutoRunControls", new_content)
        self.assertIn("getShouldBlockMcp", new_content)

    def test_apply_replacement_count(self):
        new_content, result = self.patch.apply(SAMPLE_FULL)
        # Only the caching layer's method should be patched (1 injection)
        self.assertEqual(result.replacements, 1)

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
        """Test with just the method, no callers."""
        content = f"prefix;{SAMPLE_METHOD};suffix"
        new_content, result = self.patch.apply(content)
        self.assertTrue(result.applied)
        self.assertEqual(result.replacements, 1)

    def test_minimal_change(self):
        """The patch should only add bytes, not remove any."""
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertTrue(result.applied)
        self.assertGreater(len(new_content), len(SAMPLE_FULL))


if __name__ == "__main__":
    unittest.main()
