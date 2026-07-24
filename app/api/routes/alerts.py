from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies import get_orchestrator
from app.schemas import AlertAccepted, AlertCreate, IncidentRead
from app.services.repository import (
    add_event,
    compute_fingerprint,
    create_incident,
    find_recent_open_duplicate,
    get_incident,
)

router = APIRouter(prefix="/alerts", tags=["告警接入"])


async def _process_in_background(incident_id: str) -> None:
    await get_orchestrator().process(incident_id)


@router.post("", response_model=AlertAccepted, status_code=status.HTTP_202_ACCEPTED, summary="接收告警并创建 Incident")
def receive_alert(
    alert: AlertCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AlertAccepted:
    settings = get_settings()
    fingerprint = compute_fingerprint(alert)
    duplicate = find_recent_open_duplicate(db, fingerprint, settings.dedupe_window_seconds)
    if duplicate is not None:
        add_event(
            db,
            duplicate.id,
            "DUPLICATE_ALERT_RECEIVED",
            "检测到重复告警，已根据指纹和去重时间窗口抑制重复处理。",
            alert.model_dump(mode="json"),
        )
        db.commit()
        duplicate = get_incident(db, duplicate.id)
        return AlertAccepted(
            incident=IncidentRead.model_validate(duplicate), deduplicated=True
        )

    incident = create_incident(db, alert, fingerprint)
    if settings.auto_process_alerts:
        background_tasks.add_task(_process_in_background, incident.id)
    return AlertAccepted(
        incident=IncidentRead.model_validate(incident), deduplicated=False
    )
