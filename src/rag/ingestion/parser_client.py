"""HTTP client for Parser Service (POST /parse)."""

from __future__ import annotations

import httpx

from rag.config import get_settings
from rag.models.parse import ParseResponse
from rag.observability.logging import get_logger

logger = get_logger(__name__)


class ParserError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ParserClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.parse_api_base_url).rstrip("/")
        self.timeout = timeout_seconds if timeout_seconds is not None else settings.parse_api_timeout_seconds

    async def parse(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str | None = None,
        output_format: str = "markdown",
    ) -> ParseResponse:
        url = f"{self.base_url}/parse"
        params = {"output_format": output_format}
        files = {
            "file": (
                filename,
                data,
                content_type or "application/octet-stream",
            )
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, params=params, files=files)
        except httpx.TimeoutException as exc:
            raise ParserError(f"Parser service timeout after {self.timeout}s") from exc
        except httpx.HTTPError as exc:
            raise ParserError(f"Parser service unreachable: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            raise ParserError(
                f"Parser service HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
            )

        parsed = ParseResponse.model_validate(response.json())
        if parsed.status.upper() != "SUCCESS":
            raise ParserError(parsed.error or f"Parse failed with status={parsed.status}")

        logger.info(
            "document_parsed",
            filename=filename,
            results=len(parsed.results),
            processing_time_ms=parsed.processing_time_ms,
        )
        return parsed
