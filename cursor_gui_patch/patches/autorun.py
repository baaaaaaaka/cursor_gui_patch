"""Auto-run controls patch: disable team admin settings in agent extensions."""

from __future__ import annotations

import re
from typing import Tuple

from .base import BasePatch, PatchResult

_MARKER = "CGP_PATCH_AUTORUN_DISABLED"

# Patch the caching layer's getTeamAdminSettings() to always return undefined.
# This single injection neutralises ALL downstream admin restrictions:
#   getAutoRunControls, getNetworkAccessControls, getSandboxingControls,
#   getShouldBlockMcp, getDeleteFileProtection, isServerBlocked, etc.
# Matches: async getTeamAdminSettings(){return(Date.now()-...
_RE_METHOD_OPEN = re.compile(
    r"(async\s+getTeamAdminSettings\s*\(\s*\)\s*\{)"
)


class AutoRunPatch(BasePatch):
    @property
    def name(self) -> str:
        return "autorun"

    @property
    def marker(self) -> str:
        return _MARKER

    def is_applicable(self, content: str) -> bool:
        return "getTeamAdminSettings" in content and _RE_METHOD_OPEN.search(content) is not None

    def apply(self, content: str) -> Tuple[str, PatchResult]:
        result = PatchResult()

        if self.is_already_patched(content):
            result.already_patched = True
            return content, result

        if not self.is_applicable(content):
            result.not_applicable = True
            return content, result

        # Inject early return right after the method opening brace.
        # Original: async getTeamAdminSettings(){return(Date.now()-...
        # Patched:  async getTeamAdminSettings(){return void 0/* marker */;return(Date.now()-...
        injection = f"return void 0/* {_MARKER} */;"
        new_content, n = _RE_METHOD_OPEN.subn(
            lambda m: m.group(1) + injection,
            content,
        )

        if n > 0:
            result.applied = True
            result.replacements = n
            result.details.append(f"Injected early return in {n} getTeamAdminSettings method(s)")
        else:
            result.not_applicable = True

        return new_content, result
