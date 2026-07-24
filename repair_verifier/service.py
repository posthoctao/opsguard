from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.schemas import RepairVerificationResult

_TEST_COMMAND = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


class RepairVerifierService:
    def __init__(self, workspace_root: Path, timeout_seconds: int = 60) -> None:
        self.workspace_root = workspace_root.resolve()
        self.timeout_seconds = timeout_seconds

    def verify(self, job_id: str) -> RepairVerificationResult:
        safe_job_id = "".join(char for char in job_id if char.isalnum() or char in {"-", "_"})
        if not safe_job_id or safe_job_id != job_id:
            raise ValueError("代码修复任务 ID 无效。")
        workspace = (self.workspace_root / safe_job_id).resolve()
        workspace.relative_to(self.workspace_root)
        if not workspace.is_dir():
            raise FileNotFoundError(f"代码修复工作区不存在：{job_id}")

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(workspace),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "HOME": "/tmp",
        }
        try:
            completed = subprocess.run(
                _TEST_COMMAND,
                cwd=workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("独立代码修复验证超时。") from exc

        return RepairVerificationResult(
            tests_passed=completed.returncode == 0,
            return_code=completed.returncode,
            test_command=list(_TEST_COMMAND),
            test_output=(completed.stdout + completed.stderr)[-10000:],
        )
