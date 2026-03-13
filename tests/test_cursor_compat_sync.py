from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cursor_compat_sync.py"
SPEC = importlib.util.spec_from_file_location("cursor_compat_sync", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
cursor_compat_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cursor_compat_sync)


def test_load_result_matrix_supports_target_wrapper(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "linux-gui.json").write_text(
        json.dumps(
            {
                "target": "linux-gui",
                "results": {
                    "2.6.19": {"commit": "abc123", "status": "pass"},
                },
            }
        ),
        encoding="utf-8",
    )

    matrix = cursor_compat_sync.load_result_matrix(results_dir)

    assert matrix["linux-gui"]["2.6.19"]["status"] == "pass"


def test_overall_status_requires_full_matrix(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    version = "2.6.19"
    for target in ("linux-server", "linux-gui", "macos-gui", "hot-patch-guard"):
        (results_dir / f"{target}.json").write_text(
            json.dumps(
                {
                    "target": target,
                    "results": {
                        version: {"commit": "abc123", "status": "pass"},
                    },
                }
            ),
            encoding="utf-8",
        )

    matrix = cursor_compat_sync.load_result_matrix(results_dir)

    assert cursor_compat_sync._overall_status(matrix, version) == "fail"

    (results_dir / "windows-gui.json").write_text(
        json.dumps(
            {
                "target": "windows-gui",
                "results": {
                    version: {"commit": "abc123", "status": "pass"},
                },
            }
        ),
        encoding="utf-8",
    )

    matrix = cursor_compat_sync.load_result_matrix(results_dir)
    assert cursor_compat_sync._overall_status(matrix, version) == "pass"
