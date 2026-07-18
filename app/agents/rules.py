from __future__ import annotations

from typing import Any

from app.agents.base import DiagnosisAgent
from app.schemas import AlertCreate, DiagnosisDecision


class RuleBasedDiagnosisAgent(DiagnosisAgent):
    """用于开发与测试的确定性规则模式，可通过 AI_PROVIDER 切换到 Claude。"""

    async def diagnose(
        self, alert: AlertCreate, evidence: dict[str, Any]
    ) -> DiagnosisDecision:
        service = alert.service_name
        state = evidence.get("service", {})
        metrics = evidence.get("metrics", {})

        if alert.alert_type == "ServiceUnavailable" or not state.get("running", True):
            return DiagnosisDecision(
                summary=f"服务 {service} 当前不可用，健康检查未通过。",
                root_cause="服务进程未运行。",
                confidence=0.95,
                evidence=[
                    f"健康检查结果={evidence.get('health_check')}",
                    f"运行状态={state.get('running')}",
                ],
                recommended_action="restart_service",
                action_parameters={"service_name": service},
            )

        if alert.alert_type == "HighErrorRateAfterDeploy" or (
            float(metrics.get("error_rate", 0)) >= 0.1 and state.get("version") != "v1-stable"
        ):
            return DiagnosisDecision(
                summary=f"服务 {service} 在新版本部署后错误率上升。",
                root_cause="当前部署版本很可能引入了回归问题。",
                confidence=0.91,
                evidence=[
                    f"当前版本={state.get('version')}",
                    f"错误率={metrics.get('error_rate')}",
                ],
                recommended_action="rollback_deployment",
                action_parameters={
                    "service_name": service,
                    "target_version": "v1-stable",
                },
            )

        if alert.alert_type == "HighLatency" or int(metrics.get("latency_ms", 0)) >= 1000:
            return DiagnosisDecision(
                summary=f"服务 {service} 的延迟超过恢复阈值。",
                root_cause="服务当前处于性能降级状态。",
                confidence=0.78,
                evidence=[f"延迟毫秒数={metrics.get('latency_ms')}"],
                recommended_action="restart_service",
                action_parameters={"service_name": service},
            )

        return DiagnosisDecision(
            summary="现有证据不足，无法安全地执行自动修复。",
            root_cause="未知",
            confidence=0.25,
            evidence=[f"告警类型={alert.alert_type}", f"现有证据={evidence}"],
            recommended_action="no_safe_action",
            action_parameters={},
        )
