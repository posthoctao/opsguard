import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.schemas import RepairVerificationRequest, RepairVerificationResult
from repair_verifier.service import RepairVerifierService

app = FastAPI(
    title="代码修复验证服务",
    version="0.3.0",
    description="不持有任何密钥、仅运行固定回归测试命令的内部验证服务。",
)


@app.get("/health", summary="检查代码修复验证服务健康状态")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/internal/v1/verify", response_model=RepairVerificationResult, summary="独立执行固定回归测试")
def verify(request: RepairVerificationRequest) -> RepairVerificationResult:
    service = RepairVerifierService(
        workspace_root=Path(os.getenv("REPAIR_WORKSPACE_ROOT", "/workspaces/jobs")),
        timeout_seconds=int(os.getenv("REPAIR_TEST_TIMEOUT_SECONDS", "60")),
    )
    try:
        return service.verify(request.job_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
