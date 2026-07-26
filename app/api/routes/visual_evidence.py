from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.agents.vision import ClaudeVisionUnavailableError
from app.core.config import get_settings
from app.core.enums import IncidentStatus
from app.db.session import get_db
from app.dependencies import get_vision_agent
from app.schemas import VisualEvidenceRecord
from app.services.repository import add_event, get_incident


router = APIRouter(prefix="/incidents", tags=["多模态视觉证据"])

ALLOWED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
}


def _signature_matches(content: bytes, mime_type: str) -> bool:
    if mime_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime_type == "image/webp":
        return (
            len(content) >= 12
            and content.startswith(b"RIFF")
            and content[8:12] == b"WEBP"
        )
    return False


@router.post(
    "/{incident_id}/visual-evidence",
    response_model=VisualEvidenceRecord,
    status_code=status.HTTP_201_CREATED,
    summary="上传并分析故障截图",
)
async def add_visual_evidence(
    incident_id: str,
    file: UploadFile = File(..., description="PNG、JPEG 或 WEBP 故障截图"),
    db: Session = Depends(get_db),
) -> VisualEvidenceRecord:
    try:
        incident = get_incident(db, incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if IncidentStatus(incident.status) != IncidentStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "只能在 Incident 进入处理流程前上传视觉证据。"
                f"当前状态：{incident.status}"
            ),
        )

    settings = get_settings()
    mime_type = (file.content_type or "").lower()
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 image/png、image/jpeg 和 image/webp。",
        )

    try:
        content = await file.read(settings.vision_max_image_bytes + 1)
    finally:
        await file.close()

    if not content:
        raise HTTPException(status_code=400, detail="上传的图片为空。")
    if len(content) > settings.vision_max_image_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "图片超过大小限制："
                f"{settings.vision_max_image_bytes // (1024 * 1024)} MB。"
            ),
        )
    if not _signature_matches(content, mime_type):
        raise HTTPException(
            status_code=400,
            detail="图片内容与声明的 MIME 类型不匹配。",
        )

    context = {
        "incident_id": incident.id,
        "service_name": incident.service_name,
        "alert_type": incident.alert_type,
        "severity": incident.severity,
        "alert": incident.alert_payload,
    }
    try:
        analysis = await get_vision_agent().analyze(
            image_bytes=content,
            media_type=mime_type,
            incident_context=context,
        )
    except ClaudeVisionUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    record = VisualEvidenceRecord(
        id=str(uuid4()),
        filename=(file.filename or "uploaded-image")[:255],
        mime_type=mime_type,
        sha256=hashlib.sha256(content).hexdigest(),
        analysis=analysis,
        created_at=datetime.now(timezone.utc),
    )

    existing_evidence = dict(incident.evidence or {})
    visual_items = list(existing_evidence.get("visual_evidence") or [])
    visual_items.append(record.model_dump(mode="json"))
    incident.evidence = {
        **existing_evidence,
        "visual_evidence": visual_items,
    }
    add_event(
        db,
        incident_id,
        "VISUAL_EVIDENCE_ANALYZED",
        f"已分析视觉证据：{record.filename}",
        {
            "visual_evidence_id": record.id,
            "filename": record.filename,
            "mime_type": record.mime_type,
            "sha256": record.sha256,
            "analysis": record.analysis.model_dump(mode="json"),
        },
    )
    db.commit()
    return record
