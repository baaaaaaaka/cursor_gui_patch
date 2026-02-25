"""Base class for all patches."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class PatchResult:
    """Result of applying a single patch to a single file."""
    applied: bool = False  # True if content was modified
    already_patched: bool = False  # True if patch marker already present
    not_applicable: bool = False  # True if target pattern not found
    replacements: int = 0  # Number of replacements made
    details: List[str] = field(default_factory=list)  # Human-readable details


class BasePatch(ABC):
    """Abstract base class for patches."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. 'autorun' or 'models'."""
        ...

    @property
    @abstractmethod
    def marker(self) -> str:
        """Marker string injected into patched content for idempotency detection."""
        ...

    @abstractmethod
    def is_applicable(self, content: str) -> bool:
        """Return True if the content contains patterns this patch targets."""
        ...

    def is_already_patched(self, content: str) -> bool:
        """Return True if the patch marker is already present."""
        return self.marker in content

    @abstractmethod
    def apply(self, content: str) -> Tuple[str, PatchResult]:
        """
        Apply the patch to content.

        Returns (new_content, result).
        If already patched or not applicable, returns content unchanged.
        """
        ...
