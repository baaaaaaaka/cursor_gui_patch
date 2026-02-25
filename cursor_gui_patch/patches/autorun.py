"""Auto-run controls patch: disable team admin auto-run restrictions."""

from __future__ import annotations

import re
from typing import Tuple

from .base import BasePatch, PatchResult

_MARKER = "CGP_PATCH_AUTORUN_DISABLED"

# Minimal injection: match the method opening and inject an early return.
# Matches: async getAutoRunControls(){
# We inject: return void 0/* marker */; right after the opening brace.
# The rest of the method body is left intact (unreachable but valid JS).
# This is safer than replacing the entire method body because it preserves
# the file structure and avoids subtle issues with brace matching.
_RE_METHOD_OPEN = re.compile(
    r"(async\s+getAutoRunControls\s*\(\s*\)\s*\{)"
)


class AutoRunPatch(BasePatch):
    @property
    def name(self) -> str:
        return "autorun"

    @property
    def marker(self) -> str:
        return _MARKER

    def is_applicable(self, content: str) -> bool:
        return "getAutoRunControls" in content and _RE_METHOD_OPEN.search(content) is not None

    def apply(self, content: str) -> Tuple[str, PatchResult]:
        result = PatchResult()

        # Check marker first: after patching, original patterns may be gone
        if self.is_already_patched(content):
            result.already_patched = True
            return content, result

        if not self.is_applicable(content):
            result.not_applicable = True
            return content, result

        # Inject early return right after the method opening brace.
        # Original: async getAutoRunControls(){const e=...
        # Patched:  async getAutoRunControls(){return void 0/* CGP_PATCH_AUTORUN_DISABLED */;const e=...
        injection = f"return void 0/* {_MARKER} */;"
        new_content, n = _RE_METHOD_OPEN.subn(
            lambda m: m.group(1) + injection,
            content,
        )

        if n > 0:
            result.applied = True
            result.replacements = n
            result.details.append(f"Injected early return in {n} method(s)")
        else:
            result.not_applicable = True

        return new_content, result
