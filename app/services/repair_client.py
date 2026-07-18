from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.schemas import CodeRepairWorkerRequest, CodeRepairWorkerResult


class RepairWorkerClient(ABC):
    @abstractmethod
    async def run_repair(self, request: CodeRepairWorkerRequest) -> CodeRepairWorkerResult:
        raise NotImplementedError


class HttpRepairWorkerClient(RepairWorkerClient):
    def __init__(self, base_url: str, timeout_seconds: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def run_repair(self, request: CodeRepairWorkerRequest) -> CodeRepairWorkerResult:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/internal/v1/repairs/run",
                json=request.model_dump(mode="json"),
            )
            if response.is_error:
                try:
                    error_detail = response.json()
                except ValueError:
                    error_detail = response.text

                raise RuntimeError(
                    "代码修复 Worker 请求失败："
                    f"HTTP {response.status_code}，"
                    f"响应内容：{error_detail}"
                )
            return CodeRepairWorkerResult.model_validate(response.json())
