# ADR-0003: BGE-M3 + bge-reranker-v2-m3 모델 선택

- **상태:** Accepted
- **날짜:** 2026-08-25

## 맥락

RAG 검색 품질은 **Embedding(bi-encoder)** 과 **Reranker(cross-encoder)** 선택에 크게 의존한다.

요구사항:
- 한국어/영어 혼합 문서
- Self-host (API 비용 통제)
- 1024-dim dense, cosine similarity
- rerank top-50 → top-5

## 결정

| 역할 | 모델 | 차원 |
|------|------|------|
| Embedding | `BAAI/bge-m3` | 1024 |
| Reranker | `BAAI/bge-reranker-v2-m3` | — |

- `sentence-transformers` / `CrossEncoder`로 CPU inference (GPU optional)
- Query embedding Redis cache (TTL 1h)

## 대안

| 대안 | 기각 이유 |
|------|-----------|
| OpenAI text-embedding-3 | API 비용·vendor lock-in |
| Cohere rerank API | latency + 비용, self-host reranker와 품질 동급 |
| multilingual-e5-large | bge-m3 대비 다국어 벤치마크 열위 in MTEB |

## 결과

### 장점

- 다국어 SOTA tier, 한국어 포함
- OpenSearch/pgvector **백엔드와 독립** — A/B 시 품질 동점 원인
- HuggingFace 캐시, docker volume 공유

### 단점

- 첫 기동 시 모델 다운로드 (~수 GB)
- CPU reranker **~410ms** — 현재 latency 병목
- worker/API 메모리 2~4GB+

### 후속 조치

- [ ] reranker GPU / ONNX export (Phase 2)
- [ ] `rerank_input_k` 튜닝 (50 → 30)
