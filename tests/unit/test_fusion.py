
from rag.retrieval.fusion import rrf_fuse


def test_rrf_fuse_combines_rankings():
    dense = [
        {"chunk_id": "a", "content": "alpha", "score": 0.9},
        {"chunk_id": "b", "content": "beta", "score": 0.8},
    ]
    sparse = [
        {"chunk_id": "b", "content": "beta", "score": 5.0},
        {"chunk_id": "c", "content": "gamma", "score": 4.0},
    ]

    fused = rrf_fuse(dense, sparse, k=60)

    assert len(fused) == 3
    ids = [h["chunk_id"] for h in fused]
    assert "b" in ids
    assert fused[0]["chunk_id"] == "b"  # appears in both lists, highest RRF
    assert "rrf_score" in fused[0]


def test_rrf_fuse_empty():
    assert rrf_fuse([], []) == []


def test_rrf_fuse_single_source():
    dense = [{"chunk_id": "x", "content": "test", "score": 1.0}]
    fused = rrf_fuse(dense, [], k=60)
    assert len(fused) == 1
    assert fused[0]["chunk_id"] == "x"
