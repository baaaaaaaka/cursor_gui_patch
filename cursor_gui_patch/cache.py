"""File-stat-based cache to skip unchanged files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_CACHE_FILENAME = ".cgp-patch-cache.json"
_CACHE_VERSION = 1

# Bump this when patch logic changes to invalidate stale caches.
_CACHE_SIGNATURE = "cgp_v1_autorun+models"

STATUS_PATCHED = "already_patched"
STATUS_NOT_APPLICABLE = "not_applicable"


def cache_path(root: Path) -> Path:
    """Return the cache file path for a given installation root."""
    return root / _CACHE_FILENAME


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON atomically via tmp+rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _stat_values(st: os.stat_result) -> Tuple[int, int]:
    """Extract (mtime_ns, size) from a stat result."""
    mtime_ns = getattr(st, "st_mtime_ns", None)
    if not isinstance(mtime_ns, int):
        mtime_ns = int(st.st_mtime * 1_000_000_000)
    return int(mtime_ns), int(st.st_size)


def _coerce_int(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def load_cache(root: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    """Load the patch cache for an installation. Returns None if invalid/missing."""
    p = cache_path(root)
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("version") != _CACHE_VERSION:
        return None
    if obj.get("signature") != _CACHE_SIGNATURE:
        return None
    files = obj.get("files")
    if not isinstance(files, dict):
        return None
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in files.items():
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        mtime_ns = _coerce_int(v.get("mtime_ns"))
        size = _coerce_int(v.get("size"))
        status = v.get("status")
        if mtime_ns is None or size is None:
            continue
        if status not in (STATUS_PATCHED, STATUS_NOT_APPLICABLE):
            continue
        out[k] = {"mtime_ns": mtime_ns, "size": size, "status": status}
    return out


def save_cache(root: Path, files: Dict[str, Dict[str, Any]]) -> None:
    """Save the patch cache."""
    payload = {
        "version": _CACHE_VERSION,
        "signature": _CACHE_SIGNATURE,
        "files": files,
    }
    _atomic_write_json(cache_path(root), payload)


def make_cache_key(path: Path, root: Path) -> str:
    """Create a cache key (relative POSIX path)."""
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.as_posix()


def make_cache_entry(status: str, st: os.stat_result) -> Dict[str, Any]:
    """Create a cache entry from a stat result."""
    mtime_ns, size = _stat_values(st)
    return {"mtime_ns": mtime_ns, "size": size, "status": status}


def cache_entry_matches(entry: Dict[str, Any], st: os.stat_result) -> bool:
    """Check if a cache entry matches the current file stat."""
    mtime_ns, size = _stat_values(st)
    return entry.get("mtime_ns") == mtime_ns and entry.get("size") == size
