from dataclasses import dataclass
from typing import Any

from app.core.enums import RiskLevel
from app.schemas import PolicyDecision, RemediationPlan


@dataclass(frozen=True)
class ActionPolicy:
    risk_level: RiskLevel
    approval_required: bool
    allowed: bool
    max_attempts: int
    allowed_parameters: frozenset[str]


ACTION_POLICIES: dict[str, ActionPolicy] = {
    "restart_service": ActionPolicy(
        risk_level=RiskLevel.LOW,
        approval_required=False,
        allowed=True,
        max_attempts=1,
        allowed_parameters=frozenset({"service_name"}),
    ),
    "rollback_deployment": ActionPolicy(
        risk_level=RiskLevel.HIGH,
        approval_required=True,
        allowed=True,
        max_attempts=1,
        allowed_parameters=frozenset({"service_name", "target_version"}),
    ),
    "no_safe_action": ActionPolicy(
        risk_level=RiskLevel.PROHIBITED,
        approval_required=True,
        allowed=False,
        max_attempts=0,
        allowed_parameters=frozenset(),
    ),
}


class PolicyViolationError(ValueError):
    pass


def evaluate_plan(plan: RemediationPlan) -> PolicyDecision:
    policy = ACTION_POLICIES.get(plan.action_name)
    if policy is None:
        return PolicyDecision(
            action_name=plan.action_name,
            risk_level=RiskLevel.PROHIBITED,
            approval_required=True,
            allowed=False,
            reason="该动作未注册在服务端白名单中。",
        )

    unexpected = set(plan.parameters) - set(policy.allowed_parameters)
    if unexpected:
        return PolicyDecision(
            action_name=plan.action_name,
            risk_level=RiskLevel.PROHIBITED,
            approval_required=True,
            allowed=False,
            reason=f"检测到未授权的动作参数：{sorted(unexpected)}",
        )

    return PolicyDecision(
        action_name=plan.action_name,
        risk_level=policy.risk_level,
        approval_required=policy.approval_required,
        allowed=policy.allowed,
        reason="动作和参数均符合服务端安全策略。",
    )


def get_max_attempts(action_name: str) -> int:
    policy = ACTION_POLICIES.get(action_name)
    return policy.max_attempts if policy else 0


def sanitize_parameters(action_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    policy = ACTION_POLICIES.get(action_name)
    if policy is None:
        raise PolicyViolationError(f"未知动作：{action_name}")
    unexpected = set(parameters) - set(policy.allowed_parameters)
    if unexpected:
        raise PolicyViolationError(f"检测到未授权参数：{sorted(unexpected)}")
    return {key: parameters[key] for key in policy.allowed_parameters if key in parameters}
