# RAG 아키텍처 상세

> [RAG 기획서](./RAG_PLANNING.md) · [그룹](./GROUP_PLANNING.md) · [청킹](./CHUNKING.md) · [ADR](./adr/)

## 컴포넌트 다이어그램

```mermaid
flowchart TB
  subgraph client [Client]
    App[Application]
  end

  subgraph api_layer [API Layer]
    FastAPI[FastAPI rag-api]
    Auth[API Key Middleware]
    RateLimit[Rate Limit Redis]
  end

  subgraph ingest [Ingestion]
    Upload[Document Upload]
    MD[MarkItDown / parsed Markdown]
    Chunker[Semantic Chunker]
    EmbedWorker[Embedding BGE-M3]
    MorphWorker[Kiwi Morphology]
    CeleryWorker[Celery Worker]
  end

  subgraph storage [Storage]
    S3[MinIO / S3]
    PG[(PostgreSQL pgvector + FTS)]
    Redis[(Redis)]
  end

  subgraph query [Query Pipeline]
    Dense[Dense kNN top-50]
    Sparse[FTS ts_rank top-50]
    RRF[RRF Fusion k=60]
    Rerank[Cross-encoder top-5]
    LLM[LLM Generate]
  end

  App --> Auth --> RateLimit --> FastAPI
  FastAPI --> Upload
  Upload --> S3
  Upload --> CeleryWorker
  CeleryWorker --> MD --> Chunker --> EmbedWorker
  EmbedWorker --> MorphWorker --> PG

  FastAPI --> Dense
  FastAPI --> Sparse
  Dense --> PG
  Sparse --> PG
  Dense --> RRF
  Sparse --> RRF
  RRF --> Rerank --> LLM
  Rerank --> PG
  Dense --> Redis
```

## 데이터 흐름

### 인덱싱

1. Client → `POST /v1/documents` (multipart file + **필수** `group_id`)
2. API → S3 upload + PostgreSQL document record (status: pending)
3. API → Celery `ingest_document` task enqueue
4. Worker → parse → chunk → embed (BGE-M3) → Kiwi morph
5. Worker → `chunks` 행에 `embedding`, `content_morph`, `tsv` 갱신
6. Worker → PostgreSQL status: completed, chunk_count 갱신

### 질의

1. Client → `POST /v1/query` (query text)
2. API → query embedding (Redis cache check)
3. Parallel: pgvector kNN + FTS (`ts_rank` on `tsv`, Kiwi morph query)
4. RRF fuse → Cross-encoder rerank top-5
5. Build context (4096 token budget) → LLM generate
6. Response: answer + citations[] + latency_ms (`backend: "pgvector"`)

## PostgreSQL `chunks` 스키마

```sql
-- 확장
CREATE EXTENSION IF NOT EXISTS vector;

-- chunks (검색 관련 컬럼)
ALTER TABLE chunks ADD COLUMN content_morph text;
ALTER TABLE chunks ADD COLUMN tsv tsvector;
ALTER TABLE chunks ADD COLUMN embedding vector(1024);

-- 인덱스
CREATE INDEX idx_chunks_embedding_hnsw
  ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_chunks_tsv_gin
  ON chunks USING GIN (tsv);

-- 인덱싱 시 갱신
UPDATE chunks SET
  content_morph = :morph_text,
  embedding     = :embedding_vec,
  tsv           = to_tsvector('simple', :morph_text)
WHERE id = :chunk_id;
```

| 컬럼 | 타입 | 용도 |
|------|------|------|
| `group_id` | varchar(128) | 소속 그룹 복제 (정확 일치 필터) |
| `content` | text | 원문 (citation snippet) |
| `content_morph` | text | Kiwi 형태소 분석 결과 |
| `embedding` | vector(1024) | Dense kNN (cosine, HNSW) |
| `tsv` | tsvector | Sparse FTS (`plainto_tsquery('simple', …)`) |

삭제 시 soft-delete: `embedding`, `content_morph`, `tsv`를 NULL로 초기화.

## 디렉터리 구조

```
src/rag/
├── api/              # FastAPI app, routes, middleware
│   ├── main.py       # lifespan, health/ready/metrics
│   ├── routes.py     # /v1/documents, retrieve, query
│   ├── groups.py     # /v1/groups CRUD
│   └── middleware.py # API key, rate limit
├── groups/
│   ├── filter.py     # retrieve SQL 필터
│   └── service.py    # CRUD, 삭제 정책
├── ingestion/
│   ├── markdown.py   # MarkItDown / 경로 B 패스스루
│   ├── chunker.py    # SemanticChunker (헤딩·표)
│   └── pipeline.py   # IngestionPipeline
├── retrieval/
│   ├── embeddings.py # BGE-M3, reranker, cache
│   ├── fusion.py     # RRF
│   └── pipeline.py   # RetrievalPipeline
├── generation/
│   ├── llm.py        # OpenAI-compatible client
│   └── service.py    # QueryService
├── indexing/
│   ├── pgvector_backend.py  # kNN + FTS
│   ├── morphology.py        # Kiwi analyzer
│   └── factory.py
├── workers/
│   └── celery_app.py
├── db/
│   ├── models.py     # Group, Document, Chunk, IngestJob
│   └── session.py
├── storage/
│   └── s3.py
├── observability/
│   ├── logging.py
│   ├── metrics.py
│   └── tracing.py
└── config.py
```

## 파싱 경계 · 적재는 이 저장소

원본 파싱만 외부로 둘 수 있다. chunk/embed/PG 적재와 retrieve는 여기 남는다 (ADR-0008).

```mermaid
flowchart LR
  subgraph entry [진입점]
    A[POST /v1/documents 원본]
    B[POST /v1/documents/parsed]
  end

  subgraph parse [파싱]
    MD[MarkItDown 이 저장소]
    Ext[외부 파서]
  end

  subgraph load [적재 - 이 저장소]
    Chunk[Chunk + Embed + Kiwi]
  end

  subgraph rag_svc [검색]
    Retrieve[POST /v1/retrieve]
    Query[POST /v1/query]
  end

  PG[(PostgreSQL documents + chunks)]

  A --> MD --> Chunk
  Ext -->|Markdown| B --> Chunk
  Chunk --> PG
  Retrieve --> PG
  Query --> Retrieve
```

- 경로 A: 원본 → MarkItDown → 공통 적재
- 경로 B: 외부 Markdown → 공통 적재 (PG 직접 write 없음)
- 검색: `chunks` JOIN `documents` (`filename`, `page`, `group_id`)

계약: [PARSE_BOUNDARY.md](PARSE_BOUNDARY.md)

## 확장 포인트

| 확장 | 방법 |
|------|------|
| 새 문서 포맷 | 경로 A MarkItDown extras, 또는 경로 B 외부 파서 |
| 새 embedding 모델 | `EMBEDDING_MODEL` env + `vector(N)` dimension 변경 |
| LLM provider 교체 | `LLM_BASE_URL` + `LLM_API_KEY` |
| Tenant 격리 | `group_id` 정확 일치 (현재) → schema-per-tenant (Phase 2) |
| Dense 전용 스토어 | Qdrant 분리 + RRF 유지 (Phase 3) |
