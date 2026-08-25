# RAG 시스템 기획서

> **프로젝트명:** Hybrid RAG Platform  
> **버전:** 0.1.0  
> **최종 수정:** 2026-08-25  
> **상태:** Phase 1 구현 완료 + Dual Search Backend (OpenSearch / pgvector)

---

## 1. 개요

### 1.1 목적

대규모 프로덕션 환경에서 안정적으로 운영 가능한 **Retrieval-Augmented Generation(RAG)** 플랫폼을 구축한다.  
단순 벡터 검색이 아닌 **Dense + Sparse 하이브리드 검색**, **Cross-encoder Rerank**, **출처 기반 답변 생성**을 통해 검색 정확도와 답변 신뢰도를 동시에 확보한다.

### 1.2 핵심 목표

| 목표 | 설명 | 달성 기준 |
|------|------|-----------|
| **검색 품질** | 의미 검색 + 키워드 검색 결합 | Hybrid 모드 Recall@5 ≥ 0.8 (golden set) |
| **답변 신뢰도** | 출처(citation) 포함 답변 | 모든 `/v1/query` 응답에 citations[] 포함 |
| **확장성** | 대량 문서 비동기 처리 | Celery worker horizontal scale-out |
| **운영성** | 관측·배포·복구 가능 | Prometheus metrics, K8s manifests, reindex runbook |
| **다국어** | 한국어/영어 혼합 문서 | Nori(OpenSearch) / Kiwi(pgvector) + BGE-M3 |
| **백엔드 비교** | OpenSearch vs PG pgvector A/B | `SEARCH_BACKEND` / API `backend` 파라미터 |

### 1.3 비목표 (Out of Scope — Phase 1)

- 멀티모달(이미지/음성) RAG
- 실시간 스트리밍 답변 (SSE)
- Graph RAG / Agentic RAG
- 사용자 피드백 기반 online learning

---

## 2. 아키텍처

### 2.1 전체 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client / Application                      │
└───────────────────────────────┬─────────────────────────────────┘
                                │ REST API (X-API-Key)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI (rag-api)                            │
│  POST /v1/documents  GET /v1/documents/{id}  DELETE              │
│  POST /v1/retrieve   POST /v1/query                              │
│  GET /health  GET /ready  GET /metrics                           │
└───────┬──────────────────────────────┬──────────────────────────┘
        │                              │
        ▼                              ▼
┌───────────────┐              ┌───────────────────┐
│ Celery Worker │              │ Retrieval Pipeline │
│ (ingest/delete)│              │ Dense→Sparse→RRF  │
└───────┬───────┘              │ →Rerank→LLM       │
        │                      └─────────┬─────────┘
        ▼                                │
┌───────────────────────────────────────────────────┐
│                   Storage Layer                    │
│  PostgreSQL (metadata)  │  MinIO/S3 (originals)  │
│  OpenSearch (hybrid index)  │  Redis (cache/queue) │
└───────────────────────────────────────────────────┘
```

### 2.2 기술 스택

| 레이어 | 기술 | 선정 이유 |
|--------|------|-----------|
| API | FastAPI + Uvicorn | async, OpenAPI 자동 생성, 높은 처리량 |
| Queue | Celery + Redis | 검증된 비동기 작업 큐, retry/DLQ 지원 |
| Vector + Sparse | OpenSearch 2.x | BM25 + kNN 단일 클러스터 운영, Nori 한국어 지원 |
| Metadata DB | PostgreSQL 16 | ACID, 문서/청크/잡 상태 관리 |
| Object Storage | MinIO / S3 | 원본 파일 보존, reindex 시 재처리 |
| Embedding | BAAI/bge-m3 | 다국어, 1024-dim, self-host 비용 통제 |
| Reranker | BAAI/bge-reranker-v2-m3 | Cross-encoder, 한영 혼합 문서 강점 |
| LLM | OpenAI-compatible API | 설정으로 provider 교체 가능 |
| Container | Docker Compose (dev), K8s (prod) | 환경 일관성 |

### 2.3 왜 OpenSearch 단일 클러스터인가?

Dense(Qdrant) + Sparse(Elasticsearch) 분리 대비:

- **운영 포인트 1개** — 인덱스 관리, 백업, 모니터링 단순화
- **하이브리드 쿼리** — 동일 문서에 BM25 + kNN 공존
- **한국어 BM25** — Nori analyzer 내장

벡터 QPS > 500/s 또는 billion-scale이 필요해지면 Phase 3에서 Qdrant 분리를 검토한다.

### 2.4 Dual Search Backend (Phase 1.5 — 구현 완료)

동일 RAG 파이프라인(RRF, Rerank, LLM) 위에 검색/인덱스 레이어만 플러그인으로 교체한다.

| Backend | Dense | Sparse | 저장 |
|---------|-------|--------|------|
| `opensearch` | kNN HNSW | BM25 + Nori | OpenSearch |
| `pgvector` | pgvector HNSW | FTS + Kiwi (`kiwipiepy`) | PostgreSQL `chunks` |

전환 방법: `SEARCH_BACKEND` env, API `backend` 필드, `benchmark_retrieval.py --backend`.  
상세: [`SEARCH_BACKENDS.md`](SEARCH_BACKENDS.md)

---

## 3. 인덱싱 파이프라인

### 3.1 흐름

```
Upload → S3 저장 → Celery Job → Parser → Semantic Chunker
       → Embedding (BGE-M3) → Bulk Index (OpenSearch) → PostgreSQL 상태 갱신
