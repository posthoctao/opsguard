import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.runtime.docker import DockerRuntime


class FakeContainer:
    def __init__(
        self,
        *,
        name: str = "incident-ai-demo-service",
        managed: bool = True,
        running: bool = True,
        version: str = "v1-stable",
        startup_fault: str = "none",
        image: str = "incident-ai-demo:local",
    ) -> None:
        self.name = name
        self.restart_calls = 0
        self.stop_calls = 0
        self.remove_calls = 0
        labels = {"com.incident-ai.managed": "true"} if managed else {}
        self.attrs = {
            "Id": "abcdef1234567890",
            "State": {
                "Status": "running" if running else "exited",
                "Running": running,
                "ExitCode": 0,
                "StartedAt": "2026-07-18T00:00:00Z",
                "FinishedAt": "",
                "Health": {"Status": "healthy" if running else "unhealthy"},
            },
            "Config": {
                "Image": image,
                "Labels": labels,
                "Env": [f"APP_VERSION={version}", f"STARTUP_FAULT={startup_fault}"],
            },
            "RestartCount": 0,
        }
        self.status = self.attrs["State"]["Status"]

    def reload(self) -> None:
        self.status = self.attrs["State"]["Status"]

    def logs(self, tail: int) -> bytes:
        return f"last {tail} lines\nservice log".encode()

    def restart(self, timeout: int) -> None:
        self.restart_calls += 1
        self.attrs["State"]["Running"] = True
        self.attrs["State"]["Status"] = "running"
        self.attrs["State"]["Health"] = {"Status": "healthy"}

    def stop(self, timeout: int) -> None:
        self.stop_calls += 1
        self.attrs["State"]["Running"] = False
        self.attrs["State"]["Status"] = "exited"
        self.attrs["State"]["Health"] = {"Status": "unhealthy"}

    def remove(self, force: bool) -> None:
        self.remove_calls += 1


class FakeContainers:
    def __init__(self, container: FakeContainer) -> None:
        self.current = container
        self.run_calls: list[dict] = []

    def get(self, name: str) -> FakeContainer:
        if name != self.current.name:
            raise AssertionError(f"出现非预期的容器查询：{name}")
        return self.current

    def run(self, **kwargs):
        self.run_calls.append(kwargs)
        environment = kwargs["environment"]
        self.current = FakeContainer(
            name=kwargs["name"],
            managed=True,
            running=True,
            version=environment["APP_VERSION"],
            startup_fault=environment["STARTUP_FAULT"],
            image=kwargs["image"],
        )
        return self.current


class FakeDockerClient:
    def __init__(self, container: FakeContainer) -> None:
        self.containers = FakeContainers(container)


def _settings() -> Settings:
    return Settings(
        runtime_backend="docker",
        docker_container_name="incident-ai-demo-service",
        docker_demo_service_url="http://incident-ai-demo-service:8081",
        docker_network_name="incident-ai-network",
        docker_network_alias="demo-service",
        docker_demo_image="incident-ai-demo:local",
    )


def test_docker_runtime_rejects_unmanaged_container():
    runtime = DockerRuntime(_settings(), client=FakeDockerClient(FakeContainer(managed=False)))

    with pytest.raises(PermissionError, match="受管标签"):
        runtime._inspect_managed_container()


def test_restart_uses_only_the_allowlisted_container(monkeypatch):
    container = FakeContainer()
    runtime = DockerRuntime(_settings(), client=FakeDockerClient(container))
    monkeypatch.setattr(
        runtime,
        "_wait_for_service",
        AsyncMock(
            return_value={
                "service_name": "demo-api",
                "running": True,
                "version": "v1-stable",
                "error_rate": 0.0,
                "latency_ms": 50,
                "active_fault": None,
            }
        ),
    )

    result = asyncio.run(
        runtime.execute_action("restart_service", {"service_name": "demo-api"})
    )

    assert result["ok"] is True
    assert container.restart_calls == 1


def test_rollback_recreates_the_container_with_stable_version(monkeypatch):
    old = FakeContainer(
        version="v2-buggy",
        startup_fault="deploy_regression",
    )
    client = FakeDockerClient(old)
    runtime = DockerRuntime(_settings(), client=client)

    monkeypatch.setattr(
        runtime,
        "_wait_for_service",
        AsyncMock(
            return_value={
                "service_name": "demo-api",
                "running": True,
                "version": "v1-stable",
                "error_rate": 0.0,
                "latency_ms": 50,
                "active_fault": None,
            }
        ),
    )

    result = asyncio.run(
        runtime.execute_action(
            "rollback_deployment",
            {
                "service_name": "demo-api",
                "target_version": "v1-stable",
            },
        )
    )

    assert result["target_version"] == "v1-stable"
    assert old.remove_calls == 1

    call = client.containers.run_calls[0]

    assert call["environment"] == {
        "APP_VERSION": "v1-stable",
        "STARTUP_FAULT": "none",
    }
    assert call["network"] == "incident-ai-network"

    # Docker SDK 的 containers.run() 不支持 network_aliases 参数，
    # 当前通过固定受管容器名进行服务访问。
    assert "network_aliases" not in call

    assert call["ports"] == {
        "8081/tcp": 8081,
    }
    assert call["restart_policy"] == {
        "Name": "unless-stopped",
    }

def test_rollback_rejects_non_allowlisted_target():
    runtime = DockerRuntime(_settings(), client=FakeDockerClient(FakeContainer()))

    with pytest.raises(ValueError, match="仅允许目标版本"):
        asyncio.run(
            runtime.execute_action(
                "rollback_deployment",
                {"service_name": "demo-api", "target_version": "attacker-image"},
            )
        )


def test_service_unavailable_fault_stops_real_container(monkeypatch):
    container = FakeContainer()
    runtime = DockerRuntime(_settings(), client=FakeDockerClient(container))
    monkeypatch.setattr(runtime, "_read_http_state", AsyncMock(return_value=None))

    state = asyncio.run(runtime.inject_fault("service_unavailable"))

    assert container.stop_calls == 1
    assert state["running"] is False
    assert state["error_rate"] == 1.0
