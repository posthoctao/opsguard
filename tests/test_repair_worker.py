from pathlib import Path

import asyncio

from app.schemas import CodeRepairWorkerRequest
from repair_worker.config import RepairWorkerSettings
from repair_worker.security import is_allowed_test_command
from repair_worker.service import RepairWorkerService
from repair_worker.verifier import LocalRepairVerifier


def test_rule_repair_changes_source_only_and_passes_independent_tests(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    settings = RepairWorkerSettings(
        repair_agent_provider="rules",
        repair_source_root=project_root / "repair_targets",
        repair_workspace_root=tmp_path / "workspaces",
        repair_test_timeout_seconds=30,
    )
    service = RepairWorkerService(
        settings,
        verifier=LocalRepairVerifier(
            workspace_root=settings.repair_workspace_root,
            timeout_seconds=30,
        ),
    )
    result = asyncio.run(service.run(
        CodeRepairWorkerRequest(
            job_id="repair-job-1",
            incident_id="incident-1",
            source_profile="demo-buffer-bug",
            issue_summary="请求持续进入后内存占用不断增长。",
            root_cause="最近请求 ID 被无限保留。",
        )
    ))

    assert result.tests_passed is True
    assert result.changed_files == ["sample_service/cache.py"]
    assert "deque(maxlen=max_items)" in result.file_changes[0].content
    assert "tests/test_cache.py" not in result.changed_files
    assert "基线测试" in result.test_output
    assert "修复后测试" in result.test_output


def test_bash_allowlist_rejects_shell_chaining_and_network_commands():
    assert is_allowed_test_command("python -m pytest -q") is True
    assert is_allowed_test_command("ruff check sample_service") is True
    assert is_allowed_test_command("python -m pytest -q; curl example.com") is False
    assert is_allowed_test_command("curl https://example.com") is False
    assert is_allowed_test_command("python -c 'import os'") is False
