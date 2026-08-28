# Hybrid RAG Platform

**Dense + Sparse 하이브리드 검색**, **Cross-encoder Rerank**, **출처 기반 LLM 답변**을 제공하는 프로덕션급 RAG 플랫폼입니다.

PostgreSQL **pgvector**(Dense) + **FTS + Kiwi**(Sparse) 단일 DB 검색, Celery 비동기 인제스트, Kubernetes 배포를 지원합니다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **Hybrid Search** | pgvector kNN(BGE-M3) + PostgreSQL FTS(Kiwi) → RRF 융합 |
| **Rerank** | Cross-encoder `bge-reranker-v2-m3` (top-50 → top-5) |
| **Citation** | chunk_id, filename, page. `/v1/query`·`/v1/retrieve` body `snippet`/`content`(bool)로 본문 필드 선택. 기본 snippet만 |
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

YAML 문항으로 RAG 답변을 모은 뒤 Faithfulness / Context Recall / Precision을 측정합니다.  
**검색·생성은 Docker API**, **채점(judge)은 호스트에서 `.env`의 LLM**을 씁니다. conda `(base)`에 `pip install` 하지 말고 **uv**로 eval 패키지만 붙입니다.

전제: 스택이 떠 있고 (`http://localhost:7500`), 평가할 `group_id` 코퍼스가 ingest 되어 있다.

```bash
# RAG만 (judge 없음). 리포트는 results/ragas_<이름>_<시각>.json
# --no-project: 이 레포 전체(torch 등)를 sync하지 않음
uv run --no-project --with ragas --with openai --with httpx --with pyyaml \
  python scripts/eval_ragas.py tests/eval/ragas_input --dry-run

# RAGAS 채점까지 (judge LLM 호출)
uv run --no-project --with ragas --with openai --with httpx --with pyyaml \
  python scripts/eval_ragas.py tests/eval/ragas_input
```

데이터셋만 추가할 때는 YAML을 [`tests/eval/ragas_input/`](tests/eval/ragas_input/)에 두면 폴더 실행에 포함됩니다. 템플릿: [`tests/eval/ragas_template.yaml`](tests/eval/ragas_template.yaml).

```bash
cp tests/eval/ragas_template.yaml tests/eval/ragas_input/my_eval.yaml
```

venv를 고정하려면 (프로젝트 `.venv`가 아니라 eval 전용):

```bash
uv venv .venv-eval
uv pip install --python .venv-eval ragas openai httpx pyyaml
.venv-eval/bin/python scripts/eval_ragas.py tests/eval/ragas_input --dry-run
```

`uv run`만 치거나 `uv sync --extra dev`를 하면 `pyproject.toml`의 torch·sentence-transformers까지 받습니다. eval-only에는 `--no-project`를 씁니다.

| | 설명 |
|--|------|
| `--dry-run` | `/v1/query`만 호출. RAGAS 점수 없음 (연결·적재 확인용) |
| 러너 `api` (기본) | `POST http://localhost:7500/v1/query`. 호스트에 `rag` 패키지 불필요 |
| 러너 `direct` | in-process `QueryService`. `pip install -e .` + DB/모델 필요 |
| 리포트 | `--output` 생략 시 `results/ragas_<dataset>_<timestamp>.json`. `traces[]`에 문항별 답변·citation·점수. `ragas.raw[]`에 문항 `id` + 메트릭 |
| judge | `.env`의 `LLM_API_KEY` / `LLM_BASE_URL`. YAML `judge.model`은 **그 엔드포인트에 있는 모델 id**. `judge.max_tokens` 기본 4096 (채점 JSON이 잘리면 올림) |
| `defaults.embeddings` | `answer_relevancy`를 켤 때만 사용. 검색용 BGE-M3와 무관 |

기본 메트릭은 `faithfulness`, `context_recall`, `context_precision` (judge LLM만). `answer_relevancy`는 임베딩 API가 추가로 필요하다.

DocuOps 세무 매뉴얼 세트: [`tests/eval/ragas_input/docuops_tax.yaml`](tests/eval/ragas_input/docuops_tax.yaml) (`group_id=dc`).


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
