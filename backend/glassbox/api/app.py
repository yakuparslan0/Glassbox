"""Application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Settings, ensure_safe_startup
from ..sandbox.docker_backend import DockerBackend
from ..sandbox.manager import SandboxManager
from ..sandbox.subprocess_backend import SubprocessBackend
from ..schemas.api import Health, LlmHealth
from .routes_analysis import router as analysis_router
from .routes_runs import router as runs_router
from .store import Runtime
from .ws import router as ws_router


def create_app(settings: Settings | None = None, manager: SandboxManager | None = None) -> FastAPI:
    """Build the app. Raises ``StartupError`` when the configuration is unsafe (see ``ensure_safe_startup``)."""
    settings = settings or Settings()
    ensure_safe_startup(settings)
    if manager is None:
        backend = DockerBackend(settings.docker_image) if settings.sandbox_mode == "docker" else SubprocessBackend()
        manager = SandboxManager(backend=backend)

    app = FastAPI(title="GlassBox", version="0.2.0")
    app.state.runtime = Runtime(settings, manager)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(runs_router)
    app.include_router(analysis_router)
    app.include_router(ws_router)

    @app.get("/api/health", response_model=Health)
    async def health() -> Health:
        # LLM providers arrive in Phase 4; until then the list is honestly empty.
        return Health(status="ok", llm=LlmHealth(providers=[]), sandbox_mode=settings.sandbox_mode)

    return app