```

### 3.2 지원 문서 포맷

| 포맷 | Parser | 비고 |
|------|--------|------|
| PDF | PyMuPDF | 페이지 단위 텍스트 추출 |
| Markdown | MarkdownParser | 헤딩/문단 구조 유지 |
| HTML | BeautifulSoup | script/style 제거 |
| Plain Text | TextParser | fallback |

### 3.3 Chunking 전략

**Semantic Chunker** — 문단/헤딩 경계 우선 분할

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `max_tokens` | 768 | 청크 최대 토큰 |
| `overlap_tokens` | 128 | 청크 간 겹침 (recall 안정화) |
| `min_chunk_tokens` | 64 | 최소 청크 크기 |

**설계 원칙:**
- 고정 길이 분할보다 **의미 단위(문단/문장) 경계** 우선
- overlap으로 경계에 걸린 정보의 recall 손실 방지
- oversized 문단은 문장 → 단어 단위로 재분할

### 3.4 메타데이터 스키마

**PostgreSQL `documents`**

| 필드 | 타입 | 설명 |
|------|------|------|
| id | UUID | 문서 ID |
| tenant_id | string | 멀티테넌시 (optional) |
| filename | string | 원본 파일명 |
| source | string | 출처 식별자 |
| content_hash | SHA256 | 중복/변경 감지 |
| status | enum | pending → processing → completed / failed |
| chunk_count | int | 인덱싱된 청크 수 |

**OpenSearch `rag-chunks` (alias)**

| 필드 | 타입 | 용도 |
|------|------|------|
| chunk_id | keyword | 청크 고유 ID |
| doc_id | keyword | 문서 ID |
| content | text (Nori) | BM25 sparse 검색 |
| embedding | knn_vector (1024) | Dense kNN 검색 |
| page, filename, source | metadata | citation / filter |

### 3.5 Idempotency

- Idempotency key = `{doc_id}:{content_hash}`
- 동일 내용 재업로드 시 중복 인덱싱 방지
- Celery retry: max 3회, exponential backoff

---

## 4. 검색 파이프라인

### 4.1 3단계 검색 + 생성

```
Query
  │
  ├─► [1] Dense kNN ──────► top-50 (BGE-M3 embedding)
  │
  ├─► [2] BM25 Sparse ────► top-50 (Nori + multi_match)
  │
  ├─► [3] RRF Fusion ─────► merged top-50 (k=60)
  │
  ├─► [4] Cross-encoder ──► top-5 (bge-reranker-v2-m3)
  │
  └─► [5] LLM Generate ───► Answer + Citations
