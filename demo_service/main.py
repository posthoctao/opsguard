import logging
import os
from dataclasses import asdict, dataclass
from threading import Lock

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel

logger = logging.getLogger("demo_service")


@dataclass
class RuntimeState:
    service_name: str = "demo-api"
    running: bool = True
    version: str = "v1-stable"
    error_rate: float = 0.0
    latency_ms: int = 50
    active_fault: str | None = None


class RollbackRequest(BaseModel):
    target_version: str = "v1-stable"


def _build_initial_state() -> RuntimeState:
    state = RuntimeState(version=os.getenv("APP_VERSION", "v1-stable"))
    startup_fault = os.getenv("STARTUP_FAULT", "none")
    if startup_fault == "deploy_regression":
        state.error_rate = 0.35
        state.active_fault = startup_fault
    elif startup_fault not in {"", "none"}:
        raise RuntimeError(f"不支持的 STARTUP_FAULT={startup_fault!r}")
    return state


app = FastAPI(title="故障注入演示服务", version="0.2.0", description="用于模拟服务不可用、部署回归和高延迟的受控测试服务。")
_state = _build_initial_state()
_lock = Lock()
logger.info(
    "演示服务已启动 version=%s startup_fault=%s",
    _state.version,
    _state.active_fault,
)


@app.get("/health")
def health(response: Response) -> dict:
    with _lock:
        state = asdict(_state)
    if not state["running"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if state["running"] else "unavailable", **state}


@app.get("/internal/state")
def internal_state() -> dict:
    with _lock:
        return asdict(_state)


@app.post("/admin/faults/{fault_type}")
def inject_fault(fault_type: str) -> dict:
    with _lock:
        if fault_type == "service_unavailable":
            _state.running = False
            _state.error_rate = 1.0
        elif fault_type == "deploy_regression":
            _state.running = True
            _state.version = "v2-buggy"
            _state.error_rate = 0.35
        elif fault_type == "high_latency":
            _state.running = True
            _state.latency_ms = 2500
        else:
            raise HTTPException(status_code=400, detail="不支持的故障类型")
        _state.active_fault = fault_type
        logger.warning("已注入故障 type=%s state=%s", fault_type, asdict(_state))
        return asdict(_state)


@app.post("/admin/actions/restart")
def restart() -> dict:
    with _lock:
        _state.running = True
        _state.error_rate = 0.0
        _state.latency_ms = 50
        _state.active_fault = None
        logger.info("逻辑重启已完成 state=%s", asdict(_state))
        return {"ok": True, "action": "restart_service", "state": asdict(_state)}


@app.post("/admin/actions/rollback")
def rollback(request: RollbackRequest) -> dict:
    with _lock:
        _state.running = True
        _state.version = request.target_version
        _state.error_rate = 0.0
        _state.latency_ms = 50
        _state.active_fault = None
        logger.info("逻辑回滚已完成 state=%s", asdict(_state))
        return {"ok": True, "action": "rollback_deployment", "state": asdict(_state)}


@app.post("/admin/actions/reset")
def reset() -> dict:
    global _state
    with _lock:
        _state = RuntimeState(version=os.getenv("APP_VERSION", "v1-stable"))
        logger.info("逻辑重置已完成 state=%s", asdict(_state))
        return asdict(_state)
