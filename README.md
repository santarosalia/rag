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
| **Groups** | 평면 문서 그룹. 생성 시 외부 문자열 ID 지정 가능 |
| **Async Ingest** | 원본(MarkItDown) 또는 파싱 Markdown → chunk/embed (Celery) |
| **Single DB** | 메타데이터 + 벡터 + FTS 모두 PostgreSQL |
| **Observability** | Prometheus, structlog, OpenTelemetry |

---

## 아키텍처

```
Document Upload → MarkItDown (or parsed Markdown) → Chunker → Embedding + Kiwi morph → PostgreSQL (pgvector + tsvector)
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

> [`doc/RAG_PLANNING.md`](doc/RAG_PLANNING.md) · [`doc/ARCHITECTURE.md`](doc/ARCHITECTURE.md) · [`doc/GROUP_PLANNING.md`](doc/GROUP_PLANNING.md) · [`doc/adr/`](doc/adr/) · [`doc/PARSE_BOUNDARY.md`](doc/PARSE_BOUNDARY.md) · [`doc/CHUNKING.md`](doc/CHUNKING.md)

---

## Quick Start

```bash
cp .env.example .env
docker compose up -d
docker compose exec api alembic upgrade head
```

```bash
# 그룹 생성 (id는 호출측이 지정, UUID 아니어도 됨)
curl -X POST http://localhost:8000/v1/groups \
  -H "Content-Type: application/json" \
  -d '{"id": "ga"}'

# 업로드 (group_id 필수) — 경로 A
curl -X POST http://localhost:8000/v1/documents \
  -F "file=@document.pdf" \
  -F "group_id=ga"

# 파싱된 Markdown JSON — 경로 B
curl -X POST http://localhost:8000/v1/documents/parsed \
  -H "Content-Type: application/json" \
  -d '{"group_id": "ga", "filename": "document.pdf", "markdown": "# 제목\n\n본문"}'

# 파싱된 Markdown 파일 — 경로 B
curl -X POST http://localhost:8000/v1/documents/parsed/file \
  -F "file=@document.md" \
  -F "group_id=ga"

# 검색 (group_id 생략 시 전체)
curl -X POST http://localhost:8000/v1/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "질의", "mode": "hybrid", "group_id": "ga"}'

# RAG
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "질의"}'
```

---

## API

| Endpoint | 설명 |
|----------|------|
| `POST /v1/groups` | 그룹 생성 (`id` 선택) |
| `GET /v1/groups` | 목록 |
| `GET /v1/groups/{id}` | 단건 |
| `DELETE /v1/groups/{id}` | 빈 그룹만 삭제 |
| `GET /v1/groups/{id}/documents` | 소속 문서 |
| `POST /v1/documents` | 원본 업로드 (`group_id` 필수) → MarkItDown → 적재 |
| `POST /v1/documents/parsed` | 파싱된 Markdown JSON 수신 후 동일 적재 |
| `POST /v1/documents/parsed/file` | 파싱된 Markdown 파일 수신 후 동일 적재 |
| `GET /v1/documents/{id}` | 인덱싱 상태 (`group_id`) |
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
```

### 검색 속도 벤치마크

```bash
python scripts/benchmark_retrieval.py "질의" --iterations 10
```

`POST /v1/retrieve` latency Mean/P50/P95를 출력합니다.

### RAGAS 품질 평가

end-to-end 답변 품질(Faithfulness, Context Recall/Precision 등)을 YAML 데이터셋으로 측정합니다.

```bash
# 템플릿 복사 후 question / ground_truth 수정
cp tests/eval/ragas_template.yaml tests/eval/ragas_input/my_eval.yaml

# RAG만 확인 (judge LLM 비용 없음). 리포트는 results/ragas_<이름>_<시각>.json
rag-eval tests/eval/ragas_input/docuops_tax.yaml --dry-run

# ragas_input 폴더의 YAML 전부
rag-eval tests/eval/ragas_input --dry-run

# RAGAS 전체 (스택 + LLM_API_KEY 필요, group_id 코퍼스 ingest 선행)
rag-eval tests/eval/ragas_input/docuops_tax.yaml

# 호스트에서 패키지 설치 후 in-process 호출 (청크 전문 → faithfulness에 유리)
rag-eval tests/eval/ragas_input/docuops_tax.yaml --runner direct
```

| 옵션 | 설명 |
|------|------|
| `defaults.runner: api` | `/v1/query` HTTP (기본). `api_url` 기본 `http://localhost:7500` |
| `defaults.runner: direct` | in-process `QueryService`, chunk **전문** (`pip install -e .`) |
| `defaults.metrics` | `faithfulness`, `context_recall`, `context_precision`, `answer_relevancy` |
| `defaults.thresholds` | 미달 시 exit code 1 |
| `--output` | JSON 경로. 생략 시 `results/ragas_<dataset>_<timestamp>.json` |

템플릿: [`tests/eval/ragas_template.yaml`](tests/eval/ragas_template.yaml) · 입력 폴더: [`tests/eval/ragas_input/`](tests/eval/ragas_input/)

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
├── api/           # FastAPI (documents, groups, retrieve/query)
├── groups/        # 평면 그룹 CRUD, 검색 필터
├── ingestion/     # markdown (MarkItDown), chunker
├── indexing/      # pgvector_backend, Kiwi morphology
├── retrieval/     # RRF, rerank pipeline
├── generation/    # LLM
└── workers/       # Celery
```

---

## License

MIT
