from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml"


def test_tests_workflow_runs_windows_discovery_integration_step() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Run Windows discovery integration tests" in workflow
    assert "if: runner.os == 'Windows'" in workflow
    assert "tests/test_windows_discovery_integration.py -v" in workflow
