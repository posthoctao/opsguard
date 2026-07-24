from fastapi import APIRouter

router = APIRouter(tags=["健康检查"])


@router.get("/health", summary="检查后端服务健康状态")
def health() -> dict[str, str]:
    return {"status": "ok"}
