"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn import Config, Server

from app.api.atlassian_routes import router as atlassian_router
from app.api.auth_dependencies import require_request_authentication
from app.api.auth_routes import router as auth_router
from app.api.routes import router
from app.api.user_routes import router as user_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.mongo import close_mongo, init_mongo
from app.rag.vector_store import get_vector_store
from app.services.openai_service import get_openai_service

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    await init_mongo()
    logger.info(
        "app_starting",
        env=settings.app_env,
        openai_configured=settings.has_openai,
        neo4j=settings.neo4j_enabled,
        demo_fallback=settings.enable_demo_fallback,
    )
    try:
        vs = get_vector_store()
        oa = get_openai_service()
        chroma_diag = vs.diagnostics()
        logger.info(
            "runtime_diagnostics",
            openai_client_ready=oa.available,
            vector_store_mode=vs.backend_mode,
            chroma_connected=vs.backend_mode == "chroma",
            chroma_mode=chroma_diag.get("chroma_mode"),
            chroma_host=chroma_diag.get("chroma_host"),
            chroma_port=chroma_diag.get("chroma_port"),
            chroma_collection=chroma_diag.get("chroma_collection"),
            graph_store_mode=(
                "neo4j+mongo" if settings.neo4j_enabled else "mongo"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("runtime_diagnostics_failed", error=str(exc)[:200])
    try:
        yield
    finally:
        logger.info("app_stopping")
        await close_mongo()


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
        allow_origins=(
            settings.cors_origin_list + ["*"]
            if settings.is_development
            else settings.cors_origin_list
        ),
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


async def serve() -> None:
    settings = get_settings()
    config = Config(
        app="app.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.effective_uvicorn_reload,
        workers=settings.effective_uvicorn_workers,
        log_level=settings.uvicorn_log_level,
        proxy_headers=settings.uvicorn_proxy_headers,
        forwarded_allow_ips=settings.uvicorn_forwarded_allow_ips,
        timeout_keep_alive=settings.uvicorn_timeout_keep_alive_seconds,
        timeout_graceful_shutdown=(
            settings.uvicorn_timeout_graceful_shutdown_seconds
        ),
    )
    logger.info(
        "server_starting",
        host=settings.api_host,
        port=settings.api_port,
        reload=config.reload,
        workers=config.workers,
        env=settings.app_env,
    )
    server = Server(config)
    await server.serve()


def run() -> None:
    """Console entrypoint to run the backend API."""
    logger.info("entrypoint_initializing")
    settings = get_settings()
    logger.info(
        "entrypoint_configuration",
        env=settings.app_env,
        reload=settings.effective_uvicorn_reload,
        workers=settings.effective_uvicorn_workers,
    )
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        logger.info("server_interrupted")
    finally:
        logger.info("entrypoint_stopped")
