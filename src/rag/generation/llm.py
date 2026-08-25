import time

import httpx

from rag.config import get_settings
from rag.models.schemas import Citation
from rag.observability.logging import get_logger
from rag.observability.metrics import LLM_LATENCY

logger = get_logger(__name__)


def build_context(citations: list[Citation], max_tokens: int = 4096) -> str:
    """Build numbered context string from citations with token budget."""
    parts: list[str] = []
    total_chars = 0
    char_budget = max_tokens * 4  # rough chars-to-tokens estimate

    for citation in citations:
        header = f"[{citation.rank}] Source: {citation.filename}"
        if citation.page:
            header += f" (page {citation.page})"
        block = f"{header}\n{citation.snippet}\n"
        if total_chars + len(block) > char_budget:
            break
        parts.append(block)
        total_chars += len(block)

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

    async def generate(self, query: str, context: str) -> str:
        if not self.api_key:
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
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                    },
                )
                response.raise_for_status()
                data = response.json()
                answer = data["choices"][0]["message"]["content"]
                latency = time.perf_counter() - t0
                LLM_LATENCY.observe(latency)
                return answer
        except Exception as e:
            logger.error("llm_generation_failed", error=str(e))
            return self._fallback_answer(query, context)

    @staticmethod
    def _fallback_answer(query: str, context: str) -> str:
        if not context.strip():
            return (
                "LLM API key is not configured and no context was retrieved. "
                "Please set LLM_API_KEY to enable generation."
            )
        return (
            f"Based on the retrieved context, here is a summary for: {query}\n\n"
            f"{context}\n\n"
            "(Note: Set LLM_API_KEY for full LLM-powered answers.)"
        )
