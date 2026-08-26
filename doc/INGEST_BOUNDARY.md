# Ingest / RAG 경계 설계

> **목적:** Ingest를 별도 프로젝트로 분리하고, 이 저장소는 **검색·생성(RAG) 전용**으로 운영할 때의 경계·계약·메타데이터 보존 방안을 정의한다.  
> **전제:** ADR-0002에 따라 검색 스택은 **PostgreSQL pgvector + Kiwi FTS 단일 DB**만 사용한다 (OpenSearch 없음).

---

## 1. 결론 요약

**Ingest 분리는 가능하다.** pgvector 단일 스택에서는 검색·citation이 **항상 PostgreSQL `documents` + `chunks` JOIN**에 의존하므로, 외부 ingest는 **공유 PostgreSQL에 동일 스키마로 기록**하는 것이 필수다.

| 역할 | 담당 |
|------|------|
| **Ingest 프로젝트** | 업로드, 파싱, chunking, BGE-M3 embedding, Kiwi morph, PG 적재, 원본(S3) 보관 |
| **RAG 프로젝트 (본 저장소)** | hybrid retrieve, rerank, LLM generate, citation |

**메타데이터 유실 방지:** ingest가 `documents` 행과 `chunks` 검색 컬럼(`embedding`, `content_morph`, `tsv`)을 빠짐없이 채워야 citation·tenant 필터·검색이 동작한다.

---

## 2. 현재 메타데이터가 흐르는 경로

### 2.1 PostgreSQL `documents` (문서 단위)

| 필드 | 용도 |
|------|------|
| `id` | doc_id — citation, 삭제, tenant 필터 기준키 |
| `tenant_id` | 멀티테넌시 검색 필터 |
| `filename` | citation 표시 |
| `source` | citation 출처 식별자 (기본값: filename) |
| `content_type` | MIME (ingest·운영용) |
| `content_hash` | 중복·변경 감지 |
| `s3_key` | 원본 파일 위치 (ingest·reindex 전용) |
| `status` | **`completed`만 검색 대상** |

### 2.2 PostgreSQL `chunks` (청크 단위)

| 필드 | 검색/RAG 사용 |
|------|----------------|
| `id` | chunk_id (citation) |
| `doc_id` | `documents` FK |
| `tenant_id` | tenant 필터 (청크 레벨 복제) |
| `content` | rerank, LLM context, snippet |
| `page` | citation (PDF 등) |
| `chunk_index`, `token_count`, `content_hash` | 운영·디버깅 |
| `embedding` | Dense kNN (vector 1024, HNSW) |
| `content_morph` | Kiwi 형태소 분석 결과 |
| `tsv` | Sparse FTS (`to_tsvector('simple', content_morph)`) |

ingest 2단계 적재 (현재 monolith와 동일):

1. `chunks` INSERT — `content`, `page`, `tenant_id` 등
2. `PgVectorBackend.bulk_index()` — `embedding`, `content_morph`, `tsv` UPDATE

### 2.3 RAG 검색 SQL (citation 메타 출처)

```sql
SELECT
    c.id::text AS chunk_id,
    c.doc_id::text AS doc_id,
    c.content,
    d.source,
    d.filename,
    c.page,
    ...
FROM chunks c
JOIN documents d ON c.doc_id = d.id
WHERE c.embedding IS NOT NULL
  AND d.status = 'completed'
```

→ **`documents`에 `source`/`filename`이 없거나 `status != completed`이면 검색·citation에서 제외**된다.

---

## 3. Ingest 분리 시 메타데이터가 유실되는 대표 시나리오

| 시나리오 | 증상 |
|----------|------|
| ingest가 `chunks.content`만 INSERT, `embedding`/`tsv` 미갱신 | dense/sparse 검색 결과 0건 |
| `documents` 행 누락 | JOIN 실패 → 검색 불가 |
| `documents.status`가 `completed`가 아님 | 검색 WHERE 조건에서 제외 |
| `source`/`filename`/`page` 누락 | citation 출처 표시 불가 (**핵심 리스크**) |
| Kiwi morph 생략 (`content_morph`, `tsv` 불일치) | 한국어 sparse recall 저하 |
| ingest가 자체 doc_id/chunk_id 체계 사용 | RAG 삭제·추적 불일치 |
| `tenant_id` 누�락 | tenant 격리 검색 무력화 |

---

## 4. 권장 아키텍처

### 패턴 A — 공유 PostgreSQL (권장, 사실상 유일)

```
[Ingest Service]                         [RAG Service]
  parse → chunk → embed → Kiwi morph       retrieve → rerank → LLM
              │                                    │
              └────► PostgreSQL (documents, chunks) ◄──┘
```

- ingest와 RAG가 **동일 PostgreSQL** (또는 ingest write / RAG read replica) 사용
- 별도 검색 엔진·dual-write **불필요**
- citation 메타의 단일 원천: `documents` (`source`, `filename`) + `chunks` (`page`, `content`)

### 패턴 B — 이벤트 기반

- ingest 완료 이벤트 → indexer worker가 PG에 동일 스키마로 적재
- 이벤트에 `schema_version` 포함 (하위 호환)
- **최종 저장소는 여전히 PostgreSQL** — RAG는 PG만 읽음

---

## 5. Ingest → PostgreSQL 계약

### 5.1 문서 (`documents`)

