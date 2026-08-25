from typing import Any


def rrf_fuse(
    dense_hits: list[dict[str, Any]],
    sparse_hits: list[dict[str, Any]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion of dense and sparse retrieval results."""
    scores: dict[str, float] = {}
    docs: dict[str, dict[str, Any]] = {}

    for hits in (dense_hits, sparse_hits):
        for rank, hit in enumerate(hits, start=1):
            chunk_id = str(hit.get("chunk_id", ""))
            if not chunk_id:
                continue
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            if chunk_id not in docs:
                docs[chunk_id] = hit.copy()

    fused = []
    for chunk_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        doc = docs[chunk_id]
        doc["rrf_score"] = score
        fused.append(doc)

    return fused
