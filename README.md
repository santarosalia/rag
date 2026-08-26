# Hybrid RAG Platform

**Dense + Sparse 하이브리드 검색**, **Cross-encoder Rerank**, **출처 기반 LLM 답변**을 제공하는 프로덕션급 RAG 플랫폼입니다.

PostgreSQL **pgvector**(Dense) + **FTS + Kiwi**(Sparse) 단일 DB 검색, Celery 비동기 인제스트, Kubernetes 배포를 지원합니다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **Hybrid Search** | pgvector kNN(BGE-M3) + PostgreSQL FTS(Kiwi) → RRF 융합 |
| **Rerank** | Cross-encoder `bge-reranker-v2-m3` (top-50 → top-5) |
| **Citation** | chunk_id, filename, page, snippet 포함 |
| **Async Ingest** | PDF / MD / HTML / TXT (Celery) |
| **Single DB** | 메타데이터 + 벡터 + FTS 모두 PostgreSQL |
| **Observability** | Prometheus, structlog, OpenTelemetry |

---

## 아키텍처

```
Document Upload → Parser → Chunker → Embedding + Kiwi morph → PostgreSQL (pgvector + tsvector)
                                                                    ↓
Query → Dense kNN + FTS Sparse → RRF → Rerank → LLM → Answer + Citations
```

| Component | Technology |
|-----------|------------|
| API | FastAPI + Uvicorn |
| Queue | Celery + Redis |
| Search | PostgreSQL pgvector + FTS (Kiwi) |
| Object Storage | MinIO / S3 |
| Embedding | BAAI/bge-m3 |
| Reranker | BAAI/bge-reranker-v2-m3 |
| LLM | OpenAI-compatible API |

> [`doc/RAG_PLANNING.md`](doc/RAG_PLANNING.md) · [`doc/ARCHITECTURE.md`](doc/ARCHITECTURE.md) · [`doc/adr/`](doc/adr/)

---

## Quick Start

```bash
cp .env.example .env
docker compose up -d
docker compose exec api alembic upgrade head
```

```bash
# 업로드
curl -X POST http://localhost:8000/v1/documents \
  -H "X-API-Key: dev-api-key-change-me" \
  -F "file=@document.pdf"

# 검색
curl -X POST http://localhost:8000/v1/retrieve \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"query": "질의", "mode": "hybrid"}'

# RAG
curl -X POST http://localhost:8000/v1/query \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"query": "질의"}'
```

---

## API

| Endpoint | 설명 |
|----------|------|
| `POST /v1/documents` | 문서 업로드 |
| `GET /v1/documents/{id}` | 인덱싱 상태 |
| `POST /v1/retrieve` | hybrid/dense/sparse 검색 |
| `POST /v1/query` | 검색 + LLM 답변 |
| `/health`, `/ready`, `/metrics` | 운영 |

응답 `backend` 필드는 항상 `"pgvector"`입니다.

---

## 설정

[`configs/default.yaml`](configs/default.yaml) — chunk size, top_k, RRF k 등  
[`.env.example`](.env.example) — DB, Redis, LLM, 모델

---

## 개발

```bash
pip install -e ".[dev]"
pytest tests/unit tests/eval -v
ruff check src tests scripts
python scripts/benchmark_retrieval.py "질의" --iterations 10
```

---

## K8s

```bash
kubectl apply -f deploy/k8s/rag.yaml
```

Postgres는 `pgvector/pgvector:pg16` 이미지 사용. OpenSearch 클러스터 불필요.

---

## 프로젝트 구조

```
src/rag/
├── api/           # FastAPI
├── ingestion/     # parser, chunker
├── indexing/      # pgvector_backend, Kiwi morphology
├── retrieval/     # RRF, rerank pipeline
├── generation/    # LLM
└── workers/       # Celery
```

---

## License

MIT
