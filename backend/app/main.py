from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api import websocket as websocket_api
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await websocket_api.transcription_session_registry.shutdown()

app = FastAPI(
    title=settings.app_name,
    version="0.5.5",
    description=(
        "Realtime transcription, conversation analysis, bounded session memory, "
        "provider-neutral streamed answers, and advisory next-turn prediction "
        "for Mentara AI."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(websocket_api.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "milestone": "5.5 — Predictive Next-Turn (verification in progress)",
        "docs": "/docs",
    }
