import time

import httpx
import tiktoken

from rag.config import get_settings
from rag.models.schemas import Citation
from rag.observability.logging import get_logger
from rag.observability.metrics import LLM_LATENCY

logger = get_logger(__name__)


def _encoding():
    return tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def _truncate_tokens(text: str, max_tokens: int) -> str:
    enc = _encoding()
    ids = enc.encode(text)
    if len(ids) <= max_tokens:
        return text
    return enc.decode(ids[:max_tokens])


def build_context(citations: list[Citation], max_tokens: int = 4096) -> str:
    """Numbered context from full chunk text, truncated to a token budget.

    API ``snippet`` stays short. Generation uses ``content`` when set.
    Rank order is kept; the last included chunk may be cut mid-text.
    """
    parts: list[str] = []
    used = 0

    for citation in citations:
        body = citation.content or citation.snippet
        header = f"[{citation.rank}] Source: {citation.filename}"
        if citation.page:
            header += f" (page {citation.page})"
        header_block = f"{header}\n"
        header_tokens = _count_tokens(header_block)
        remaining = max_tokens - used
        if remaining <= header_tokens:
            break
        body_budget = remaining - header_tokens
        body_tokens = _count_tokens(body)
        if body_tokens > body_budget:
            body = _truncate_tokens(body, body_budget)
            parts.append(f"{header_block}{body}\n")
            break
        block = f"{header_block}{body}\n"
        parts.append(block)
        used += header_tokens + body_tokens

    return "\n".join(parts)


class LLMGenerator:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url.rstrip("/")
        llm_cfg = settings.yaml_config.get("llm", {})
        self.model = llm_cfg.get("model", "gpt-4o-mini")
        self.temperature = llm_cfg.get("temperature", 0.1)
        self.max_tokens = llm_cfg.get("max_tokens", 1024)
        self.system_prompt = llm_cfg.get(
            "system_prompt",
            "Answer based on the provided context. Cite sources using [1], [2], etc.",
        )
        self.extra_body = llm_cfg.get("extra_body") or {}

    async def generate(self, query: str, context: str) -> str:
        # OpenAI-compatible servers (vLLM, etc.) accept any/empty key; skip only
        # when neither a key nor a non-default endpoint is configured.
        api_key = self.api_key or "EMPTY"
        if not self.api_key and self.base_url.rstrip("/") == "https://api.openai.com/v1":
            return self._fallback_answer(query, context)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {query}",
            },
        ]

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                        **self.extra_body,
                    },
                )
                response.raise_for_status()
                data = response.json()
                answer = data["choices"][0]["message"]["content"]
                latency = time.perf_counter() - t0
                LLM_LATENCY.observe(latency)
                return answer
        except httpx.HTTPStatusError as e:
            logger.error(
                "llm_generation_failed",
                error=str(e),
                status_code=e.response.status_code,
                body=e.response.text[:1000],
            )
            return self._fallback_answer(query, context)
        except Exception as e:
            logger.error("llm_generation_failed", error=str(e))
            return self._fallback_answer(query, context)

    @staticmethod
    def _fallback_answer(query: str, context: str) -> str:
        if not context.strip():
            return (
                "LLM generation is unavailable and no context was retrieved. "
                "Check LLM_BASE_URL / LLM_API_KEY."
            )
        return (
            f"Based on the retrieved context, here is a summary for: {query}\n\n"
            f"{context}\n\n"
            "(Note: LLM generation is unavailable. Check LLM_BASE_URL / LLM_API_KEY.)"
        )
