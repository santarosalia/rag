from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import make_asgi_app
from sqlalchemy import text

from rag import __version__
from rag.api.middleware import APIKeyMiddleware, RateLimitMiddleware
from rag.api.routes import router
from rag.config import get_settings
from rag.db.session import engine
from rag.indexing.factory import get_search_backend
from rag.models.schemas import HealthResponse, ReadyResponse
from rag.observability.logging import get_logger, setup_logging
from rag.observability.tracing import setup_tracing

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    setup_tracing("rag-api")
    logger.info("starting_rag_api", version=__version__, env=settings.app_env)

    search_backend = get_search_backend()
    try:
        await search_backend.ensure_index()
    except Exception as e:
        logger.warning("search_backend_init_deferred", backend=search_backend.name, error=str(e))
    finally:
        await search_backend.close()

    yield
    await engine.dispose()
    logger.info("rag_api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    rate_limit = settings.yaml_config.get("rate_limit", {}).get("requests_per_minute", 60)

    app = FastAPI(
        title="Hybrid RAG API",
        description="Production-grade RAG with pgvector + FTS hybrid search",
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(RateLimitMiddleware, requests_per_minute=rate_limit)
    app.add_middleware(APIKeyMiddleware)
    app.include_router(router)
    FastAPIInstrumentor.instrument_app(app)

    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/ready", response_model=ReadyResponse)
    async def ready() -> ReadyResponse:
        checks: dict[str, Any] = {}

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception as e:
            checks["postgres"] = f"error: {e}"

        try:
            redis = aioredis.from_url(settings.redis_url)
            await redis.ping()
            await redis.aclose()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {e}"

        try:
            search_backend = get_search_backend()
            ok = await search_backend.ping()
            await search_backend.close()
            checks["search_pgvector"] = "ok" if ok else "error: ping failed"
        except Exception as e:
            checks["search_pgvector"] = f"error: {e}"

        required = {"postgres", "redis", "search_pgvector"}
        all_ok = all(checks.get(k) == "ok" for k in required)
        return ReadyResponse(
            status="ready" if all_ok else "not_ready",
            checks=checks,
        )

    return app


app = create_app()