```

### 4.2 Dense Retrieval (의미 검색)

- **모델:** BGE-M3, 1024-dim, cosine similarity
- **인덱스:** OpenSearch HNSW (m=16, ef_construction=128, ef_search=100)
- **캐시:** Redis query embedding cache (TTL 1h)
- **적합 쿼리:** 개념/의미 기반 질문, paraphrase, 다국어

### 4.3 Sparse Retrieval (키워드 검색)

- **알고리즘:** BM25 via OpenSearch multi_match
- **Analyzer:** Nori (한국어) + english + standard fields
- **fuzziness:** AUTO (오타 허용)
- **적합 쿼리:** 고유명사, 코드, 숫자, 정확한 용어

### 4.4 RRF Fusion (Reciprocal Rank Fusion)

```
score(chunk) = Σ  1 / (k + rank_i)
               i∈{dense, sparse}
```

- **k = 60** (기본값)
- Dense/Sparse 점수 스케일 불일치에 robust
- 양쪽 모두 상위에 등장하는 청크에 높은 점수

### 4.5 Rerank (Cross-encoder)

- **모델:** bge-reranker-v2-m3
- **입력:** top-50 fused → **출력:** top-5
- **batch_size:** 16 (CPU), GPU 사용 시 확대 가능
- bi-encoder(dense)보다 query-document 쌍 직접 비교 → 정밀도 향상

### 4.6 Generation (LLM)

- **Provider:** OpenAI-compatible API (설정 교체 가능)
- **Context budget:** 4096 tokens
- **Citation format:** `[1]`, `[2]` — context 번호와 매칭
- **System prompt:** context 기반 답변, 정보 부족 시 명시, 질문 언어로 답변

### 4.7 검색 모드

| mode | 동작 | 사용 시점 |
|------|------|-----------|
| `hybrid` | Dense + Sparse + RRF + Rerank | **기본값**, 일반 질의 |
| `dense` | kNN only + Rerank | 의미 검색 디버깅 |
| `sparse` | BM25 only + Rerank | 키워드 검색 디버깅 |

---

## 5. API 설계

### 5.1 Endpoint 목록

| Method | Path | 설명 | Auth |
|--------|------|------|------|
| POST | `/v1/documents` | 문서 업로드 → ingest job | API Key |
| GET | `/v1/documents/{id}` | 문서/인덱싱 상태 조회 | API Key |
| DELETE | `/v1/documents/{id}` | 소프트 삭제 + 인덱스 제거 | API Key |
| POST | `/v1/retrieve` | 검색만 (LLM 없음) | API Key |
| POST | `/v1/query` | Hybrid search + generate | API Key |
| GET | `/health` | Liveness | 없음 |
| GET | `/ready` | Readiness (PG/Redis/OS) | 없음 |
| GET | `/metrics` | Prometheus | 없음 |

### 5.2 Request / Response 예시

**POST /v1/query**

```json
// Request
{
  "query": "하이브리드 검색이란?",
  "tenant_id": "team-a",
  "top_k": 5
}

