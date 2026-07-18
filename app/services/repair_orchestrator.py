from __future__ import annotations

from datetime import datetime, timezone

from app.core.enums import CodeRepairStatus, IncidentStatus
from app.db.session import session_scope
from app.schemas import CodeRepairWorkerRequest
from app.services.repair_client import RepairWorkerClient
from app.services.repair_repository import add_repair_event, get_repair_job, mark_repair_failed
from app.services.repository import add_event, get_incident


class CodeRepairOrchestrator:
    def __init__(self, worker: RepairWorkerClient) -> None:
        self.worker = worker

    async def run(self, repair_job_id: str) -> None:
        try:
            with session_scope() as db:
                job = get_repair_job(db, repair_job_id)
                if CodeRepairStatus(job.status) != CodeRepairStatus.QUEUED:
                    return
                incident = get_incident(db, job.incident_id)
                if IncidentStatus(incident.status) not in {
                    IncidentStatus.RESOLVED,
                    IncidentStatus.ESCALATED,
                    IncidentStatus.FAILED,
                }:
                    raise ValueError(
                        "只有运行时修复流程进入终态后，才能启动代码修复。"
                    )

                job.status = CodeRepairStatus.RUNNING.value
                add_repair_event(
                    db,
                    job.id,
                    "REPAIR_STARTED",
                    "隔离式代码修复 Worker 已启动。",
                )
                diagnosis = incident.diagnosis or {}
                request = CodeRepairWorkerRequest(
                    job_id=job.id,
                    incident_id=incident.id,
                    source_profile=job.source_profile,
                    issue_summary=str(
                        diagnosis.get("summary")
                        or incident.alert_payload.get("summary")
                        or incident.alert_type
                    ),
                    root_cause=str(diagnosis.get("root_cause") or "未知根因"),
                    evidence=incident.evidence or {},
                    instructions=job.instructions,
                )
                db.commit()

            result = await self.worker.run_repair(request)
            with session_scope() as db:
                job = get_repair_job(db, repair_job_id)
                job.provider = result.provider
                job.summary = result.summary
                job.root_cause = result.root_cause
                job.changed_files = result.changed_files
                job.file_changes = [item.model_dump(mode="json") for item in result.file_changes]
                job.diff_text = result.diff_text
                job.test_command = result.test_command
                job.test_output = result.test_output[-20000:]
                job.tests_passed = result.tests_passed
                job.finished_at = datetime.now(timezone.utc)

                if not result.changed_files:
                    raise ValueError("代码修复 Worker 未产生任何源码变更。")
                if not result.tests_passed:
                    raise ValueError("独立验证测试未通过。")

                job.status = CodeRepairStatus.PATCH_READY.value
                add_repair_event(
                    db,
                    job.id,
                    "PATCH_READY",
                    "已生成通过测试的补丁，等待人工审核。",
                    {
                        "provider": result.provider,
                        "changed_files": result.changed_files,
                        "tests_passed": result.tests_passed,
                        "test_command": result.test_command,
                    },
                )
                add_event(
                    db,
                    job.incident_id,
                    "CODE_REPAIR_PATCH_READY",
                    "已生成通过测试的代码修复补丁，等待审核。",
                    {"repair_job_id": job.id, "changed_files": result.changed_files},
                )
                db.commit()
        except Exception as exc:  # noqa: BLE001
            with session_scope() as db:
                try:
                    job = get_repair_job(db, repair_job_id)
                except KeyError:
                    return
                if CodeRepairStatus(job.status) in {
                    CodeRepairStatus.APPROVED,
                    CodeRepairStatus.REJECTED,
                    CodeRepairStatus.PUBLISHED,
                }:
                    return
                mark_repair_failed(db, job, str(exc))
                add_event(
                    db,
                    job.incident_id,
                    "CODE_REPAIR_FAILED",
                    str(exc)[:2000],
                    {"repair_job_id": job.id},
                )
                db.commit()
