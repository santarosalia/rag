from rag.config import get_settings
from rag.generation.llm import LLMGenerator, build_context
from rag.models.schemas import QueryResponse
from rag.retrieval.pipeline import RetrievalPipeline


class QueryService:
    def __init__(
        self,
        retrieval: RetrievalPipeline | None = None,
        llm: LLMGenerator | None = None,
    ) -> None:
        self.retrieval = retrieval or RetrievalPipeline()
        self.llm = llm or LLMGenerator()

    async def query(
        self,
        query: str,
        group_id: str | None = None,
        top_k: int | None = None,
    ) -> QueryResponse:
        citations, latency = await self.retrieval.retrieve(
            query=query,
            group_id=group_id,
            top_k=top_k,
            rerank=True,
        )

        max_tokens = get_settings().yaml_config.get("retrieval", {}).get(
            "context_max_tokens", 4096
        )
        context = build_context(citations, max_tokens=max_tokens)
        answer = await self.llm.generate(query, context)

        return QueryResponse(
            query=query,
            answer=answer,
            backend=self.retrieval.backend_name,
            citations=citations,
            latency_ms=latency,
        )
