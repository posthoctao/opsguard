from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.schemas import VerificationResult


class RuntimeAdapter(ABC):
    @abstractmethod
    async def collect_evidence(self, service_name: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute_action(self, action_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def verify(self, alert_type: str, service_name: str) -> VerificationResult:
        raise NotImplementedError

    @abstractmethod
    async def inject_fault(self, fault_type: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def reset(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_state(self) -> dict[str, Any]:
        raise NotImplementedError
