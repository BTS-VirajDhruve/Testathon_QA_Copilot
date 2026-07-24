"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    logger.info(
        "app_starting",
        env=settings.app_env,
        openai=settings.has_openai,
        neo4j=settings.neo4j_enabled,
    )
    yield
    logger.info("app_stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Agentic QA Copilot",
        description="Graph RAG + Vector RAG agentic QA intelligence system",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list + ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    return app


app = create_app()