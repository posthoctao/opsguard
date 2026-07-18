from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.runtime.base import RuntimeAdapter
from app.schemas import VerificationResult

try:
    import docker
    from docker.errors import DockerException, NotFound
except ImportError:  # 在可选依赖尚未安装时，仍允许只运行内存模式测试。
    docker = None  # type: ignore[assignment]

    class DockerException(Exception):
        pass

    class NotFound(DockerException):
        pass


class DockerRuntimeConfigurationError(RuntimeError):
    pass


class DockerRuntime(RuntimeAdapter):
    """仅操作一个明确加入白名单的 Docker 演示容器。

    该适配器不接受模型提供的容器名、镜像名、网络或端口；这些目标值
    只能来自可信的服务端配置。
    """

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        if client is not None:
            self.client = client
        else:
            if docker is None:
                raise DockerRuntimeConfigurationError(
                    "未安装 Docker SDK，请运行 `pip install -r requirements.txt`。"
                )
            try:
                self.client = docker.from_env()
                self.client.ping()
            except DockerException as exc:
                raise DockerRuntimeConfigurationError(
                    "已选择 Docker Runtime，但无法连接 Docker Daemon。"
                ) from exc

    async def collect_evidence(self, service_name: str) -> dict[str, Any]:
        self._validate_service_name(service_name)
        container = await asyncio.to_thread(self._inspect_managed_container)
        http_state = await self._read_http_state()

        running = bool(container["running"])
        version = str(
            (http_state or {}).get("version")
            or container.get("app_version")
            or "unknown"
        )
        error_rate = float((http_state or {}).get("error_rate", 1.0 if not running else 0.0))
        latency_ms = int((http_state or {}).get("latency_ms", 0))
        active_fault = (http_state or {}).get("active_fault") or container.get("startup_fault")
        if active_fault == "none":
            active_fault = None
        if not running and active_fault is None:
            active_fault = "service_unavailable"

        service_state = {
            "service_name": service_name,
            "running": running,
            "version": version,
            "error_rate": error_rate,
            "latency_ms": latency_ms,
            "active_fault": active_fault,
        }
        health_status = container.get("health_status")
        health_ok = running and health_status not in {"unhealthy"}
        if http_state is not None:
            health_ok = health_ok and bool(http_state.get("running", True))

        return {
            "service": service_state,
            "health_check": {
                "ok": health_ok,
                "status_code": 200 if health_ok else 503,
                "container_health": health_status,
            },
            "deployment": {
                "current_version": version,
                "image": container.get("image"),
                "container_id": container.get("container_id"),
            },
            "metrics": {
                "error_rate": error_rate,
                "latency_ms": latency_ms,
            },
            "container": container,
            "logs_tail": container.get("logs_tail", ""),
        }

    async def execute_action(self, action_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        self._validate_service_name(str(parameters.get("service_name", "")))

        if action_name == "restart_service":
            container = await asyncio.to_thread(self._get_managed_container)
            await asyncio.to_thread(container.restart, timeout=10)
            state = await self._wait_for_service()
            return {
                "ok": True,
                "action": action_name,
                "container_name": self.settings.docker_container_name,
                "state": state,
            }

        if action_name == "rollback_deployment":
            target_version = str(parameters.get("target_version", ""))
            if target_version != self.settings.docker_stable_version:
                raise ValueError(
                    f"Docker 回滚仅允许目标版本 {self.settings.docker_stable_version!r}。"
                )
            await asyncio.to_thread(
                self._recreate_managed_container,
                target_version,
                "none",
            )
            state = await self._wait_for_service()
            return {
                "ok": True,
                "action": action_name,
                "container_name": self.settings.docker_container_name,
                "target_version": target_version,
                "state": state,
            }

        raise ValueError(f"Docker Runtime 未实现该动作：{action_name}")

    async def verify(self, alert_type: str, service_name: str) -> VerificationResult:
        self._validate_service_name(service_name)
        try:
            await self._wait_for_service()
        except TimeoutError:
            pass

        evidence = await self.collect_evidence(service_name)
        state = evidence["service"]
        container = evidence["container"]
        checks: dict[str, Any] = {
            "service_running": bool(state["running"]),
            "container_not_unhealthy": container.get("health_status") != "unhealthy",
            "error_rate_below_2_percent": float(state["error_rate"]) < 0.02,
            "latency_below_1000_ms": int(state["latency_ms"]) < 1000,
        }
        if alert_type == "HighErrorRateAfterDeploy":
            checks["stable_version_restored"] = (
                state["version"] == self.settings.docker_stable_version
            )
        success = all(bool(value) for value in checks.values())
        return VerificationResult(
            success=success,
            checks=checks,
            message=(
                "Docker 容器和应用服务健康检查均已通过。"
                if success
                else "一个或多个 Docker 恢复检查未通过。"
            ),
        )

    async def inject_fault(self, fault_type: str) -> dict[str, Any]:
        if fault_type == "service_unavailable":
            container = await asyncio.to_thread(self._get_managed_container)
            await asyncio.to_thread(container.stop, timeout=10)
            return await self.get_state()

        if fault_type == "deploy_regression":
            await asyncio.to_thread(
                self._recreate_managed_container,
                self.settings.docker_buggy_version,
                "deploy_regression",
            )
            await self._wait_for_service()
            return await self.get_state()

        if fault_type == "high_latency":
            await self._request_demo("POST", "/admin/faults/high_latency")
            return await self.get_state()

        raise ValueError(f"不支持的故障类型：{fault_type}")

    async def reset(self) -> dict[str, Any]:
        """将演示服务恢复到稳定、无故障状态。

        当前已经是稳定版本时，不删除并重建容器，避免重复绑定宿主机端口。
        只有当前运行的是错误版本时，才重新创建稳定版本容器。
        """
        container_state = await asyncio.to_thread(self._inspect_managed_container)
        current_version = str(
            container_state.get("app_version")
            or self.settings.docker_stable_version
        )

        if current_version != self.settings.docker_stable_version:
            await asyncio.to_thread(
                self._recreate_managed_container,
                self.settings.docker_stable_version,
                "none",
            )
            await self._wait_for_service()
            return await self.get_state()

        if not bool(container_state.get("running")):
            container = await asyncio.to_thread(self._get_managed_container)
            await asyncio.to_thread(container.start)

        await self._wait_for_service()
        await self._request_demo("POST", "/admin/actions/reset")
        return await self.get_state()

    async def get_state(self) -> dict[str, Any]:
        container = await asyncio.to_thread(self._inspect_managed_container)
        http_state = await self._read_http_state()
        running = bool(container["running"])
        return {
            "service_name": "demo-api",
            "running": running,
            "version": str(
                (http_state or {}).get("version")
                or container.get("app_version")
                or "unknown"
            ),
            "error_rate": float((http_state or {}).get("error_rate", 1.0 if not running else 0.0)),
            "latency_ms": int((http_state or {}).get("latency_ms", 0)),
            "active_fault": (
                (http_state or {}).get("active_fault")
                or self._normalize_fault(container.get("startup_fault"))
                or ("service_unavailable" if not running else None)
            ),
        }

    def _validate_service_name(self, service_name: str) -> None:
        if service_name != "demo-api":
            raise ValueError("Docker Runtime 仅允许操作白名单服务 'demo-api'。")

    def _get_managed_container(self) -> Any:
        try:
            container = self.client.containers.get(self.settings.docker_container_name)
        except NotFound as exc:
            raise DockerRuntimeConfigurationError(
                f"未找到受管容器 {self.settings.docker_container_name!r}。"
            ) from exc
        container.reload()
        labels = dict(container.attrs.get("Config", {}).get("Labels") or {})
        if labels.get(self.settings.docker_managed_label_key) != self.settings.docker_managed_label_value:
            raise PermissionError(
                "目标容器缺少受管标签，已拒绝 Docker 操作。"
            )
        return container

    def _inspect_managed_container(self) -> dict[str, Any]:
        container = self._get_managed_container()
        attrs = container.attrs
        state = attrs.get("State", {})
        config = attrs.get("Config", {})
        env = self._env_to_dict(config.get("Env") or [])
        health = state.get("Health") or {}
        logs = container.logs(tail=self.settings.docker_logs_tail).decode(
            "utf-8", errors="replace"
        )
        return {
            "container_id": str(attrs.get("Id", ""))[:12],
            "container_name": self.settings.docker_container_name,
            "status": state.get("Status", getattr(container, "status", "unknown")),
            "running": bool(state.get("Running", False)),
            "exit_code": state.get("ExitCode"),
            "restart_count": attrs.get("RestartCount", 0),
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            "health_status": health.get("Status", "not_configured"),
            "image": config.get("Image") or self.settings.docker_demo_image,
            "app_version": env.get("APP_VERSION", self.settings.docker_stable_version),
            "startup_fault": env.get("STARTUP_FAULT", "none"),
            "logs_tail": logs[-12000:],
        }

    def _recreate_managed_container(self, version: str, startup_fault: str) -> None:
        if version not in {
            self.settings.docker_stable_version,
            self.settings.docker_buggy_version,
        }:
            raise ValueError(f"版本 {version!r} 未加入演示 Runtime 白名单。")
        if startup_fault not in {"none", "deploy_regression"}:
            raise ValueError(f"启动故障 {startup_fault!r} 未加入白名单。")

        existing = self._get_managed_container()
        inherited_labels = dict(existing.attrs.get("Config", {}).get("Labels") or {})
        inherited_labels[self.settings.docker_managed_label_key] = (
            self.settings.docker_managed_label_value
        )
        image = existing.attrs.get("Config", {}).get("Image") or self.settings.docker_demo_image
        existing.remove(force=True)

        last_error: DockerException | None = None
        for attempt in range(3):
            try:
                self.client.containers.run(
                    image=image,
                    name=self.settings.docker_container_name,
                    detach=True,
                    environment={
                        "APP_VERSION": version,
                        "STARTUP_FAULT": startup_fault,
                    },
                    labels=inherited_labels,
                    network=self.settings.docker_network_name,
                    ports={
                        f"{self.settings.docker_demo_internal_port}/tcp": (
                            self.settings.docker_demo_host_port
                        )
                    },
                    restart_policy={"Name": "unless-stopped"},
                )
                return
            except DockerException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))

        raise DockerRuntimeConfigurationError(
            "重新创建受管容器失败，请检查容器名称、网络和宿主机端口是否被占用。"
        ) from last_error

    async def _read_http_state(self) -> dict[str, Any] | None:
        try:
            return await self._request_demo("GET", "/internal/state")
        except (httpx.HTTPError, TimeoutError):
            return None

    async def _request_demo(self, method: str, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.settings.docker_demo_service_url,
            timeout=self.settings.runtime_timeout_seconds,
        ) as client:
            response = await client.request(method, path)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("演示服务返回的 JSON 不是对象类型。")
            return payload

    async def _wait_for_service(self) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + self.settings.docker_wait_timeout_seconds
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                state = await self._request_demo("GET", "/internal/state")
                if bool(state.get("running")):
                    return state
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
            await asyncio.sleep(0.5)
        message = "等待受管 Docker 服务恢复可用状态超时。"
        if last_error is not None:
            message = f"{message} 最后一次错误：{last_error}"
        raise TimeoutError(message)

    @staticmethod
    def _env_to_dict(values: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in values:
            key, separator, value = item.partition("=")
            if separator:
                result[key] = value
        return result

    @staticmethod
    def _normalize_fault(value: Any) -> str | None:
        if value in {None, "", "none"}:
            return None
        return str(value)