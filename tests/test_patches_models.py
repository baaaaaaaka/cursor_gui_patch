"""Tests for the model enumeration patch."""

import unittest

from cursor_gui_patch.patches.models import ModelsPatch

# Sample: AgentService with r. prefix (same prefix has AvailableModels)
SAMPLE_AGENT_SERVICE = (
    'nameAgent:{name:"NameAgent",I:r.NameAgentRequest,O:r.NameAgentResponse,kind:s.MethodKind.Unary},'
    'getUsableModels:{name:"GetUsableModels",I:r.GetUsableModelsRequest,O:r.GetUsableModelsResponse,kind:s.MethodKind.Unary},'
    'getDefaultModelForCli:{name:"GetDefaultModelForCli",I:r.GetDefaultModelForCliRequest,O:r.GetDefaultModelForCliResponse,kind:s.MethodKind.Unary}'
)

# Sample: AiServerService with availableModels descriptor (provides the prefix)
SAMPLE_AISERVER_SERVICE = (
    'throwErrorCheck:{name:"ThrowErrorCheck",I:r.ThrowErrorCheckRequest,O:r.ThrowErrorCheckResponse,kind:s.MethodKind.Unary},'
    'availableModels:{name:"AvailableModels",I:r.AvailableModelsRequest,O:r.AvailableModelsResponse,kind:s.MethodKind.Unary},'
    'streamChatTryReallyHard:{name:"StreamChatTryReallyHard",I:r.GetChatRequest,O:r.StreamChatResponse,kind:s.MethodKind.Unary}'
)

# Sample: BackgroundComposerService with f. prefix (different from available's prefix)
SAMPLE_BG_SERVICE = (
    'getBackgroundComposerFeedbackLink:{name:"GetBackgroundComposerFeedbackLink",I:f.GetBackgroundComposerFeedbackLinkRequest,O:f.GetBackgroundComposerFeedbackLinkResponse,kind:s.MethodKind.Unary},'
    'getUsableModels:{name:"GetUsableModels",I:f.GetUsableModelsRequest,O:f.GetUsableModelsResponse,kind:s.MethodKind.Unary},'
    'getDefaultModelForCli:{name:"GetDefaultModelForCli",I:f.GetDefaultModelForCliRequest,O:f.GetDefaultModelForCliResponse,kind:s.MethodKind.Unary}'
)

# Full sample with both services + type definitions
SAMPLE_FULL = (
    f"/* types */ r.AvailableModelsRequest; r.AvailableModelsResponse; "
    f"r.GetUsableModelsRequest; r.GetUsableModelsResponse; "
    f"f.GetUsableModelsRequest; f.GetUsableModelsResponse; "
    f"/* AgentService */ {SAMPLE_AGENT_SERVICE}; "
    f"/* AiServerService */ {SAMPLE_AISERVER_SERVICE}; "
    f"/* BackgroundComposerService */ {SAMPLE_BG_SERVICE}; "
)

# Sample: cursor-retrieval style (f. prefix for GetUsableModels, n. for AvailableModels)
SAMPLE_RETRIEVAL = (
    'throwErrorCheck:{name:"ThrowErrorCheck",I:n.ThrowErrorCheckRequest,O:n.ThrowErrorCheckResponse,kind:s.MethodKind.Unary},'
    'availableModels:{name:"AvailableModels",I:n.AvailableModelsRequest,O:n.AvailableModelsResponse,kind:s.MethodKind.Unary},'
    'streamChatTryReallyHard:{name:"StreamChatTryReallyHard"};'
    'getUsableModels:{name:"GetUsableModels",I:f.GetUsableModelsRequest,O:f.GetUsableModelsResponse,kind:s.MethodKind.Unary},'
    'getDefaultModelForCli:{name:"GetDefaultModelForCli"}'
)


class TestModelsPatch(unittest.TestCase):
    def setUp(self):
        self.patch = ModelsPatch()

    def test_name(self):
        self.assertEqual(self.patch.name, "models")

    def test_marker(self):
        self.assertEqual(self.patch.marker, "CGP_PATCH_MODELS_AVAILABLE")

    def test_is_applicable_true(self):
        self.assertTrue(self.patch.is_applicable(SAMPLE_FULL))

    def test_is_applicable_false(self):
        self.assertFalse(self.patch.is_applicable("some random code"))

    def test_apply_same_prefix(self):
        """Test when GetUsableModels prefix matches AvailableModels prefix."""
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertTrue(result.applied)
        self.assertEqual(result.replacements, 2)
        self.assertIn("CGP_PATCH_MODELS_AVAILABLE", new_content)
        # Both descriptors should be patched
        self.assertNotIn('name:"GetUsableModels"', new_content)
        self.assertIn('name:"AvailableModels"', new_content)

    def test_apply_agent_service_uses_same_prefix(self):
        """AgentService uses r. prefix, and r.AvailableModelsRequest exists."""
        new_content, result = self.patch.apply(SAMPLE_FULL)
        self.assertIn("I:r.AvailableModelsRequest", new_content)
        self.assertIn("O:r.AvailableModelsResponse", new_content)

    def test_apply_bg_service_uses_fallback_prefix(self):
        """BackgroundComposerService uses f. but falls back to r. from nearest availableModels."""
        new_content, result = self.patch.apply(SAMPLE_FULL)
        # The f. prefix replacement should use r. (from the nearest availableModels descriptor)
        # There should be no f.AvailableModelsRequest (since it doesn't exist)
        self.assertNotIn("f.AvailableModelsRequest", new_content)

    def test_apply_retrieval_style(self):
        """cursor-retrieval: f. for GetUsableModels, n. for AvailableModels."""
        new_content, result = self.patch.apply(SAMPLE_RETRIEVAL)
        self.assertTrue(result.applied)
        self.assertEqual(result.replacements, 1)
        # Should use n. prefix from the nearest availableModels descriptor
        self.assertIn("I:n.AvailableModelsRequest", new_content)
        self.assertIn("O:n.AvailableModelsResponse", new_content)

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
        self.assertEqual(content, new_content)

    def test_preserves_surrounding_code(self):
        """Ensure patch doesn't corrupt surrounding content."""
        new_content, result = self.patch.apply(SAMPLE_FULL)
        # AgentService method before getUsableModels should still be there
        self.assertIn('nameAgent:{name:"NameAgent"', new_content)
        # Methods after should still be there
        self.assertIn('getDefaultModelForCli:{name:"GetDefaultModelForCli"', new_content)
        # AiServerService's availableModels should be untouched
        self.assertIn(
            'availableModels:{name:"AvailableModels",I:r.AvailableModelsRequest',
            new_content,
        )


if __name__ == "__main__":
    unittest.main()
