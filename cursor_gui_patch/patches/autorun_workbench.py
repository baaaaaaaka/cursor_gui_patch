"""Workbench autorun patch: disable admin autorun controls in workbench.desktop.main.js."""

from __future__ import annotations

from typing import Tuple

from .base import BasePatch, PatchResult

_MARKER = "CGP_PATCH_AUTORUN_WORKBENCH"

# The workbench independently fetches team admin settings and checks:
#   const s = r?.autoRunControls?.enabled ?? !1;
#   if (s) { /* build admin-controlled state */ }
# Replacing the check with !1 (false) prevents the admin-controlled branch
# from ever executing, so the UI stays in user-controlled mode.
_OLD_ENABLED_CHECK = "r?.autoRunControls?.enabled??!1"
_NEW_ENABLED_CHECK = "!1"


class AutoRunWorkbenchPatch(BasePatch):
    @property
    def name(self) -> str:
        return "autorun_workbench"

    @property
    def marker(self) -> str:
        return _MARKER

    def is_applicable(self, content: str) -> bool:
        return _OLD_ENABLED_CHECK in content

    def apply(self, content: str) -> Tuple[str, PatchResult]:
        result = PatchResult()

        if self.is_already_patched(content):
            result.already_patched = True
            return content, result

        if not self.is_applicable(content):
            result.not_applicable = True
            return content, result

        new_content = content.replace(
            _OLD_ENABLED_CHECK,
            f"{_NEW_ENABLED_CHECK}/* {_MARKER} */",
            1,
        )

        result.applied = True
        result.replacements = 1
        result.details.append("Disabled autoRunControls.enabled check")

        return new_content, result
