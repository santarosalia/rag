# Hybrid RAG Platform

**Dense + Sparse 하이브리드 검색**, **Cross-encoder Rerank**, **출처 기반 LLM 답변**을 제공하는 프로덕션급 RAG(Retrieval-Augmented Generation) 플랫폼입니다.

한국어/영어 혼합 문서를 대상으로 **OpenSearch** 또는 **PostgreSQL pgvector+FTS(Kiwi)** 검색 백엔드를 선택할 수 있으며, Celery 비동기 인제스트, Kubernetes 배포를 지원합니다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **Hybrid Search** | Dense kNN(BGE-M3) + Sparse(BM25/Nori 또는 FTS+Kiwi) → RRF 융합 |
| **Dual Search Backend** | `opensearch` ↔ `pgvector` 환경/API 스위치로 A/B 테스트 |
| **Rerank** | Cross-encoder `bge-reranker-v2-m3`로 top-50 → top-5 정밀 재정렬 |
| **Citation** | 모든 답변에 chunk_id, source, page, snippet 포함 |
| **Async Ingest** | PDF / Markdown / HTML / TXT 비동기 인덱싱 (Celery) |
| **Multi-tenant** | `tenant_id` 기반 검색 필터 |
| **Observability** | Prometheus metrics, structured JSON log, OpenTelemetry |

---

## 아키텍처

```
Document Upload → Parser → Semantic Chunker → Embedding + OpenSearch Index
                                                      ↓
Query → Dense kNN + BM25 Sparse → RRF Fusion → Cross-encoder Rerank → LLM → Answer + Citations
```

### 기술 스택

| Component | Technology |
|-----------|------------|
| API | FastAPI + Uvicorn |
| Queue | Celery + Redis |
| Vector + Sparse | OpenSearch 2.x **또는** PG pgvector + FTS (Kiwi) |
| Metadata | PostgreSQL 16 |
| Object Storage | MinIO (dev) / S3 (prod) |
| Embedding | BAAI/bge-m3 (1024-dim) |
| Reranker | BAAI/bge-reranker-v2-m3 |
| LLM | OpenAI-compatible API |

> 상세 기획: [`doc/RAG_PLANNING.md`](doc/RAG_PLANNING.md)  
> 아키텍처 상세: [`doc/ARCHITECTURE.md`](doc/ARCHITECTURE.md)  
> **검색 백엔드 전환:** [`doc/SEARCH_BACKENDS.md`](doc/SEARCH_BACKENDS.md)

---

## 검색 백엔드 선택

| Backend | Dense | Sparse | 적합한 경우 |
|---------|-------|--------|-------------|
| `opensearch` (기본) | kNN HNSW | BM25 + Nori | 대규모, Nori 한국어 품질 |
| `pgvector` | pgvector HNSW | FTS + Kiwi | PG 통합 운영, 인프라 단순화 |

```bash
# .env 기본값 변경
SEARCH_BACKEND=pgvector

# 또는 API 요청마다 지정 (A/B 테스트)
curl -X POST http://localhost:8000/v1/retrieve \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"query": "질의", "backend": "pgvector"}'

# 벤치마크 비교
python scripts/benchmark_retrieval.py "질의" --backend opensearch --iterations 10
python scripts/benchmark_retrieval.py "질의" --backend pgvector --iterations 10
```

백엔드 전환 후 **문서 re-ingest** 필요. 상세: [`doc/SEARCH_BACKENDS.md`](doc/SEARCH_BACKENDS.md)

---

## Quick Start

### 1. 환경 설정

```bash
git clone https://github.com/santarosalia/rag.git
cd rag
cp .env.example .env
# LLM 답변 생성 시: .env 에 LLM_API_KEY 설정
```

### 2. 서비스 기동

```bash
docker compose up -d
```

OpenSearch health check 통과까지 약 1~2분 소요.  
첫 질의 시 BGE-M3 / reranker 모델 다운로드로 추가 시간이 걸릴 수 있습니다.

### 3. DB Migration

```bash
docker compose exec api alembic upgrade head
```

### 4. 문서 업로드

```bash
curl -X POST http://localhost:8000/v1/documents \
  -H "X-API-Key: dev-api-key-change-me" \
  -F "file=@document.pdf"
```

응답 예시:

```json
{
  "doc_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "status": "pending",
  "message": "Document queued for ingestion"
}
```

인덱싱 완료 확인:

```bash
curl http://localhost:8000/v1/documents/{doc_id} \
  -H "X-API-Key: dev-api-key-change-me"
# status: "completed", chunk_count > 0
```

### 5. 질의

```bash
# 검색만 (LLM 없음 — 디버깅/평가용)
curl -X POST http://localhost:8000/v1/retrieve \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "하이브리드 검색이란?",
    "mode": "hybrid",
    "rerank": true
  }'

# 전체 RAG (검색 + LLM 답변 + citations)
curl -X POST http://localhost:8000/v1/query \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"query": "하이브리드 검색이란?"}'
```

---

