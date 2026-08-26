import time
from collections.abc import Callable

import redis.asyncio as aioredis
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from rag.config import get_settings
from rag.observability.logging import get_logger

logger = get_logger(__name__)


class APIKeyMiddleware(BaseHTTPMiddleware):
    EXEMPT_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # api_key = request.headers.get("X-API-Key")
        # if not api_key or api_key != get_settings().api_key:
        #     return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    EXEMPT_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}

    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            settings = get_settings()
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        window = int(time.time()) // 60
        key = f"ratelimit:{client_ip}:{window}"

        try:
            redis = await self._get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 60)
            if count > self.requests_per_minute:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                )
        except Exception as e:
            logger.warning("rate_limit_check_failed", error=str(e))

        return await call_next(request)
