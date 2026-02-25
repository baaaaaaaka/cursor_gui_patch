"""Auto-run controls patch: disable team admin auto-run restrictions."""

from __future__ import annotations

import re
from typing import Tuple

from .base import BasePatch, PatchResult

_MARKER = "CGP_PATCH_AUTORUN_DISABLED"

# Pattern 1: Method implementation
# Matches: async getAutoRunControls(){const e=await this.getTeamAdminSettings();if(e?.autoRunControls?.enabled)return{...}}
# The method body reads team settings and returns auto-run config; we replace
# the entire method to return void 0 (undefined).
_RE_METHOD_IMPL = re.compile(
    r"async\s+getAutoRunControls\s*\(\s*\)\s*\{"
    r"const\s+\w+=await\s+this\.getTeamAdminSettings\(\);"
    r"if\(\w+\?\.autoRunControls\?\.enabled\)"
    r"return\{[^}]*\}"
    r"\}"
)

# Pattern 2: Call sites
# Matches: this.teamSettingsService.getAutoRunControls()
# (possibly with await prefix, captured separately)
_RE_CALL_SITE = re.compile(
    r"this\.teamSettingsService\.getAutoRunControls\s*\(\s*\)"
)


class AutoRunPatch(BasePatch):
    @property
    def name(self) -> str:
        return "autorun"

    @property
    def marker(self) -> str:
        return _MARKER

    def is_applicable(self, content: str) -> bool:
        return (
            "getAutoRunControls" in content
            and "teamSettingsService" in content
        )

    def apply(self, content: str) -> Tuple[str, PatchResult]:
        result = PatchResult()

        # Check marker first: after patching, original patterns may be gone
        if self.is_already_patched(content):
            result.already_patched = True
            return content, result

        if not self.is_applicable(content):
            result.not_applicable = True
            return content, result

        new_content = content
        total_replacements = 0

        # Replacement 1: Method implementation → return void 0
        method_replacement = f"async getAutoRunControls(){{return void 0/* {_MARKER} */}}"
        new_content, n = _RE_METHOD_IMPL.subn(method_replacement, new_content)
        total_replacements += n
        if n:
            result.details.append(f"Replaced {n} method implementation(s)")

        # Replacement 2: Call sites → Promise.resolve(void 0)
        call_replacement = f"Promise.resolve(void 0)/* {_MARKER} */"
        new_content, n = _RE_CALL_SITE.subn(call_replacement, new_content)
        total_replacements += n
        if n:
            result.details.append(f"Replaced {n} call site(s)")

        if total_replacements > 0:
            result.applied = True
            result.replacements = total_replacements
        else:
            # Patterns exist but regexes didn't match — treat as not applicable
            result.not_applicable = True

        return new_content, result
