from fastapi import FastAPI, HTTPException

from app.schemas import CodeRepairWorkerRequest, CodeRepairWorkerResult
from repair_worker.config import get_repair_worker_settings
from repair_worker.service import RepairWorkerService

app = FastAPI(
    title="隔离式代码修复 Worker",
    version="0.3.0",
    description=(
        "内部 Worker：把白名单源码模板复制到独立工作区，"
        "运行受约束的代码修复 Agent，并独立验证补丁。"
    ),
)


@app.get("/health", summary="检查代码修复 Worker 健康状态")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/internal/v1/repairs/run", response_model=CodeRepairWorkerResult, summary="执行隔离式代码修复任务")
async def run_repair(request: CodeRepairWorkerRequest) -> CodeRepairWorkerResult:
    service = RepairWorkerService(get_repair_worker_settings())
    try:
        return await service.run(request)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
