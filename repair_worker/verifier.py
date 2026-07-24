from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from app.schemas import RepairVerificationRequest, RepairVerificationResult


class RepairVerifier(ABC):
    @abstractmethod
    async def verify(self, job_id: str) -> RepairVerificationResult:
        raise NotImplementedError


class HttpRepairVerifier(RepairVerifier):
    def __init__(self, base_url: str, timeout_seconds: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def verify(self, job_id: str) -> RepairVerificationResult:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/internal/v1/verify",
                json=RepairVerificationRequest(job_id=job_id).model_dump(mode="json"),
            )
            response.raise_for_status()
            return RepairVerificationResult.model_validate(response.json())


class LocalRepairVerifier(RepairVerifier):
    """仅用于单元测试和非 Docker 本地开发的验证器。"""

    def __init__(self, workspace_root: Path, timeout_seconds: int = 60) -> None:
        from repair_verifier.service import RepairVerifierService

        self.service = RepairVerifierService(
            workspace_root=workspace_root,
            timeout_seconds=timeout_seconds,
        )

    async def verify(self, job_id: str) -> RepairVerificationResult:
        return self.service.verify(job_id)
