from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "stt_provider": settings.stt_provider,
        "stt_model": settings.stt_model,
        "stt_configured": settings.stt_configured,
    }
