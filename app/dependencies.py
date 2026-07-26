from functools import lru_cache

from app.agents.factory import build_diagnosis_agent
from app.agents.vision import ClaudeVisionEvidenceAgent
from app.core.config import get_settings
from app.runtime.base import RuntimeAdapter
from app.runtime.docker import DockerRuntime
from app.runtime.http import HttpDemoRuntime
from app.runtime.memory import InMemoryRuntime
from app.services.github import GitHubPullRequestPublisher
from app.services.orchestrator import IncidentOrchestrator
from app.services.repair_client import HttpRepairWorkerClient, RepairWorkerClient
from app.services.repair_orchestrator import CodeRepairOrchestrator

_runtime_override: RuntimeAdapter | None = None
_repair_client_override: RepairWorkerClient | None = None


@lru_cache
def get_runtime() -> RuntimeAdapter:
    if _runtime_override is not None:
        return _runtime_override
    settings = get_settings()
    if settings.runtime_backend == "docker":
        return DockerRuntime(settings=settings)
    if settings.runtime_backend == "http":
        return HttpDemoRuntime(
            base_url=settings.demo_service_url,
            timeout_seconds=settings.runtime_timeout_seconds,
        )
    return InMemoryRuntime()


def set_runtime_override(runtime: RuntimeAdapter | None) -> None:
    global _runtime_override
    _runtime_override = runtime
    get_runtime.cache_clear()


@lru_cache
def get_vision_agent() -> ClaudeVisionEvidenceAgent:
    settings = get_settings()
    return ClaudeVisionEvidenceAgent(
        model=settings.vision_model,
        timeout_seconds=settings.vision_timeout_seconds,
    )


def get_orchestrator() -> IncidentOrchestrator:
    settings = get_settings()
    return IncidentOrchestrator(
        settings=settings,
        runtime=get_runtime(),
        diagnosis_agent=build_diagnosis_agent(settings),
    )


@lru_cache
def get_repair_client() -> RepairWorkerClient:
    if _repair_client_override is not None:
        return _repair_client_override
    settings = get_settings()
    return HttpRepairWorkerClient(
        base_url=settings.repair_worker_url,
        timeout_seconds=settings.repair_worker_timeout_seconds,
    )


def set_repair_client_override(client: RepairWorkerClient | None) -> None:
    global _repair_client_override
    _repair_client_override = client
    get_repair_client.cache_clear()


def get_repair_orchestrator() -> CodeRepairOrchestrator:
    return CodeRepairOrchestrator(worker=get_repair_client())


def get_github_publisher() -> GitHubPullRequestPublisher:
    return GitHubPullRequestPublisher(get_settings())
