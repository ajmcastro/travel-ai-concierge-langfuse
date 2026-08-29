from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from travel_ai_concierge.api.routes.health import router as health_router
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.logging_config import configure_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "starting",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        langfuse_host=settings.langfuse_host,
        langfuse_enabled=settings.langfuse_enabled,
    )
    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Travel AI Concierge — Langfuse Observability Lab. "
            "A production-quality reference implementation of an Agentic AI system "
            "with comprehensive LLM observability."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)

    return app


app = create_app()
