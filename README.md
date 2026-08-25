# Hybrid RAG — Production-Grade Retrieval-Augmented Generation

Dense + Sparse 하이브리드 검색, Cross-encoder Rerank, 비동기 인덱싱을 갖춘 프로덕션급 RAG 플랫폼입니다.

## Architecture

```
Document Upload → Parser → Semantic Chunker → Embedding + OpenSearch Index
                                                      ↓
Query → Dense kNN + BM25 Sparse → RRF Fusion → Cross-encoder Rerank → LLM → Answer + Citations
```

### Components

| Component | Technology |
|-----------|------------|
| API | FastAPI + Uvicorn |
| Queue | Celery + Redis |
| Vector + Sparse | OpenSearch 2.x (kNN + BM25, Nori analyzer) |
| Metadata | PostgreSQL 16 |
| Object Storage | MinIO (dev) / S3 (prod) |
| Embedding | BGE-M3 (1024-dim) |
| Reranker | bge-reranker-v2-m3 |
| LLM | OpenAI-compatible API |

## Quick Start

### 1. Setup

```bash
cp .env.example .env
# Edit .env — set LLM_API_KEY if using LLM generation

docker compose up -d
```

Wait for all services to be healthy (~2 min for OpenSearch).

### 2. Run Migrations

```bash
docker compose exec api alembic upgrade head
```

### 3. Upload a Document

```bash
curl -X POST http://localhost:8000/v1/documents \
  -H "X-API-Key: dev-api-key-change-me" \
  -F "file=@document.pdf"
```

### 4. Query

```bash
# Retrieval only (no LLM)
curl -X POST http://localhost:8000/v1/retrieve \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"query": "your question", "mode": "hybrid", "rerank": true}'

# Full RAG (retrieve + generate)
curl -X POST http://localhost:8000/v1/query \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"query": "your question"}'
```

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/documents` | POST | Upload document (multipart) |
| `/v1/documents/{id}` | GET | Document status |
| `/v1/documents/{id}` | DELETE | Queue deletion |
| `/v1/retrieve` | POST | Hybrid search + rerank (no LLM) |
| `/v1/query` | POST | Full RAG pipeline |
| `/health` | GET | Liveness probe |
| `/ready` | GET | Readiness probe (checks all deps) |
| `/metrics` | GET | Prometheus metrics |

All `/v1/*` endpoints require `X-API-Key` header.

### Retrieve Modes

- `hybrid` — Dense kNN + BM25 → RRF fusion → rerank (default)
- `dense` — Vector search only
- `sparse` — BM25 keyword search only

## Configuration

Hyperparameters are in [`configs/default.yaml`](configs/default.yaml):

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

Environment variables override model names and connection strings — see [`.env.example`](.env.example).

## Development

```bash
pip install -e ".[dev]"

# Run tests
pytest tests/unit tests/eval -v

# Lint
ruff check src tests scripts

# CLI ingest
python scripts/ingest_cli.py ./documents/

# Benchmark retrieval
python scripts/benchmark_retrieval.py "your query" --iterations 10
```

## Production Deployment (Kubernetes)

Manifests are in [`deploy/k8s/rag.yaml`](deploy/k8s/rag.yaml):

```bash
kubectl apply -f deploy/k8s/rag.yaml
```

Includes:
- API Deployment (2 replicas, HPA 2-10)
- Celery Worker Deployment (2 replicas)
- OpenSearch StatefulSet (3 nodes)
- PostgreSQL, Redis

### Operational Runbook

#### Reindex (zero-downtime)

1. Create new index: `rag-chunks-v2`
2. Bulk reindex all documents via worker
3. Swap alias: `rag-chunks` → `rag-chunks-v2`
4. Delete old index after validation

#### Scale Out

- **API**: HPA scales on CPU (70% target)
- **Worker**: Increase replicas for ingest throughput
- **OpenSearch**: Add data nodes, increase shards (target ~30GB/shard)

#### Monitoring

Prometheus metrics at `/metrics`:
- `rag_retrieval_latency_seconds{stage}` — per-stage latency
- `rag_llm_latency_seconds` — LLM generation time
- `rag_ingest_total{status}` — ingest success/failure count
- `rag_query_total{endpoint,status}` — query count

#### Backup

- **OpenSearch**: Snapshot to S3 repository
- **PostgreSQL**: pg_dump scheduled backup
- **MinIO/S3**: Versioning enabled on document bucket

## Project Structure

```
src/rag/
├── api/           # FastAPI routes, middleware
├── ingestion/     # Parsers, chunker, pipeline
├── retrieval/     # Dense, sparse, RRF, rerank
├── generation/    # LLM, context builder
├── indexing/      # OpenSearch client
├── workers/       # Celery tasks
├── db/            # SQLAlchemy models
└── observability/ # Metrics, logging
```

## License

MIT
