from rag.config import get_settings
from rag.generation.llm import LLMGenerator, build_context
from rag.glossary.expand import format_glossary_context, matched_glossary_definitions
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
        *,
        include_glossary_definitions: bool = False,
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
        glossary_text = None
        if include_glossary_definitions:
            glossary_text = format_glossary_context(
                matched_glossary_definitions(query)
            ) or None
        context = build_context(
            citations,
            max_tokens=max_tokens,
            glossary_text=glossary_text,
        )
        answer = await self.llm.generate(query, context)

        return QueryResponse(
            query=query,
            answer=answer,
            backend=self.retrieval.backend_name,
            citations=citations,
            latency_ms=latency,
        )