// Response
{
  "query": "하이브리드 검색이란?",
  "answer": "하이브리드 검색은 Dense(의미)와 Sparse(키워드) 검색을 결합하는 방식입니다 [1][2].",
  "citations": [
    {
      "chunk_id": "uuid",
      "doc_id": "uuid",
      "source": "rag-guide.pdf",
      "filename": "rag-guide.pdf",
      "page": 3,
      "score": 0.92,
      "snippet": "...",
      "rank": 1
    }
  ],
  "latency_ms": {
    "embedding_ms": 45.2,
    "dense_ms": 12.1,
    "sparse_ms": 8.3,
    "fusion_ms": 0.1,
    "rerank_ms": 120.5,
    "total_ms": 186.2
  }
}
```

### 5.3 보안

| 항목 | Phase 1 | Phase 2 |
|------|---------|---------|
| 인증 | X-API-Key | JWT + API Key |
| Rate Limit | Redis sliding window (60 req/min) | per-tenant limit |
| Tenant isolation | tenant_id filter on search | index-level isolation |

---

## 6. 성능 목표

| 지표 | 목표 | 조건 |
|------|------|------|
| Query latency (p95) | < 2s | 10k chunks, CPU reranker |
| Ingest throughput | > 100 docs/hour | worker concurrency=2 |
| Retrieval Recall@5 | ≥ 0.8 | golden eval set |
| API availability | 99.9% | K8s 2+ replicas |
| Index size | ~30GB/shard | OpenSearch shard sizing |

---

## 7. 관측성 (Observability)

### 7.1 Prometheus Metrics

| Metric | Type | Labels |
|--------|------|--------|
| `rag_retrieval_latency_seconds` | Histogram | stage (dense/sparse/fusion/rerank) |
| `rag_llm_latency_seconds` | Histogram | — |
| `rag_ingest_total` | Counter | status (success/failed) |
| `rag_query_total` | Counter | endpoint, status |
| `rag_opensearch_errors_total` | Counter | operation |

### 7.2 Logging

- Structured JSON logging (structlog)
- 필드: timestamp, level, event, doc_id, latency, error

### 7.3 Tracing

- OpenTelemetry FastAPI + httpx instrumentation
- Query pipeline stage별 span

---

## 8. 배포 전략

### 8.1 Development

```bash
docker compose up -d          # 단일 노드 OpenSearch
alembic upgrade head          # DB migration
```

### 8.2 Production (Kubernetes)

```
deploy/k8s/rag.yaml
├── rag-api       Deployment (2 replicas, HPA 2-10)
├── rag-worker    Deployment (2 replicas)
├── opensearch    StatefulSet (3 nodes)
├── postgres      Deployment
└── redis         Deployment
```

### 8.3 Zero-downtime Reindex

1. 새 인덱스 `rag-chunks-v2` 생성
2. Worker로 전체 문서 reindex
3. Alias swap: `rag-chunks` → v2
4. 검증 후 v1 삭제

---

## 9. 로드맵

### Phase 1 — 코어 RAG ✅ (완료)

- [x] Hybrid retrieval (Dense + Sparse + RRF + Rerank)
- [x] FastAPI REST API
- [x] Celery async ingestion
- [x] OpenSearch hybrid index
- [x] Docker Compose + K8s manifests
- [x] Unit tests + eval benchmark
- [x] Prometheus metrics

### Phase 2 — 프로덕션 Hardening

- [ ] JWT 인증 + per-tenant rate limit
- [ ] OpenSearch 3-node cluster 튜닝
- [ ] Reranker GPU/ONNX 배포
- [ ] RAGAS eval CI gate
- [ ] Grafana dashboard

### Phase 3 — 고급 기능

- [ ] Query rewriting (HyDE, multi-query expansion)
- [ ] Parent-child chunking (small chunk 검색 → large context 반환)
- [ ] Freshness boost (time decay)
- [ ] User feedback loop (thumbs up/down)
- [ ] Qdrant 분리 (billion-scale dense)

---

## 10. 평가 (Evaluation)

### 10.1 Retrieval Metrics

| Metric | 설명 |
|--------|------|
| Recall@k | relevant 중 top-k에 포함된 비율 |
| MRR | 첫 relevant의 역순위 평균 |
| nDCG@k | 순위 가중 relevant 점수 |

### 10.2 Generation Metrics (Phase 2 — RAGAS)

| Metric | 설명 |
|--------|------|
| Faithfulness | 답변이 context에 근거하는지 |
| Answer Relevance | 답변이 질문에 적합한지 |
| Context Precision | retrieved context의 정밀도 |

### 10.3 Golden Set

`tests/eval/test_benchmark.py`에 fusion benchmark golden set 포함.  
CI에서 Recall@5, MRR threshold gate.

---

## 11. 리스크 및 완화

| 리스크 | 영향 | 완화 |
|--------|------|------|
| 한국어 BM25 품질 | Sparse recall 저하 | Nori + 도메인 사용자 사전 |
| Reranker latency | p95 초과 | top-k 축소, GPU/ONNX, async endpoint |
| OpenSearch SPOF | 검색 불가 | replica ≥ 1, snapshot backup |
| LLM 비용 | 운영 비용 증가 | retrieve-only endpoint, context budget |
| 모델 cold start | 첫 요청 지연 | model cache volume, warm-up job |

---

## 12. 관련 문서

- [README](../README.md) — Quick Start, API 레퍼런스
- [SEARCH_BACKENDS.md](SEARCH_BACKENDS.md) — OpenSearch ↔ pgvector 전환
- [ARCHITECTURE.md](ARCHITECTURE.md) — 컴포넌트 다이어그램
