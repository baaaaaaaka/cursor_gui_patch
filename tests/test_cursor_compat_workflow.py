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


def test_compat_workflow_supports_backtesting_old_code_refs():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "code_ref:" in workflow
    assert "force_run:" in workflow
    assert "record_results:" in workflow
    assert "force_version:" in workflow
    assert "force_windows_gui_url:" in workflow
    assert 'git checkout "${{ needs.detect.outputs.code_ref }}" -- cursor_gui_patch' in workflow
    assert "code_ref=${code_ref}" not in workflow


def test_compat_workflow_skips_record_updates_for_manual_backtests():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "record_results=${{ steps.detect.outputs.record_results }}" not in workflow
    assert "needs.detect.outputs.record_results == 'true'" in workflow
    assert "manual_backtest = event_name == \"workflow_dispatch\"" in workflow
