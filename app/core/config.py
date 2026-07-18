from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "智能故障诊断与安全修复后端"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/incidents.db"
    dedupe_window_seconds: int = 300

    ai_provider: Literal["rules", "claude"] = "rules"
    ai_fallback_to_rules: bool = True
    claude_model: str = "claude-sonnet-4-6"
    claude_max_turns: int = 3
    claude_timeout_seconds: int = 90

    runtime_backend: Literal["memory", "http", "docker"] = "memory"
    demo_service_url: str = "http://demo-service:8081"
    runtime_timeout_seconds: float = 10.0

    # Docker Runtime 配置。以下值全部由服务端控制，不接受 LLM 输出。
    docker_container_name: str = "incident-ai-demo-service"
    docker_demo_service_url: str = "http://incident-ai-demo-service:8081"
    docker_network_name: str = "incident-ai-network"
    docker_network_alias: str = "demo-service"
    docker_demo_image: str = "incident-ai-demo:local"
    docker_demo_internal_port: int = 8081
    docker_demo_host_port: int = 8081
    docker_managed_label_key: str = "com.incident-ai.managed"
    docker_managed_label_value: str = "true"
    docker_stable_version: str = "v1-stable"
    docker_buggy_version: str = "v2-buggy"
    docker_wait_timeout_seconds: float = 30.0
    docker_logs_tail: int = Field(default=100, ge=10, le=1000)

    auto_process_alerts: bool = True
    max_remediation_attempts: int = Field(default=1, ge=1, le=3)

    repair_worker_url: str = "http://repair-worker:8090"
    repair_worker_timeout_seconds: float = 180.0
    repair_source_profile: str = "demo-buffer-bug"

    github_pr_enabled: bool = False
    github_token: str | None = None
    github_repository: str | None = None
    github_base_branch: str = "main"
    github_api_url: str = "https://api.github.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
