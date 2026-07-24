from fastapi import APIRouter, HTTPException

from app.dependencies import get_runtime
from app.schemas import FaultInjectionRequest, RuntimeState

router = APIRouter(prefix="/runtime", tags=["故障演示运行时"])


@router.get("/state", response_model=RuntimeState, summary="查询演示服务运行状态")
async def get_state() -> RuntimeState:
    return RuntimeState.model_validate(await get_runtime().get_state())


@router.post("/faults", response_model=RuntimeState, summary="注入测试故障")
async def inject_fault(request: FaultInjectionRequest) -> RuntimeState:
    try:
        state = await get_runtime().inject_fault(request.fault_type)
        return RuntimeState.model_validate(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset", response_model=RuntimeState, summary="重置演示服务状态")
async def reset_runtime() -> RuntimeState:
    return RuntimeState.model_validate(await get_runtime().reset())
