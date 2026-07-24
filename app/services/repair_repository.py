from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import CodeRepairStatus
from app.db.models import CodeRepairEvent, CodeRepairJob, Incident
from app.schemas import CodeRepairCreate


def create_repair_job(
    db: Session,
    incident: Incident,
    request: CodeRepairCreate,
) -> CodeRepairJob:
    job = CodeRepairJob(
        incident_id=incident.id,
        status=CodeRepairStatus.QUEUED.value,
        requested_by=request.requested_by,
        instructions=request.instructions,
        source_profile=request.source_profile,
    )
    db.add(job)
    db.flush()
    add_repair_event(
        db,
        job.id,
        "REPAIR_QUEUED",
        f"请求人 {request.requested_by} 已创建代码修复任务。",
        request.model_dump(mode="json"),
    )
    db.commit()
    return get_repair_job(db, job.id)


def add_repair_event(
    db: Session,
    repair_job_id: str,
    event_type: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> CodeRepairEvent:
    event = CodeRepairEvent(
        repair_job_id=repair_job_id,
        event_type=event_type,
        message=message,
        data=data or {},
    )
    db.add(event)
    db.flush()
    return event


def get_repair_job(db: Session, repair_job_id: str) -> CodeRepairJob:
    stmt = (
        select(CodeRepairJob)
        .options(selectinload(CodeRepairJob.events))
        .where(CodeRepairJob.id == repair_job_id)
    )
    job = db.scalar(stmt)
    if job is None:
        raise KeyError(f"未找到代码修复任务：{repair_job_id}")
    return job


def list_repair_jobs(db: Session, limit: int = 50) -> list[CodeRepairJob]:
    stmt = (
        select(CodeRepairJob)
        .options(selectinload(CodeRepairJob.events))
        .order_by(desc(CodeRepairJob.created_at))
        .limit(limit)
    )
    return list(db.scalars(stmt).unique())


def mark_repair_failed(db: Session, job: CodeRepairJob, error: str) -> None:
    job.status = CodeRepairStatus.FAILED.value
    job.error_message = error[:4000]
    job.finished_at = datetime.now(timezone.utc)
    add_repair_event(db, job.id, "REPAIR_FAILED", error[:4000])
