# 검색 백엔드 비교 및 전환 가이드

이 프로젝트는 **두 가지 검색 백엔드**를 지원하며, 설정 또는 API 파라미터로 번갈아 테스트할 수 있습니다.

## 지원 백엔드

| | **opensearch** (기본) | **pgvector** |
|---|----------------------|--------------|
| Dense | OpenSearch kNN (HNSW) | PostgreSQL pgvector (HNSW) |
| Sparse | BM25 + Nori analyzer | PostgreSQL FTS + **Kiwi** 형태소 |
| 저장소 | OpenSearch 클러스터 | PostgreSQL `chunks` 테이블 |
| 메타데이터 | PostgreSQL | PostgreSQL (동일) |
| 운영 | 검색 엔진 클러스터 | DB 하나로 통합 |

## 전환 방법

### 1. 환경 변수 (서버 기본값)

```bash
# .env
SEARCH_BACKEND=opensearch   # 또는 pgvector
```

`docker compose` 재시작 후 **문서를 re-ingest**해야 합니다. 백엔드마다 인덱스 저장 방식이 다릅니다.

```bash
docker compose restart api worker
python scripts/ingest_cli.py ./documents/
```

### 2. API 요청 단위 (A/B 테스트)

서버 기본값과 무관하게 요청마다 백엔드를 지정할 수 있습니다.

```bash
# OpenSearch
curl -X POST http://localhost:8000/v1/retrieve \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"query": "하이브리드 검색", "backend": "opensearch"}'

# PostgreSQL pgvector + Kiwi FTS
curl -X POST http://localhost:8000/v1/retrieve \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"query": "하이브리드 검색", "backend": "pgvector"}'
```

응답의 `"backend"` 필드로 실제 사용된 백엔드를 확인합니다.

### 3. 벤치마크 CLI

```bash
# OpenSearch
python scripts/benchmark_retrieval.py "질의" --backend opensearch --iterations 10

# pgvector
python scripts/benchmark_retrieval.py "질의" --backend pgvector --iterations 10
```

## pgvector 백엔드 사전 요건

1. **PostgreSQL pgvector 이미지** — `docker-compose.yml`의 `pgvector/pgvector:pg16` 사용
2. **Migration** — pgvector extension 및 컬럼 생성

```bash
docker compose exec api alembic upgrade head
```

3. **Kiwi** — `kiwipiepy` 패키지 (worker/API에 설치됨)

### pgvector 스키마 (chunks 테이블 추가 컬럼)

| 컬럼 | 타입 | 용도 |
|------|------|------|
| `content_morph` | TEXT | Kiwi 형태소 분석 결과 |
| `embedding` | vector(1024) | Dense 검색 |
| `tsv` | tsvector | FTS Sparse 검색 |

## 공정한 비교를 위한 주의사항

1. **동일 문서를 각 백엔드에 인덱싱** — `SEARCH_BACKEND`를 바꾼 뒤 re-ingest
2. **API `backend` 파라미터** — 인덱스는 서버 `SEARCH_BACKEND`로 ingest된 것만 유효  
   (opensearch로 ingest 후 `backend: pgvector` 요청 → pgvector 쪽 인덱스 없음 → 결과 없음)
3. **dual-index** — 두 백엔드 동시 비교하려면 각각 ingest 1회씩 필요 (별도 env 전환)

## 아키텍처 (플러그인)

```
SearchBackend (Protocol)
├── OpenSearchBackend   → opensearch_client.py
└── PgVectorBackend     → pgvector_backend.py + morphology.py (Kiwi)

RetrievalPipeline → get_search_backend() → dense/sparse/RRF/rerank (공통)
```

## 언제 어떤 백엔드를 쓸까

| 상황 | 추천 |
|------|------|
| 대규모, 한국어 BM25(Nori) 품질 중시 | `opensearch` |
| 인프라 단순화, PG만 운영 | `pgvector` |
| 소~중규모, Kiwi FTS 실험 | `pgvector` |
| 두 방식 latency/recall 비교 | benchmark `--backend` |

## 관련 파일

- [`src/rag/indexing/factory.py`](../src/rag/indexing/factory.py) — 백엔드 팩토리
- [`src/rag/indexing/pgvector_backend.py`](../src/rag/indexing/pgvector_backend.py) — PG 구현
- [`src/rag/indexing/morphology.py`](../src/rag/indexing/morphology.py) — Kiwi analyzer
- [`alembic/versions/002_pgvector_fts.py`](../alembic/versions/002_pgvector_fts.py) — migration
