"""Golden Q&A evaluation dataset and benchmark runner."""

from rag.retrieval.fusion import rrf_fuse

GOLDEN_SET = [
    {
        "query": "What is hybrid search?",
        "relevant_chunk_ids": {"chunk_hybrid_1", "chunk_hybrid_2"},
        "dense_results": ["chunk_hybrid_1", "chunk_other_1", "chunk_hybrid_2"],
        "sparse_results": ["chunk_hybrid_2", "chunk_sparse_1", "chunk_hybrid_1"],
    },
    {
        "query": "How does reranking work?",
        "relevant_chunk_ids": {"chunk_rerank_1"},
        "dense_results": ["chunk_rerank_1", "chunk_other_2"],
        "sparse_results": ["chunk_other_2", "chunk_rerank_1"],
    },
]


def run_fusion_benchmark() -> dict:
    from tests.eval.metrics import mrr, ndcg_at_k, recall_at_k

    metrics = {"recall@5": [], "mrr": [], "ndcg@5": []}

    for item in GOLDEN_SET:
        dense = [{"chunk_id": cid, "content": cid} for cid in item["dense_results"]]
        sparse = [{"chunk_id": cid, "content": cid} for cid in item["sparse_results"]]
        fused = rrf_fuse(dense, sparse)
        retrieved = [h["chunk_id"] for h in fused]
        relevant = item["relevant_chunk_ids"]

        metrics["recall@5"].append(recall_at_k(relevant, retrieved, 5))
        metrics["mrr"].append(mrr(relevant, retrieved))
        metrics["ndcg@5"].append(ndcg_at_k(relevant, retrieved, 5))

    return {k: sum(v) / len(v) for k, v in metrics.items()}


def test_fusion_benchmark_meets_threshold():
    results = run_fusion_benchmark()
    assert results["recall@5"] >= 0.5
    assert results["mrr"] >= 0.5
