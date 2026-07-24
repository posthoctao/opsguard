from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import IncidentStatus
from app.db.models import Incident, IncidentEvent
from app.schemas import AlertCreate


TERMINAL_STATUSES = {
    IncidentStatus.RESOLVED.value,
    IncidentStatus.ESCALATED.value,
    IncidentStatus.FAILED.value,
}


def compute_fingerprint(alert: AlertCreate) -> str:
    if alert.fingerprint:
        return alert.fingerprint
    canonical = {
        "service_name": alert.service_name,
        "alert_type": alert.alert_type,
        "labels": dict(sorted(alert.labels.items())),
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_recent_open_duplicate(
    db: Session, fingerprint: str, dedupe_window_seconds: int
) -> Incident | None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=dedupe_window_seconds)
    stmt = (
        select(Incident)
        .where(
            Incident.fingerprint == fingerprint,
            Incident.created_at >= cutoff,
            Incident.status.not_in(TERMINAL_STATUSES),
        )
        .order_by(desc(Incident.created_at))
        .limit(1)
    )
    return db.scalar(stmt)


def create_incident(db: Session, alert: AlertCreate, fingerprint: str) -> Incident:
    incident = Incident(
        fingerprint=fingerprint,
        service_name=alert.service_name,
        alert_type=alert.alert_type,
        severity=alert.severity.value,
        status=IncidentStatus.OPEN.value,
        alert_payload=alert.model_dump(mode="json"),
    )
    db.add(incident)
    db.flush()
    add_event(db, incident.id, "ALERT_RECEIVED", alert.summary, alert.model_dump(mode="json"))
    db.commit()
    return get_incident(db, incident.id)


def add_event(
    db: Session,
    incident_id: str,
    event_type: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> IncidentEvent:
    event = IncidentEvent(
        incident_id=incident_id,
        event_type=event_type,
        message=message,
        data=data or {},
    )
    db.add(event)
    db.flush()
    return event


def get_incident(db: Session, incident_id: str) -> Incident:
    stmt = (
        select(Incident)
        .options(selectinload(Incident.events), selectinload(Incident.tool_executions), selectinload(Incident.repair_jobs))
        .where(Incident.id == incident_id)
    )
    incident = db.scalar(stmt)
    if incident is None:
        raise KeyError(f"未找到 Incident：{incident_id}")
    return incident


def list_incidents(db: Session, limit: int = 50) -> list[Incident]:
    stmt = (
        select(Incident)
        .options(selectinload(Incident.events), selectinload(Incident.tool_executions), selectinload(Incident.repair_jobs))
        .order_by(desc(Incident.created_at))
        .limit(limit)
    )
    return list(db.scalars(stmt).unique())
