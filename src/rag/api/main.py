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
from rag.indexing.opensearch_client import OpenSearchClient
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

    opensearch = OpenSearchClient()
    try:
        await opensearch.ensure_index()
    except Exception as e:
        logger.warning("opensearch_init_deferred", error=str(e))
    finally:
        await opensearch.close()

    yield
    await engine.dispose()
    logger.info("rag_api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    rate_limit = settings.yaml_config.get("rate_limit", {}).get("requests_per_minute", 60)

    app = FastAPI(
        title="Hybrid RAG API",
        description="Production-grade RAG with dense, sparse, and rerank",
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
            opensearch = OpenSearchClient()
            ok = await opensearch.ping()
            await opensearch.close()
            checks["opensearch"] = "ok" if ok else "error: ping failed"
        except Exception as e:
            checks["opensearch"] = f"error: {e}"

        all_ok = all(v == "ok" for v in checks.values())
        return ReadyResponse(
            status="ready" if all_ok else "not_ready",
            checks=checks,
        )

    return app


app = create_app()
