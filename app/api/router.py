from fastapi import APIRouter

from app.api.routes import alerts, health, incidents, repairs, runtime

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(alerts.router)
api_router.include_router(incidents.router)
api_router.include_router(repairs.router)
api_router.include_router(runtime.router)
