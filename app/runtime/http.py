from __future__ import annotations

from typing import Any

import httpx

from app.runtime.base import RuntimeAdapter
from app.schemas import VerificationResult


class HttpDemoRuntime(RuntimeAdapter):
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

    async def collect_evidence(self, service_name: str) -> dict[str, Any]:
        state = await self._request("GET", "/internal/state")
        return {
            "service": state,
            "health_check": {
                "ok": bool(state["running"]),
                "status_code": 200 if state["running"] else 503,
            },
            "deployment": {"current_version": state["version"]},
            "metrics": {
                "error_rate": state["error_rate"],
                "latency_ms": state["latency_ms"],
            },
        }

    async def execute_action(self, action_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if action_name == "restart_service":
            return await self._request("POST", "/admin/actions/restart")
        if action_name == "rollback_deployment":
            return await self._request(
                "POST", "/admin/actions/rollback", json={"target_version": parameters.get("target_version", "v1-stable")}
            )
        raise ValueError(f"HTTP Runtime 未实现该动作：{action_name}")

    async def verify(self, alert_type: str, service_name: str) -> VerificationResult:
        state = await self._request("GET", "/internal/state")
        checks = {
            "service_running": bool(state["running"]),
            "error_rate_below_2_percent": float(state["error_rate"]) < 0.02,
            "latency_below_1000_ms": int(state["latency_ms"]) < 1000,
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
        return await self._request("POST", f"/admin/faults/{fault_type}")

    async def reset(self) -> dict[str, Any]:
        return await self._request("POST", "/admin/actions/reset")

    async def get_state(self) -> dict[str, Any]:
        return await self._request("GET", "/internal/state")
