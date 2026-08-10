"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn import run as uvicorn_run

from app.api.routes import router
from app.api.atlassian_routes import router as atlassian_router
from app.api.auth_dependencies import require_request_authentication
from app.api.auth_routes import router as auth_router
from app.api.user_routes import router as user_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.mongo import close_mongo, init_mongo

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    init_mongo()
    logger.info(
        "app_starting",
        env=settings.app_env,
        openai_configured=settings.has_openai,
        neo4j=settings.neo4j_enabled,
        demo_fallback=settings.enable_demo_fallback,
    )
    try:
        from app.rag.vector_store import get_vector_store
        from app.services.openai_service import get_openai_service

        vs = get_vector_store()
        oa = get_openai_service()
        logger.info(
            "runtime_diagnostics",
            openai_client_ready=oa.available,
            vector_store_mode=vs.backend_mode,
            graph_store_mode=(
                "neo4j+json"
                if settings.neo4j_enabled
                else "json"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("runtime_diagnostics_failed", error=str(exc)[:200])
    try:
        yield
    finally:
        close_mongo()
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
        expose_headers=[
            "Content-Disposition",
            "X-QA-Exported-Scenarios",
            "X-QA-Exported-Files",
            "X-QA-Analysis-Id",
        ],
    )
    app.include_router(
        router,
        prefix="/api",
        dependencies=[Depends(require_request_authentication)],
    )
    app.include_router(
        atlassian_router,
        prefix="/api",
        dependencies=[Depends(require_request_authentication)],
    )
    app.include_router(
        auth_router,
        prefix="/api",
        dependencies=[Depends(require_request_authentication)],
    )
    app.include_router(
        user_router,
        prefix="/api",
        dependencies=[Depends(require_request_authentication)],
    )
    return app


app = create_app()


def run() -> None:
    """Console entrypoint to run the backend API locally."""
    settings = get_settings()
    uvicorn_run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "development",
    )
