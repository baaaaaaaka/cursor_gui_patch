"""Patch registry."""

from __future__ import annotations

from typing import Dict, Type

from .base import BasePatch
from .autorun import AutoRunPatch
from .autorun_workbench import AutoRunWorkbenchPatch
from .models import ModelsPatch

# Registry: patch name → patch class
PATCHES: Dict[str, Type[BasePatch]] = {
    "autorun": AutoRunPatch,
    "autorun_workbench": AutoRunWorkbenchPatch,
    "models": ModelsPatch,
}


def get_patch(name: str) -> BasePatch:
    """Instantiate a patch by name."""
    cls = PATCHES.get(name)
    if cls is None:
        raise ValueError(f"Unknown patch: {name!r}")
    return cls()
