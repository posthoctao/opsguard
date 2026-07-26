from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.base import DiagnosisAgent
from app.agents.claude import ClaudeAgentUnavailableError
from app.agents.rules import RuleBasedDiagnosisAgent
from app.core.config import Settings
from app.core.enums import IncidentStatus, ToolExecutionStatus
from app.core.state_machine import ensure_transition
from app.db.models import Incident, ToolExecution
from app.db.session import session_scope
from app.runtime.base import RuntimeAdapter
from app.schemas import AlertCreate, DiagnosisDecision, RemediationPlan
from app.services.policy import evaluate_plan, get_max_attempts, sanitize_parameters
from app.services.repository import add_event, get_incident


class IncidentOrchestrator:
    def __init__(
        self,
        settings: Settings,
        runtime: RuntimeAdapter,
        diagnosis_agent: DiagnosisAgent,
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self.diagnosis_agent = diagnosis_agent
        self.fallback_agent = RuleBasedDiagnosisAgent()

    async def process(self, incident_id: str) -> None:
        try:
            with session_scope() as db:
                incident = get_incident(db, incident_id)
                if IncidentStatus(incident.status) != IncidentStatus.OPEN:
                    return
                self._transition(db, incident, IncidentStatus.COLLECTING_EVIDENCE, "正在收集运行时证据。")
                alert = AlertCreate.model_validate(incident.alert_payload)
                existing_evidence = dict(incident.evidence or {})
                db.commit()

            runtime_evidence = await self.runtime.collect_evidence(alert.service_name)
            evidence = self._merge_evidence(
                runtime_evidence=runtime_evidence,
                existing_evidence=existing_evidence,
            )
            with session_scope() as db:
                incident = get_incident(db, incident_id)
                incident.evidence = evidence
                add_event(db, incident_id, "EVIDENCE_COLLECTED", "运行时证据收集完成。", evidence)
                self._transition(db, incident, IncidentStatus.DIAGNOSING, "正在执行故障诊断。")
                db.commit()

            diagnosis = await self._diagnose(alert, evidence)
            plan = self._build_remediation_plan(alert, diagnosis)

            with session_scope() as db:
                incident = get_incident(db, incident_id)
                incident.diagnosis = diagnosis.model_dump(mode="json")
                add_event(
                    db,
                    incident_id,
                    "DIAGNOSIS_COMPLETED",
                    diagnosis.summary,
                    diagnosis.model_dump(mode="json"),
                )
                self._transition(db, incident, IncidentStatus.PLANNING, "正在评估修复建议。")
                incident.remediation_plan = plan.model_dump(mode="json")

                if diagnosis.action_parameters != plan.parameters:
                    add_event(
                        db,
                        incident_id,
                        "ACTION_PARAMETERS_NORMALIZED",
                        "模型建议参数已由后端转换为安全白名单参数。",
                        {
                            "model_parameters": diagnosis.action_parameters,
                            "effective_parameters": plan.parameters,
                        },
                    )

                policy = evaluate_plan(plan)
                add_event(
                    db,
                    incident_id,
                    "POLICY_EVALUATED",
                    policy.reason,
                    policy.model_dump(mode="json"),
                )

                if not policy.allowed:
                    self._transition(
                        db,
                        incident,
                        IncidentStatus.ESCALATED,
                        "当前没有可安全自动执行的修复操作，已升级人工处理。",
                    )
                    db.commit()
                    return

                if policy.approval_required:
                    self._transition(
                        db,
                        incident,
                        IncidentStatus.WAITING_FOR_APPROVAL,
                        "高风险修复操作需要人工审批。",
                    )
                    db.commit()
                    return

                db.commit()

            await self.execute_and_verify(incident_id, approved=False)
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(incident_id, str(exc))

    async def execute_and_verify(self, incident_id: str, approved: bool) -> None:
        with session_scope() as db:
            incident = get_incident(db, incident_id)
            current = IncidentStatus(incident.status)
            if current not in {IncidentStatus.PLANNING, IncidentStatus.WAITING_FOR_APPROVAL}:
                raise ValueError(f"Incident 当前状态不允许执行修复：{current}")
            plan = RemediationPlan.model_validate(incident.remediation_plan)
            policy = evaluate_plan(plan)
            if not policy.allowed:
                raise ValueError(policy.reason)
            if policy.approval_required and not approved:
                raise PermissionError("该动作必须经过人工审批。")

            max_attempts = min(
                get_max_attempts(plan.action_name), self.settings.max_remediation_attempts
            )
            attempts = db.scalar(
                select(func.count(ToolExecution.id)).where(
                    ToolExecution.incident_id == incident_id,
                    ToolExecution.action_name == plan.action_name,
                )
            ) or 0
            if attempts >= max_attempts:
                self._transition(
                    db,
                    incident,
                    IncidentStatus.ESCALATED,
                    "已达到最大修复尝试次数，升级人工处理。",
                )
                db.commit()
                return

            parameters = sanitize_parameters(plan.action_name, plan.parameters)
            self._transition(db, incident, IncidentStatus.REMEDIATING, "正在执行已授权的修复操作。")
            execution = ToolExecution(
                incident_id=incident_id,
                action_name=plan.action_name,
                risk_level=policy.risk_level.value,
                status=ToolExecutionStatus.AUTHORIZED.value,
                request_payload=parameters,
            )
            db.add(execution)
            db.flush()
            execution.status = ToolExecutionStatus.EXECUTING.value
            execution.started_at = datetime.now(timezone.utc)
            add_event(
                db,
                incident_id,
                "TOOL_EXECUTION_STARTED",
                f"正在执行动作 {plan.action_name}。",
                {"execution_id": execution.id, "parameters": parameters},
            )
            db.commit()
            execution_id = execution.id

        started = time.perf_counter()
        try:
            result = await self.runtime.execute_action(plan.action_name, parameters)
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - started) * 1000)
            with session_scope() as db:
                incident = get_incident(db, incident_id)
                execution = db.get(ToolExecution, execution_id)
                assert execution is not None
                execution.status = ToolExecutionStatus.FAILED.value
                execution.error_message = str(exc)
                execution.finished_at = datetime.now(timezone.utc)
                execution.duration_ms = duration_ms
                add_event(db, incident_id, "TOOL_EXECUTION_FAILED", str(exc))
                self._transition(db, incident, IncidentStatus.ESCALATED, "修复操作执行失败。")
                db.commit()
            return

        duration_ms = int((time.perf_counter() - started) * 1000)
        with session_scope() as db:
            incident = get_incident(db, incident_id)
            execution = db.get(ToolExecution, execution_id)
            assert execution is not None
            execution.status = ToolExecutionStatus.SUCCEEDED.value
            execution.result_payload = result
            execution.finished_at = datetime.now(timezone.utc)
            execution.duration_ms = duration_ms
            add_event(
                db,
                incident_id,
                "TOOL_EXECUTION_SUCCEEDED",
                f"动作 {plan.action_name} 执行完成。",
                result,
            )
            self._transition(db, incident, IncidentStatus.VERIFYING, "正在验证服务是否恢复。")
            db.commit()

        verification = await self.runtime.verify(incident.alert_type, incident.service_name)
        with session_scope() as db:
            incident = get_incident(db, incident_id)
            incident.verification = verification.model_dump(mode="json")
            add_event(
                db,
                incident_id,
                "VERIFICATION_COMPLETED",
                verification.message,
                verification.model_dump(mode="json"),
            )
            if verification.success:
                self._transition(db, incident, IncidentStatus.RESOLVED, "Incident 已解决，且恢复验证通过。")
                incident.resolved_at = datetime.now(timezone.utc)
            else:
                self._transition(
                    db,
                    incident,
                    IncidentStatus.ESCALATED,
                    "恢复验证失败，需要人工进一步排查。",
                )
            db.commit()



    @staticmethod
    def _merge_evidence(
        runtime_evidence: dict[str, Any],
        existing_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """合并服务端运行证据和处理前上传的视觉证据。

        运行时证据始终由后端重新采集；仅保留此前写入的 visual_evidence，
        避免旧的运行状态覆盖本次采集结果。
        """
        merged = dict(runtime_evidence)
        visual_evidence = existing_evidence.get("visual_evidence")
        if isinstance(visual_evidence, list) and visual_evidence:
            merged["visual_evidence"] = visual_evidence
        return merged

    def _build_remediation_plan(
        self,
        alert: AlertCreate,
        diagnosis: DiagnosisDecision,
    ) -> RemediationPlan:
        """根据模型建议动作，由后端生成最终可执行参数。

        模型只负责推荐动作，不拥有容器 ID、镜像、版本等运行时目标的决定权。
        所有执行参数均由可信后端上下文和服务端配置生成。
        """

        if diagnosis.recommended_action == "restart_service":
            parameters: dict[str, Any] = {
                "service_name": alert.service_name,
            }
        elif diagnosis.recommended_action == "rollback_deployment":
            parameters = {
                "service_name": alert.service_name,
                "target_version": self.settings.docker_stable_version,
            }
        else:
            parameters = {}

        return RemediationPlan(
            action_name=diagnosis.recommended_action,
            parameters=parameters,
            expected_outcome="服务健康状态和本次故障相关指标恢复正常。",
            verification_checks=[
                "service_running",
                "error_rate_below_2_percent",
                "latency_below_1000_ms",
            ],
        )

    async def _diagnose(
        self, alert: AlertCreate, evidence: dict[str, Any]
    ) -> DiagnosisDecision:
        try:
            return await self.diagnosis_agent.diagnose(alert, evidence)
        except ClaudeAgentUnavailableError:
            if not self.settings.ai_fallback_to_rules:
                raise
            return await self.fallback_agent.diagnose(alert, evidence)

    def _transition(
        self,
        db: Session,
        incident: Incident,
        target: IncidentStatus,
        message: str,
    ) -> None:
        current = IncidentStatus(incident.status)
        ensure_transition(current, target)
        incident.status = target.value
        add_event(
            db,
            incident.id,
            "STATUS_CHANGED",
            message,
            {"from": current.value, "to": target.value},
        )
        db.flush()

    def _mark_failed(self, incident_id: str, error: str) -> None:
        try:
            with session_scope() as db:
                incident = get_incident(db, incident_id)
                current = IncidentStatus(incident.status)
                if current in {
                    IncidentStatus.RESOLVED,
                    IncidentStatus.ESCALATED,
                    IncidentStatus.FAILED,
                }:
                    return
                incident.error_message = error[:2000]
                self._transition(db, incident, IncidentStatus.FAILED, "Incident 处理流程失败。")
                add_event(db, incident_id, "PROCESSING_ERROR", error[:2000])
                db.commit()
        except Exception:
            return