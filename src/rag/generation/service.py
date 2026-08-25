from rag.generation.llm import LLMGenerator, build_context
from rag.models.schemas import QueryResponse
from rag.retrieval.pipeline import RetrievalPipeline


class QueryService:
    def __init__(
        self,
        backend: str | None = None,
        retrieval: RetrievalPipeline | None = None,
        llm: LLMGenerator | None = None,
    ) -> None:
        self.retrieval = retrieval or RetrievalPipeline(backend=backend)
        self.llm = llm or LLMGenerator()

    async def query(
        self,
        query: str,
        tenant_id: str | None = None,
        top_k: int | None = None,
    ) -> QueryResponse:
        citations, latency = await self.retrieval.retrieve(
            query=query,
            tenant_id=tenant_id,
            top_k=top_k,
            rerank=True,
        )

        context = build_context(citations)
        answer = await self.llm.generate(query, context)

        return QueryResponse(
            query=query,
            answer=answer,
            backend=self.retrieval.backend_name,
            citations=citations,
            latency_ms=latency,
        )
