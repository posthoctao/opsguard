from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CodeRepairStatus, IncidentStatus, Severity, ToolExecutionStatus
from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_fingerprint_created", "fingerprint", "created_at"),
        Index("ix_incidents_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default=Severity.WARNING.value)
    status: Mapped[str] = mapped_column(String(40), default=IncidentStatus.OPEN.value)

    alert_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    diagnosis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    remediation_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list[IncidentEvent]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="IncidentEvent.id"
    )
    tool_executions: Mapped[list[ToolExecution]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="ToolExecution.id"
    )
    repair_jobs: Mapped[list[CodeRepairJob]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="CodeRepairJob.created_at"
    )


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incident: Mapped[Incident] = relationship(back_populates="events")


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_name: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=ToolExecutionStatus.AUTHORIZED.value
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="tool_executions")


class CodeRepairJob(Base):
    __tablename__ = "code_repair_jobs"
    __table_args__ = (
        Index("ix_code_repair_jobs_incident", "incident_id"),
        Index("ix_code_repair_jobs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default=CodeRepairStatus.QUEUED.value)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_profile: Mapped[str] = mapped_column(String(120), nullable=False)

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_files: Mapped[list[str]] = mapped_column(JSON, default=list)
    file_changes: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    diff_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_command: Mapped[list[str]] = mapped_column(JSON, default=list)
    test_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    tests_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="repair_jobs")
    events: Mapped[list[CodeRepairEvent]] = relationship(
        back_populates="repair_job",
        cascade="all, delete-orphan",
        order_by="CodeRepairEvent.id",
    )


class CodeRepairEvent(Base):
    __tablename__ = "code_repair_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repair_job_id: Mapped[str] = mapped_column(
        ForeignKey("code_repair_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    repair_job: Mapped[CodeRepairJob] = relationship(back_populates="events")
