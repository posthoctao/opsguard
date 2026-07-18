from __future__ import annotations

import difflib
import shutil
from pathlib import Path

from app.schemas import (
    CodeRepairFileChange,
    CodeRepairWorkerRequest,
    CodeRepairWorkerResult,
)
from repair_worker.agents import CodeRepairAgent, build_code_repair_agent
from repair_worker.config import RepairWorkerSettings
from repair_worker.verifier import HttpRepairVerifier, RepairVerifier

_IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache", ".ruff_cache"}
_ALLOWED_CHANGED_PREFIXES = ("sample_service/",)


class RepairWorkerService:
    def __init__(
        self,
        settings: RepairWorkerSettings,
        agent: CodeRepairAgent | None = None,
        verifier: RepairVerifier | None = None,
    ) -> None:
        self.settings = settings
        self.agent = agent or build_code_repair_agent(settings)
        self.verifier = verifier or HttpRepairVerifier(
            base_url=settings.repair_verifier_url,
            timeout_seconds=settings.repair_test_timeout_seconds + 30,
        )
        self.source_profiles = {
            "demo-buffer-bug": self.settings.repair_source_root / "demo-buffer-bug"
        }

    async def run(self, request: CodeRepairWorkerRequest) -> CodeRepairWorkerResult:
        source = self.source_profiles.get(request.source_profile)
        if source is None:
            raise ValueError("未知源码模板，或该模板未加入白名单。")
        source = source.resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"代码修复源码模板不存在：{source}")

        workspace = self._prepare_workspace(source, request.job_id)
        baseline = await self.verifier.verify(request.job_id)
        if baseline.tests_passed:
            raise ValueError("当前源码模板的基线回归测试已经通过，无法验证修复前后的差异。")

        report = await self.agent.repair(request, workspace)
        self._assert_protected_files_unchanged(source, workspace)
        changes = self._collect_changes(source, workspace)
        if not changes:
            raise ValueError("代码修复 Agent 未产生任何源码变更。")

        final = await self.verifier.verify(request.job_id)
        diff_text = self._build_diff(source, workspace, [item.path for item in changes])
        combined_output = (
            "=== 基线测试（预期失败）===\n"
            f"{baseline.test_output}\n"
            "=== 修复后测试 ===\n"
            f"{final.test_output}"
        )[-20000:]

        return CodeRepairWorkerResult(
            provider=self.settings.repair_agent_provider,
            summary=report.summary,
            root_cause=report.root_cause,
            changed_files=[item.path for item in changes],
            file_changes=changes,
            diff_text=diff_text,
            tests_passed=final.tests_passed,
            test_command=final.test_command,
            test_output=combined_output,
            agent_report=report,
        )

    def _prepare_workspace(self, source: Path, job_id: str) -> Path:
        safe_job_id = "".join(char for char in job_id if char.isalnum() or char in {"-", "_"})
        if not safe_job_id or safe_job_id != job_id:
            raise ValueError("代码修复任务 ID 无效。")
        root = self.settings.repair_workspace_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        workspace = (root / safe_job_id).resolve()
        workspace.relative_to(root)
        if workspace.exists():
            shutil.rmtree(workspace)
        shutil.copytree(source, workspace, symlinks=False)
        return workspace

    def _assert_protected_files_unchanged(self, source: Path, workspace: Path) -> None:
        for relative in self._all_files(source):
            if relative.startswith("tests/") or relative in {"pyproject.toml", "requirements.txt"}:
                original = (source / relative).read_bytes()
                candidate_path = workspace / relative
                if not candidate_path.exists() or candidate_path.read_bytes() != original:
                    raise ValueError(f"代码修复 Agent 修改了受保护文件：{relative}")

    def _collect_changes(self, source: Path, workspace: Path) -> list[CodeRepairFileChange]:
        relative_paths = sorted(set(self._all_files(source)) | set(self._all_files(workspace)))
        changes: list[CodeRepairFileChange] = []
        for relative in relative_paths:
            original_path = source / relative
            updated_path = workspace / relative
            original = original_path.read_bytes() if original_path.exists() else None
            updated = updated_path.read_bytes() if updated_path.exists() else None
            if original == updated:
                continue
            if not relative.startswith(_ALLOWED_CHANGED_PREFIXES):
                raise ValueError(f"代码修复修改了非白名单路径：{relative}")
            if updated is None:
                raise ValueError(f"代码修复删除了白名单源码文件：{relative}")
            try:
                content = updated.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"不允许修改或引入二进制文件：{relative}") from exc
            changes.append(CodeRepairFileChange(path=relative, content=content))
        return changes

    def _build_diff(self, source: Path, workspace: Path, changed_files: list[str]) -> str:
        output: list[str] = []
        for relative in changed_files:
            before_path = source / relative
            after_path = workspace / relative
            before = before_path.read_text(encoding="utf-8").splitlines(keepends=True)
            after = after_path.read_text(encoding="utf-8").splitlines(keepends=True)
            output.extend(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=f"a/{relative}",
                    tofile=f"b/{relative}",
                )
            )
        return "".join(output)

    def _all_files(self, root: Path) -> list[str]:
        files: list[str] = []
        for path in root.rglob("*"):
            if not path.is_file() or any(part in _IGNORED_PARTS for part in path.parts):
                continue
            files.append(path.relative_to(root).as_posix())
        return files