## API Reference

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/v1/documents` | POST | 문서 업로드 → ingest job enqueue |
| `/v1/documents/{id}` | GET | 문서/인덱싱 상태 조회 |
| `/v1/documents/{id}` | DELETE | 소프트 삭제 + 인덱스 제거 |
| `/v1/retrieve` | POST | Hybrid/dense/sparse 검색 + rerank |
| `/v1/query` | POST | Hybrid search + LLM generate |
| `/health` | GET | Liveness probe |
| `/ready` | GET | Readiness probe (PG/Redis/OpenSearch) |
| `/metrics` | GET | Prometheus metrics |

모든 `/v1/*` 요청에 `X-API-Key` 헤더 필요 (기본값: `dev-api-key-change-me`).

### Retrieve Mode

| mode | 동작 |
|------|------|
| `hybrid` | Dense kNN + BM25 → RRF → rerank **(기본값)** |
| `dense` | Vector 검색 only |
| `sparse` | BM25 키워드 검색 only |

### Request 예시 — POST /v1/retrieve

```json
{
  "query": "검색 질의",
  "mode": "hybrid",
  "tenant_id": "team-a",
  "top_k": 5,
  "rerank": true
}
```

### Response 예시 — POST /v1/query

```json
{
  "query": "하이브리드 검색이란?",
  "answer": "하이브리드 검색은 ... [1][2]",
  "citations": [
    {
      "chunk_id": "...",
      "doc_id": "...",
      "source": "guide.pdf",
      "filename": "guide.pdf",
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

---

## 설정

### 하이퍼파라미터 — [`configs/default.yaml`](configs/default.yaml)

```yaml
chunking:
  max_tokens: 768
  overlap_tokens: 128

retrieval:
  dense_k: 50
  sparse_k: 50
  rrf_k: 60
  rerank_top_n: 5
```

### 환경 변수 — [`.env.example`](.env.example)

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `API_KEY` | API 인증 키 | `dev-api-key-change-me` |
| `LLM_API_KEY` | LLM API 키 | (미설정 시 fallback 답변) |
| `LLM_BASE_URL` | LLM API URL | `https://api.openai.com/v1` |
| `EMBEDDING_MODEL` | Embedding 모델 | `BAAI/bge-m3` |
| `RERANKER_MODEL` | Reranker 모델 | `BAAI/bge-reranker-v2-m3` |
| `SEARCH_BACKEND` | 검색 백엔드 | `opensearch` / `pgvector` |
| `OPENSEARCH_URL` | OpenSearch URL | `http://opensearch:9200` |
| `DATABASE_URL` | PostgreSQL URL | `postgresql+asyncpg://rag:rag@postgres:5432/rag` |

---

## 개발

```bash
pip install -e ".[dev]"

# 테스트 (16개)
pytest tests/unit tests/eval -v

# Lint
ruff check src tests scripts

# CLI 문서 인제스트
python scripts/ingest_cli.py ./documents/

# 검색 latency 벤치마크
python scripts/benchmark_retrieval.py "질의 내용" --iterations 10 --mode hybrid
```

---

## 프로덕션 배포 (Kubernetes)

```bash
kubectl apply -f deploy/k8s/rag.yaml
```

포함 리소스:
- `rag-api` Deployment (2 replicas, HPA 2→10)
- `rag-worker` Deployment (2 replicas)
- `opensearch` StatefulSet (3 nodes)
- `postgres`, `redis`

### 운영 Runbook

#### Zero-downtime Reindex

1. 새 인덱스 `rag-chunks-v2` 생성
2. Worker로 전체 문서 reindex
3. Alias swap: `rag-chunks` → v2
4. 검증 후 v1 삭제

#### Scale Out

| 컴포넌트 | 방법 |
|----------|------|
| API | HPA (CPU 70%) |
| Worker | replica 수 증가 |
| OpenSearch | data node 추가, shard ~30GB 기준 |

#### Monitoring — `/metrics`

| Metric | 설명 |
|--------|------|
| `rag_retrieval_latency_seconds{stage}` | dense/sparse/fusion/rerank 단계별 latency |
| `rag_llm_latency_seconds` | LLM 생성 시간 |
| `rag_ingest_total{status}` | ingest 성공/실패 |
| `rag_query_total{endpoint,status}` | query count |

---

## 프로젝트 구조

```
rag/
├── doc/
│   ├── RAG_PLANNING.md    # RAG 시스템 기획서
│   ├── ARCHITECTURE.md    # 아키텍처 상세
│   └── SEARCH_BACKENDS.md # OpenSearch ↔ pgvector 전환 가이드
├── configs/
│   ├── default.yaml       # 하이퍼파라미터
│   └── opensearch/        # index template
├── src/rag/
│   ├── api/               # FastAPI
│   ├── ingestion/         # parser, chunker, pipeline
│   ├── retrieval/         # dense, sparse, RRF, rerank
│   ├── generation/        # LLM, citation
│   ├── indexing/          # OpenSearch client
│   ├── workers/           # Celery tasks
│   ├── db/                # SQLAlchemy models
│   └── observability/     # metrics, logging, tracing
├── deploy/k8s/            # Kubernetes manifests
├── tests/                 # unit + eval
├── scripts/               # CLI tools
└── docker-compose.yml
```

---

## 로드맵

| Phase | 내용 | 상태 |
|-------|------|------|
| **Phase 1** | Hybrid RAG core, API, Celery, Docker/K8s | ✅ 완료 |
| **Phase 2** | JWT auth, GPU reranker, RAGAS CI gate, Grafana | 🔲 예정 |
| **Phase 3** | HyDE, parent-child chunking, Qdrant 분리 | 🔲 예정 |

---

## License

MIT
