from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.enums import IncidentStatus
from app.db.session import get_db
from app.dependencies import get_orchestrator
from app.schemas import ApprovalRequest, IncidentRead, RejectionRequest
from app.services.repository import add_event, get_incident, list_incidents

router = APIRouter(prefix="/incidents", tags=["故障事件管理"])


@router.get("", response_model=list[IncidentRead], summary="查询 Incident 列表")
def list_all(limit: int = 50, db: Session = Depends(get_db)) -> list[IncidentRead]:
    return [IncidentRead.model_validate(item) for item in list_incidents(db, limit)]


@router.get("/{incident_id}", response_model=IncidentRead, summary="查询单个 Incident 详情")
def get_one(incident_id: str, db: Session = Depends(get_db)) -> IncidentRead:
    try:
        return IncidentRead.model_validate(get_incident(db, incident_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{incident_id}/process", response_model=IncidentRead, summary="立即处理指定 Incident")
async def process_now(incident_id: str, db: Session = Depends(get_db)) -> IncidentRead:
    try:
        get_incident(db, incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await get_orchestrator().process(incident_id)
    db.expire_all()
    return IncidentRead.model_validate(get_incident(db, incident_id))


@router.post("/{incident_id}/approve", response_model=IncidentRead, summary="批准高风险运行时修复")
async def approve(
    incident_id: str,
    request: ApprovalRequest,
    db: Session = Depends(get_db),
) -> IncidentRead:
    try:
        incident = get_incident(db, incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if IncidentStatus(incident.status) != IncidentStatus.WAITING_FOR_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"当前 Incident 不处于等待审批状态：{incident.status}",
        )
    add_event(
        db,
        incident_id,
        "APPROVAL_GRANTED",
        f"审批人 {request.approved_by} 已批准该运行时修复。",
        request.model_dump(mode="json"),
    )
    db.commit()
    await get_orchestrator().execute_and_verify(incident_id, approved=True)
    db.expire_all()
    return IncidentRead.model_validate(get_incident(db, incident_id))


@router.post("/{incident_id}/reject", response_model=IncidentRead, summary="拒绝高风险运行时修复")
def reject(
    incident_id: str,
    request: RejectionRequest,
    db: Session = Depends(get_db),
) -> IncidentRead:
    try:
        incident = get_incident(db, incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if IncidentStatus(incident.status) != IncidentStatus.WAITING_FOR_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"当前 Incident 不处于等待审批状态：{incident.status}",
        )
    incident.status = IncidentStatus.ESCALATED.value
    add_event(
        db,
        incident_id,
        "APPROVAL_REJECTED",
        f"审批人 {request.rejected_by} 已拒绝该运行时修复：{request.reason}",
        request.model_dump(mode="json"),
    )
    db.commit()
    return IncidentRead.model_validate(get_incident(db, incident_id))
