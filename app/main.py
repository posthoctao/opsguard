from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import create_tables


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    description=(
        "事件驱动的 AI 后端，用于故障诊断、策略控制的安全修复、"
        "人工审批、确定性恢复验证、隔离式代码修复和多模态视觉证据分析。"
    ),
    lifespan=lifespan,
)
app.include_router(api_router, prefix=settings.api_prefix)
