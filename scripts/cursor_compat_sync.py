#!/usr/bin/env python3
"""Update Cursor compatibility table and tested versions file."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
TABLE_PATH = PROJECT_DIR / "docs" / "cursor_compatibility.md"
TESTED_PATH = SCRIPT_DIR / "cursor_tested_versions.txt"

HEADER = "| Cursor Version | Commit | Date | Status |"
SEPARATOR = "|----------------|--------|------|--------|"


def load_existing_table() -> Dict[str, Dict[str, str]]:
    """Parse existing markdown table into {version: {commit, date, status}}."""
    rows: Dict[str, Dict[str, str]] = {}
    if not TABLE_PATH.exists():
        return rows
    columns: List[str] = []
    for line in TABLE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 2:
            continue
        if not columns:
            columns = parts
            continue
        if all(re.match(r"^-+$", p) for p in parts):
            continue
        row = {columns[i]: parts[i] for i in range(min(len(columns), len(parts)))}
        version = row.get("Cursor Version", "")
        if version:
            rows[version] = row
    return rows


def load_tested_versions() -> Dict[str, Dict[str, str]]:
    """Parse tested versions file."""
    versions: Dict[str, Dict[str, str]] = {}
    if not TESTED_PATH.exists():
        return versions
    for line in TESTED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 4:
            versions[parts[0]] = {
                "commit": parts[1],
                "date": parts[2],
                "status": parts[3],
            }
    return versions


def render_table(rows: Dict[str, Dict[str, str]]) -> str:
    """Render markdown table."""
    lines = [
        "# Cursor Compatibility",
        "",
        "Automatically updated by CI.",
        "",
        HEADER,
        SEPARATOR,
    ]
    for version in sorted(rows.keys(), key=lambda v: [int(x) for x in v.split(".") if x.isdigit()]):
        row = rows[version]
        commit = row.get("Commit", row.get("commit", ""))[:8]
        date = row.get("Date", row.get("date", ""))
        status = row.get("Status", row.get("status", "unknown"))
        lines.append(f"| {version} | {commit} | {date} | {status} |")
    lines.append("")
    return "\n".join(lines)


def render_tested_versions(versions: Dict[str, Dict[str, str]]) -> str:
    """Render tested versions file."""
    lines = [
        "# Cursor versions that have been tested with cgp",
        "# Format: cursor_version commit_hash date status",
    ]
    for version in sorted(versions.keys(), key=lambda v: [int(x) for x in v.split(".") if x.isdigit()]):
        v = versions[version]
        lines.append(f"{version} {v['commit']} {v['date']} {v['status']}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--missing-json", required=True, help="JSON array of {version, commit}")
    parser.add_argument("--results-dir", default="results", help="Directory with test result JSON files")
    args = parser.parse_args()

    missing = json.loads(args.missing_json)
    results_dir = Path(args.results_dir)

    # Load existing test results.
    test_results: Dict[str, Dict[str, Any]] = {}
    for json_file in results_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                test_results.update(data)
        except Exception:
            continue

    # Load existing data.
    table_rows = load_existing_table()
    tested = load_tested_versions()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Merge new results.
    for entry in missing:
        version = entry["version"]
        commit = entry["commit"]
        result = test_results.get(version, {})
        status = result.get("status", "unknown")

        table_rows[version] = {
            "Cursor Version": version,
            "Commit": commit,
            "Date": today,
            "Status": status,
        }
        tested[version] = {
            "commit": commit,
            "date": today,
            "status": status,
        }

    # Write files.
    TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TABLE_PATH.write_text(render_table(table_rows), encoding="utf-8")
    TESTED_PATH.write_text(render_tested_versions(tested), encoding="utf-8")

    print(f"Updated {TABLE_PATH} and {TESTED_PATH}")


if __name__ == "__main__":
    main()
