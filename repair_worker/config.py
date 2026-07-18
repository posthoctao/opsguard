from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RepairWorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    repair_agent_provider: Literal["rules", "claude"] = "rules"
    repair_claude_model: str = "claude-sonnet-4-6"
    repair_claude_max_turns: int = Field(default=12, ge=1, le=30)
    repair_claude_timeout_seconds: int = Field(default=180, ge=30, le=900)
    repair_claude_max_budget_usd: float = Field(default=2.0, ge=0.05, le=20.0)

    repair_source_root: Path = Path("./repair_targets")
    repair_workspace_root: Path = Path("./data/repair_workspaces")
    repair_test_timeout_seconds: int = Field(default=60, ge=5, le=600)
    repair_verifier_url: str = "http://repair-verifier:8100"


@lru_cache
def get_repair_worker_settings() -> RepairWorkerSettings:
    return RepairWorkerSettings()
