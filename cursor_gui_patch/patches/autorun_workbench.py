"""Workbench autorun patch: force isDisabledByAdmin to false in workbench.desktop.main.js."""

from __future__ import annotations

from typing import Tuple

from .base import BasePatch, PatchResult

_MARKER = "CGP_PATCH_AUTORUN_WORKBENCH"

# Default value: loaded before team settings arrive
_OLD_DEFAULT = "isAdminControlled:!1,isDisabledByAdmin:!0"
_NEW_DEFAULT = "isAdminControlled:!1,isDisabledByAdmin:!1"

# Computed value: result of team settings evaluation
_OLD_COMPUTED = "isDisabledByAdmin:v.length+w.length===0&&!S&&k.length===0&&!D"
_NEW_COMPUTED = "isDisabledByAdmin:!1"


class AutoRunWorkbenchPatch(BasePatch):
    @property
    def name(self) -> str:
        return "autorun_workbench"

    @property
    def marker(self) -> str:
        return _MARKER

    def is_applicable(self, content: str) -> bool:
        return _OLD_DEFAULT in content or _OLD_COMPUTED in content

    def apply(self, content: str) -> Tuple[str, PatchResult]:
        result = PatchResult()

        if self.is_already_patched(content):
            result.already_patched = True
            return content, result

        if not self.is_applicable(content):
            result.not_applicable = True
            return content, result

        new_content = content
        count = 0

        # Patch default value
        if _OLD_DEFAULT in new_content:
            new_content = new_content.replace(_OLD_DEFAULT, _NEW_DEFAULT, 1)
            count += 1
            result.details.append("Patched isDisabledByAdmin default value")

        # Patch computed value
        if _OLD_COMPUTED in new_content:
            new_content = new_content.replace(_OLD_COMPUTED, _NEW_COMPUTED, 1)
            count += 1
            result.details.append("Patched isDisabledByAdmin computed value")

        if count > 0:
            # Inject marker as a JS comment after the last replacement site.
            # Prefer attaching to the computed replacement; fall back to default.
            if _NEW_COMPUTED in new_content:
                new_content = new_content.replace(
                    _NEW_COMPUTED,
                    f"{_NEW_COMPUTED}/* {_MARKER} */",
                    1,
                )
            else:
                new_content = new_content.replace(
                    _NEW_DEFAULT,
                    f"{_NEW_DEFAULT}/* {_MARKER} */",
                    1,
                )
            result.applied = True
            result.replacements = count
        else:
            result.not_applicable = True

        return new_content, result
