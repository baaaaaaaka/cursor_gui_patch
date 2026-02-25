"""Model enumeration patch: redirect GetUsableModels to AvailableModels."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .base import BasePatch, PatchResult

_MARKER = "CGP_PATCH_MODELS_AVAILABLE"

# Match a getUsableModels service descriptor entry:
#   getUsableModels:{name:"GetUsableModels",I:X.GetUsableModelsRequest,O:X.GetUsableModelsResponse,kind:s.MethodKind.Unary}
#
# X is a single-letter (or short) module prefix variable.
# We capture the prefix to reuse it for the replacement types.
_RE_DESCRIPTOR = re.compile(
    r"getUsableModels:\{"
    r'name:"GetUsableModels",'
    r"I:(\w+)\.GetUsableModelsRequest,"
    r"O:\1\.GetUsableModelsResponse,"
    r"kind:(\w+)\.MethodKind\.Unary"
    r"\}"
)

# Match the availableModels descriptor to extract its prefix:
#   availableModels:{name:"AvailableModels",I:Y.AvailableModelsRequest,...}
_RE_AVAILABLE_DESCRIPTOR = re.compile(
    r"availableModels:\{"
    r'name:"AvailableModels",'
    r"I:(\w+)\.AvailableModelsRequest,"
    r"O:\1\.AvailableModelsResponse,"
    r"kind:(\w+)\.MethodKind\.Unary"
    r"\}"
)


def _find_available_prefixes(content: str) -> List[Tuple[int, str, str]]:
    """
    Find all availableModels descriptors and return (position, prefix, kind_var).

    These tell us which webpack module variables have AvailableModelsRequest/Response.
    """
    results = []
    for m in _RE_AVAILABLE_DESCRIPTOR.finditer(content):
        results.append((m.start(), m.group(1), m.group(2)))
    return results


def _find_nearest_available_prefix(
    pos: int,
    available: List[Tuple[int, str, str]],
) -> Optional[Tuple[str, str]]:
    """Find the nearest availableModels descriptor by position. Returns (prefix, kind_var)."""
    if not available:
        return None
    best = min(available, key=lambda t: abs(t[0] - pos))
    return best[1], best[2]


def _make_replacement(prefix: str, kind_var: str) -> str:
    """Build the replacement descriptor string."""
    return (
        f"getUsableModels:{{name:\"AvailableModels\","
        f"I:{prefix}.AvailableModelsRequest,"
        f"O:{prefix}.AvailableModelsResponse,"
        f"kind:{kind_var}.MethodKind.Unary"
        f"}}/* {_MARKER} */"
    )


class ModelsPatch(BasePatch):
    @property
    def name(self) -> str:
        return "models"

    @property
    def marker(self) -> str:
        return _MARKER

    def is_applicable(self, content: str) -> bool:
        return "GetUsableModels" in content and "MethodKind" in content

    def apply(self, content: str) -> Tuple[str, PatchResult]:
        result = PatchResult()

        # Check marker first: after patching, original patterns may be gone
        if self.is_already_patched(content):
            result.already_patched = True
            return content, result

        if not self.is_applicable(content):
            result.not_applicable = True
            return content, result

        # Pre-scan: find all availableModels descriptors for prefix fallback.
        available_prefixes = _find_available_prefixes(content)

        new_content = content
        total = 0

        def replacer(m: re.Match) -> str:
            nonlocal total
            prefix = m.group(1)
            kind_var = m.group(2)

            # Strategy 1: same prefix has AvailableModelsRequest
            if f"{prefix}.AvailableModelsRequest" in content:
                total += 1
                return _make_replacement(prefix, kind_var)

            # Strategy 2: find nearest availableModels descriptor and use its prefix.
            # In webpack bundles, nearby service definitions share the same module scope,
            # so the prefix from the availableModels descriptor is accessible.
            nearest = _find_nearest_available_prefix(m.start(), available_prefixes)
            if nearest is not None:
                alt_prefix, alt_kind = nearest
                total += 1
                return _make_replacement(alt_prefix, kind_var)

            # Can't safely replace
            return m.group(0)

        new_content = _RE_DESCRIPTOR.sub(replacer, new_content)

        if total > 0:
            result.applied = True
            result.replacements = total
            result.details.append(f"Replaced {total} service descriptor(s)")
        else:
            result.not_applicable = True
            result.details.append("Descriptor pattern found but no safe replacements available")

        return new_content, result
