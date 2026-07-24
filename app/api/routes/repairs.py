from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import CodeRepairStatus, IncidentStatus
from app.db.session import get_db
from app.dependencies import get_github_publisher, get_repair_orchestrator
from app.schemas import (
    CodeRepairApprovalRequest,
    CodeRepairCreate,
    CodeRepairJobRead,
    CodeRepairRejectionRequest,
    PullRequestPublishRequest,
)
from app.services.github import PullRequestPublishError
from app.services.repair_repository import (
    add_repair_event,
    create_repair_job,
    get_repair_job,
    list_repair_jobs,
)
from app.services.repository import add_event, get_incident

router = APIRouter(tags=["代码修复管理"])


async def _run_repair_in_background(repair_job_id: str) -> None:
    await get_repair_orchestrator().run(repair_job_id)


@router.post(
    "/incidents/{incident_id}/repairs",
    response_model=CodeRepairJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="为终态 Incident 创建代码修复任务",
)
def create_repair(
    incident_id: str,
    request: CodeRepairCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> CodeRepairJobRead:
    try:
        incident = get_incident(db, incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if IncidentStatus(incident.status) not in {
        IncidentStatus.RESOLVED,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"必须先让 Incident 进入运行时终态，才能启动代码修复：{incident.status}",
        )

    settings = get_settings()
    if request.source_profile != settings.repair_source_profile:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="该源码模板未被后端配置加入白名单。",
        )

    job = create_repair_job(db, incident, request)
    add_event(
        db,
        incident_id,
        "CODE_REPAIR_REQUESTED",
        f"请求人 {request.requested_by} 已创建代码修复任务。",
        {"repair_job_id": job.id, "source_profile": request.source_profile},
    )
    db.commit()
    background_tasks.add_task(_run_repair_in_background, job.id)
    return CodeRepairJobRead.model_validate(get_repair_job(db, job.id))


@router.get("/repairs", response_model=list[CodeRepairJobRead], summary="查询代码修复任务列表")
def list_repairs(limit: int = 50, db: Session = Depends(get_db)) -> list[CodeRepairJobRead]:
    return [CodeRepairJobRead.model_validate(item) for item in list_repair_jobs(db, limit)]


@router.get("/repairs/{repair_job_id}", response_model=CodeRepairJobRead, summary="查询单个代码修复任务")
def get_repair(repair_job_id: str, db: Session = Depends(get_db)) -> CodeRepairJobRead:
    try:
        return CodeRepairJobRead.model_validate(get_repair_job(db, repair_job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/repairs/{repair_job_id}/approve", response_model=CodeRepairJobRead, summary="批准已通过测试的代码补丁")
def approve_repair(
    repair_job_id: str,
    request: CodeRepairApprovalRequest,
    db: Session = Depends(get_db),
) -> CodeRepairJobRead:
    try:
        job = get_repair_job(db, repair_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if CodeRepairStatus(job.status) != CodeRepairStatus.PATCH_READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"代码修复任务尚未达到可批准状态：{job.status}",
        )
    job.status = CodeRepairStatus.APPROVED.value
    job.approved_by = request.approved_by
    job.approval_note = request.note
    job.approved_at = datetime.now(timezone.utc)
    add_repair_event(
        db,
        job.id,
        "PATCH_APPROVED",
        f"审核人 {request.approved_by} 已批准补丁。",
        request.model_dump(mode="json"),
    )
    add_event(
        db,
        job.incident_id,
        "CODE_REPAIR_APPROVED",
        f"代码修复补丁已由 {request.approved_by} 批准。",
        {"repair_job_id": job.id},
    )
    db.commit()
    return CodeRepairJobRead.model_validate(get_repair_job(db, repair_job_id))


@router.post("/repairs/{repair_job_id}/reject", response_model=CodeRepairJobRead, summary="拒绝代码补丁")
def reject_repair(
    repair_job_id: str,
    request: CodeRepairRejectionRequest,
    db: Session = Depends(get_db),
) -> CodeRepairJobRead:
    try:
        job = get_repair_job(db, repair_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if CodeRepairStatus(job.status) != CodeRepairStatus.PATCH_READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"代码修复任务尚未达到可拒绝状态：{job.status}",
        )
    job.status = CodeRepairStatus.REJECTED.value
    add_repair_event(
        db,
        job.id,
        "PATCH_REJECTED",
        f"审核人 {request.rejected_by} 已拒绝补丁：{request.reason}",
        request.model_dump(mode="json"),
    )
    add_event(
        db,
        job.incident_id,
        "CODE_REPAIR_REJECTED",
        f"代码修复补丁已由 {request.rejected_by} 拒绝。",
        {"repair_job_id": job.id, "reason": request.reason},
    )
    db.commit()
    return CodeRepairJobRead.model_validate(get_repair_job(db, repair_job_id))


@router.post("/repairs/{repair_job_id}/publish-pr", response_model=CodeRepairJobRead, summary="把已批准补丁发布为 GitHub PR")
async def publish_pull_request(
    repair_job_id: str,
    request: PullRequestPublishRequest,
    db: Session = Depends(get_db),
) -> CodeRepairJobRead:
    try:
        job = get_repair_job(db, repair_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if CodeRepairStatus(job.status) != CodeRepairStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"发布 PR 前必须先批准代码修复任务：{job.status}",
        )

    try:
        result = await get_github_publisher().publish(job, title=request.title, body=request.body)
    except PullRequestPublishError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    job.status = CodeRepairStatus.PUBLISHED.value
    job.branch_name = result.branch_name
    job.pull_request_url = result.url
    job.pull_request_number = result.number
    add_repair_event(
        db,
        job.id,
        "PULL_REQUEST_PUBLISHED",
        f"发布人 {request.published_by} 已创建 Pull Request #{result.number}。",
        {"url": result.url, "branch_name": result.branch_name},
    )
    add_event(
        db,
        job.incident_id,
        "CODE_REPAIR_PR_PUBLISHED",
        f"代码修复 Pull Request #{result.number} 已发布。",
        {"repair_job_id": job.id, "url": result.url},
    )
    db.commit()
    return CodeRepairJobRead.model_validate(get_repair_job(db, repair_job_id))