```json
{
  "doc_id": "uuid",
  "tenant_id": "team-a",
  "filename": "세무조사.pdf",
  "source": "업무지침/2024/세무조사.pdf",
  "content_type": "application/pdf",
  "content_hash": "sha256...",
  "s3_key": "documents/{doc_id}/세무조사.pdf",
  "status": "completed",
  "chunk_count": 42
}
```

`source`가 없으면 ingest에서 `filename`으로 fallback (현재 monolith와 동일).

### 5.2 청크 (`chunks`) — 1단계 INSERT

```json
{
  "chunk_id": "uuid",
  "doc_id": "uuid",
  "tenant_id": "team-a",
  "chunk_index": 0,
  "content": "청크 본문",
  "token_count": 412,
  "page": 3,
  "content_hash": "sha256..."
}
```

### 5.3 청크 — 2단계 검색 컬럼 UPDATE (ingest 필수)

ingest는 `PgVectorBackend.bulk_index()`와 동등하게 아래를 수행해야 한다:

| 컬럼 | 값 |
|------|-----|
| `embedding` | BGE-M3 1024-dim vector |
| `content_morph` | Kiwi 형태소 분석(`kiwipiepy`) 결과 |
| `tsv` | `to_tsvector('simple', content_morph)` |

**embedding 모델·차원·Kiwi analyzer는 RAG와 ingest가 동일해야 한다** (ADR-0003: `BAAI/bge-m3`).

### 5.4 `build_index_document()` 페이로드 (monolith 호환)

ingest가 monolith ingest pipeline과 동일 API를 쓸 경우:

```json
{
  "chunk_id": "uuid",
  "doc_id": "uuid",
  "tenant_id": "team-a",
  "content": "청크 본문",
  "embedding": [0.1, "..."],
  "source": "업무지침/2024/세무조사.pdf",
  "filename": "세무조사.pdf",
  "page": 3,
  "chunk_index": 0,
  "token_count": 412,
  "content_hash": "sha256..."
}
```

`source`/`filename`은 `documents`에도 기록하고, `bulk_index` 시 `content_morph`/`tsv`/`embedding`만 UPDATE한다.

---

## 6. 이 프로젝트(RAG)에서 제거·유지할 범위

### Ingest 프로젝트로 이전

| 컴포넌트 | 경로 |
|----------|------|
| Upload API | `POST /v1/documents` |
| Celery ingest/delete worker | `workers/celery_app.py` |
| Parser / Chunker | `ingestion/parsers.py`, `chunker.py`, `pipeline.py` |
| S3 upload | ingest 측 Object Storage |
| IngestJob 상태 관리 | ingest 측 queue/DB |
| Kiwi morph + embedding write | ingest 측 (RAG는 query embedding만) |

### RAG 프로젝트에 유지

| 컴포넌트 | 이유 |
|----------|------|
| `POST /v1/retrieve`, `POST /v1/query` | 핵심 |
| `PgVectorBackend` (kNN + FTS read) | 검색 |
| RetrievalPipeline, Rerank, LLM | 핵심 |
| `documents`/`chunks` **읽기** | JOIN·citation |
| `GET /health`, `GET /ready`, metrics | 운영 |

### 선택적 유지

- `GET /v1/documents/{id}` — ingest가 상태 API를 제공하면 RAG에서 deprecate
- `DELETE /v1/documents/{id}` — ingest가 tombstone + `embedding`/`tsv` NULL 처리 담당

---

## 7. Ingest 분리 체크리스트

- [ ] ingest와 RAG **동일 PostgreSQL** (스키마·migration 공유 또는 ingest가 migration 소유)
- [ ] `documents.status = completed` **후** chunk embedding/tsv UPDATE
- [ ] chunk INSERT → commit → embedding UPDATE 순서 (monolith와 동일)
- [ ] citation 5종 non-empty: `chunk_id`, `doc_id`, `source`, `filename`, `page`(nullable)
- [ ] `tenant_id` 문서·청크 양쪽 기록
- [ ] 삭제: `documents.status = deleted` + `chunks.embedding/content_morph/tsv = NULL`
- [ ] integration test: ingest golden doc → RAG `/v1/retrieve` → citation 필드 assert

---

## 8. 확장 메타데이터 (Phase 2+)

부서, 문서유형, effective_date 등 도메인 메타가 필요하면:

1. `documents.extra_metadata JSONB` (ingest가 기록, RAG는 pass-through)
2. 검색 필터용 키만 PG generated column 또는 partial index로 승격
3. contract 문서에 allowed keys 목록 명시

---

## 9. FAQ

**Q. RAG-only면 S3 원본이 필요한가?**  
A. query/retrieve 런타임에는 **불필요**. reindex·감사는 ingest 책임.

**Q. ingest만 PG 쓰고 RAG는 API로 chunks를 받을 수 있나?**  
A. 현재 RAG는 PG 직접 read. 별도 API 레이어를 두려면 retrieval pipeline 전면 교체 필요 — **비권장**.

**Q. OpenSearch dual-write는?**  
A. ADR-0002로 **제거됨**. re-ingest 없이 OS → PG 마이그레이션 경로 없음.

**Q. page 없는 MD/TXT는?**  
A. `page: null` 허용.

---

## 10. 관련 문서

- [RAG_PLANNING.md](./RAG_PLANNING.md) — 목표·API·로드맵
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 컴포넌트·chunks 스키마
- [adr/0001-postgresql-pgvector-kiwi-hybrid-search.md](./adr/0001-postgresql-pgvector-kiwi-hybrid-search.md)
- [adr/0002-remove-opensearch-single-db-stack.md](./adr/0002-remove-opensearch-single-db-stack.md)
