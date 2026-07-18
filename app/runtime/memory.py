from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from app.runtime.base import RuntimeAdapter
from app.schemas import VerificationResult


@dataclass
class _State:
    service_name: str = "demo-api"
    running: bool = True
    version: str = "v1-stable"
    error_rate: float = 0.0
    latency_ms: int = 50
    active_fault: str | None = None


class InMemoryRuntime(RuntimeAdapter):
    """用于本地开发和自动化测试的确定性内存 Runtime。"""

    def __init__(self) -> None:
        self._state = _State()
        self._lock = asyncio.Lock()

    async def collect_evidence(self, service_name: str) -> dict[str, Any]:
        async with self._lock:
            state = asdict(self._state)
        return {
            "service": state,
            "health_check": {
                "ok": state["running"],
                "status_code": 200 if state["running"] else 503,
            },
            "deployment": {"current_version": state["version"]},
            "metrics": {
                "error_rate": state["error_rate"],
                "latency_ms": state["latency_ms"],
            },
        }

    async def execute_action(self, action_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            if action_name == "restart_service":
                self._state.running = True
                self._state.error_rate = 0.0
                self._state.latency_ms = 50
                self._state.active_fault = None
                return {"ok": True, "action": action_name, "state": asdict(self._state)}
            if action_name == "rollback_deployment":
                self._state.running = True
                self._state.version = str(parameters.get("target_version", "v1-stable"))
                self._state.error_rate = 0.0
                self._state.latency_ms = 50
                self._state.active_fault = None
                return {"ok": True, "action": action_name, "state": asdict(self._state)}
            raise ValueError(f"当前 Runtime 未实现该动作：{action_name}")

    async def verify(self, alert_type: str, service_name: str) -> VerificationResult:
        async with self._lock:
            state = asdict(self._state)

        checks = {
            "service_running": state["running"],
            "error_rate_below_2_percent": state["error_rate"] < 0.02,
            "latency_below_1000_ms": state["latency_ms"] < 1000,
        }
        if alert_type == "HighErrorRateAfterDeploy":
            checks["stable_version_restored"] = state["version"] == "v1-stable"
        success = all(checks.values())
        return VerificationResult(
            success=success,
            checks=checks,
            message="运行时状态健康，恢复验证通过。" if success else "一个或多个恢复检查未通过。",
        )

    async def inject_fault(self, fault_type: str) -> dict[str, Any]:
        async with self._lock:
            if fault_type == "service_unavailable":
                self._state.running = False
                self._state.error_rate = 1.0
                self._state.active_fault = fault_type
            elif fault_type == "deploy_regression":
                self._state.running = True
                self._state.version = "v2-buggy"
                self._state.error_rate = 0.35
                self._state.active_fault = fault_type
            elif fault_type == "high_latency":
                self._state.running = True
                self._state.latency_ms = 2500
                self._state.active_fault = fault_type
            else:
                raise ValueError(f"不支持的故障类型：{fault_type}")
            return asdict(self._state)

    async def reset(self) -> dict[str, Any]:
        async with self._lock:
            self._state = _State()
            return asdict(self._state)

    async def get_state(self) -> dict[str, Any]:
        async with self._lock:
            return asdict(self._state)
