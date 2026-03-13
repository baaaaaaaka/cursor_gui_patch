from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "cursor-compat.yml"


def test_compat_workflow_uploads_only_json_results():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'path: results/hot-patch-guard.json' in workflow
    assert 'path: results/${{ matrix.target }}.json' in workflow
    assert '--artifacts-dir "compat-work/${{ matrix.target }}"' in workflow
    assert '\n          path: results/\n' not in workflow


def test_compat_workflow_covers_all_gui_platforms():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'target: linux-gui' in workflow
    assert 'target: macos-gui' in workflow
    assert 'target: windows-gui' in workflow
    assert 'target: hot-patch-guard' not in workflow
    assert 'name: Hot patch guard' in workflow
