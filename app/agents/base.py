from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.schemas import AlertCreate, DiagnosisDecision


class DiagnosisAgent(ABC):
    @abstractmethod
    async def diagnose(
        self, alert: AlertCreate, evidence: dict[str, Any]
    ) -> DiagnosisDecision:
        raise NotImplementedError
