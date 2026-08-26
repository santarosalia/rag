# Ingest / RAG 경계 설계

> **목적:** Ingest를 별도 프로젝트로 분리하고, 이 저장소는 **검색·생성(RAG) 전용**으로 운영할 때의 경계·계약·메타데이터 보존 방안을 정의한다.

---

## 1. 결론 요약

**Ingest 분리는 가능하고, 일반적인 패턴이다.**  
다만 **메타데이터를 어디에, 어떤 스키마로 쓸지**를 ingest ↔ RAG 사이에 **명시적 계약**으로 고정하지 않으면, 걱정하신 **파일 메타데이터 유실·citation 품질 저하**가 실제로 발생할 수 있다.

| 백엔드 | 검색 시 메타데이터 출처 | Ingest 분리 시 필수 조건 |
|--------|------------------------|--------------------------|
| `opensearch` | 인덱스 문서에 **비정규화** (`source`, `filename`, `page` 등) | 청크 인덱싱 시 citation 필드를 **인덱스에 반드시 포함** |
| `pgvector` | `chunks` + **`documents` JOIN** | ingest가 **공유 PostgreSQL**의 `documents`/`chunks`를 **동일 스키마**로 기록 |

---

## 2. 현재 메타데이터가 흐르는 경로

### 2.1 PostgreSQL `documents` (문서 단위)

| 필드 | 용도 |
|------|------|
| `id` | doc_id — citation, 삭제, tenant 필터의 기준키 |
| `tenant_id` | 멀티테넌시 검색 필터 |
| `filename` | citation 표시, 파서 선택(ingest 측) |
| `source` | citation 출처 식별자 (기본값: filename) |
| `content_type` | MIME (현재 RAG query 경로에서는 미사용) |
| `content_hash` | 중복·변경 감지 (ingest idempotency) |
| `s3_key` | 원본 파일 위치 (ingest·reindex 전용) |
| `status` | `completed`만 pgvector 검색 대상 |

### 2.2 PostgreSQL `chunks` (청크 단위)

| 필드 | 검색/RAG 사용 |
|------|----------------|
| `id` | chunk_id (citation) |
| `doc_id` | 문서 연결 |
| `tenant_id` | tenant 필터 (청크 레벨 복제) |
| `content` | rerank, LLM context, snippet |
| `page` | citation (PDF 등) |
| `chunk_index`, `token_count` | 디버깅·운영 |
| `embedding`, `tsv`, `content_morph` | pgvector dense/sparse (ingest 후 UPDATE) |

### 2.3 OpenSearch 인덱스 (청크 단위, 비정규화)

`build_index_document()`가 ingest 시점에 아래를 **인덱스 문서에 복사**한다.

- `chunk_id`, `doc_id`, `tenant_id`
- `content`, `embedding`
- `source`, `filename`, `page` ← **citation에 직접 사용**
- `chunk_index`, `token_count`, `content_hash`, `created_at`

→ OpenSearch 모드에서는 **query 시 PostgreSQL을 조회하지 않는다.** 인덱스에 없으면 citation에서 빈 값이 된다.

### 2.4 pgvector 검색 SQL

```sql
SELECT c.id, c.doc_id, c.content, d.source, d.filename, c.page, ...
FROM chunks c
JOIN documents d ON c.doc_id = d.id
WHERE d.status = 'completed'
```

→ **`documents` 행이 없거나 `status != completed`이면 검색·citation에서 제외**된다.

---

## 3. Ingest 분리 시 메타데이터가 유실되는 대표 시나리오

| 시나리오 | 증상 | 영향 |
|----------|------|------|
| ingest가 OpenSearch만 쓰고 PG `documents` 미기록 | pgvector 전환·JOIN 실패 | pgvector 사용 불가, citation `source`/`filename` 누락 가능 |
| ingest가 청크 텍스트만 적재, `source`/`filename`/`page` 누락 | citation에 출처 표시 불가 | **사용자가 걱정하는 핵심 리스크** |
| ingest가 자체 doc_id/chunk_id 발급, RAG와 불일치 | 삭제·재색인·추적 불가 | 운영 장애 |
| 확장 메타(부서, 작성일, 태그)를 ingest만 보유 | RAG에서 필터·표시 불가 | 검색 범위·UI 제약 (현재 스키마에도 JSON 메타 필드 없음) |
| ingest가 `tenant_id` 누락 | tenant 격리 검색 무력화 | 보안·데이터 혼선 |

---

## 4. 권장 아키텍처 패턴

### 패턴 A — 공유 PostgreSQL + 검색 인덱스 (권장)

```
[Ingest Service]                    [RAG Service]
  parse/chunk/embed                   retrieve/rerank/LLM
       │                                    │
       ├─► PostgreSQL (documents, chunks) ◄─┤  pgvector: JOIN
       └─► OpenSearch bulk index      ◄─────┘  opensearch: index read
```

- ingest: `documents`/`chunks` INSERT + embedding/tsv 또는 OpenSearch bulk
- RAG: `POST /v1/retrieve`, `POST /v1/query`만 제공
- **메타데이터 단일 원천:** PostgreSQL `documents`
- OpenSearch 사용 시에도 ingest가 **동일 메타를 인덱스에 비정규화** (reindex·백엔드 전환 대비)

### 패턴 B — 검색 인덱스 only (RAG stateless)

- RAG는 OpenSearch(또는 전용 vector DB)만 읽음
- pgvector 백엔드 **사용 불가** (또는 ingest가 PG에도 dual-write)
- citation 필드를 **인덱스 mapping에 고정**하고 ingest contract로 검증

### 패턴 C — 이벤트 기반 (Kafka/SQS)

- ingest 완료 이벤트: `{ doc_id, chunk_id, content, embedding, metadata... }`
- RAG(또는 indexer sidecar)가 이벤트를 소비해 인덱스 적재
- **스키마 버전**(`schema_version`)을 이벤트에 포함해 하위 호환 관리

---

## 5. Ingest → RAG 메타데이터 계약 (필수 필드)

외부 ingest가 **청크 1건**을 적재할 때 RAG citation·필터에 필요한 최소 필드:

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

**문서 단위 (PostgreSQL `documents` — pgvector 또는 운영 조회용):**

```json
{
  "doc_id": "uuid",
  "tenant_id": "team-a",
  "filename": "세무조사.pdf",
  "source": "업무지침/2024/세무조사.pdf",
  "content_type": "application/pdf",
  "content_hash": "sha256...",
  "status": "completed",
  "chunk_count": 42
}
```

### 확장 메타데이터 (선택, Phase 2+)

도메인별 메타(부서, 문서유형, effective_date 등)가 필요하면:

1. **`documents.extra_metadata` JSONB** (단일 원천, ingest가 기록)
2. 검색 필터가 필요한 키만 **인덱스 필드로 승격** (OpenSearch keyword / PG generated column)
3. citation UI용 필드는 retrieve 응답에 **pass-through** (RAG가 해석하지 않고 전달)

→ 스키마 migration 전까지는 ingest contract 문서에 **allowed keys** 목록을 명시한다.

---

## 6. 이 프로젝트(RAG)에서 제거·유지할 범위

### Ingest 프로젝트로 이전

| 컴포넌트 | 경로 |
|----------|------|
| Upload API | `POST /v1/documents` |
| Celery ingest/delete worker | `workers/celery_app.py`, ingest tasks |
| Parser / Chunker | `ingestion/parsers.py`, `chunker.py`, `pipeline.py` |
| S3 upload (원본 보관) | ingest 측 Object Storage |
| IngestJob 상태 관리 | ingest 측 queue/DB |

### RAG 프로젝트에 유지

| 컴포넌트 | 이유 |
|----------|------|
| `POST /v1/retrieve`, `POST /v1/query` | 핵심 |
| RetrievalPipeline, Rerank, LLM | 핵심 |
| SearchBackend (OpenSearch / pgvector) | 검색 |
| `documents`/`chunks` **읽기** (pgvector, 운영) | JOIN·상태 확인 |
| `GET /health`, `GET /ready`, metrics | 운영 |

### 선택적 유지

- `GET /v1/documents/{id}` — ingest 상태 조회 API가 별도면 RAG에서 deprecate 가능
- `DELETE /v1/documents/{id}` — ingest가 tombstone + 인덱스 삭제를 담당하면 RAG에서 제거

---

## 7. 백엔드별 체크리스트

### OpenSearch-only RAG

- [ ] ingest contract: citation 필드 5종 (`chunk_id`, `doc_id`, `source`, `filename`, `page`) 인덱스 포함
- [ ] tenant_id 인덱스 필드 + RAG `tenant_id` 필터 동작 확인
- [ ] 문서 삭제 시 ingest가 `delete_by_doc_id` 호출 또는 동등 API

### pgvector RAG

- [ ] ingest가 **동일 PostgreSQL**에 `documents` + `chunks` 기록
- [ ] `documents.status = completed` 후 embedding/tsv UPDATE
- [ ] chunk_id는 ingest가 생성하거나, RAG가 기대하는 UUID 형식 준수

### Dual backend A/B

- [ ] ingest가 **OpenSearch bulk + PG chunks embedding** dual-write (현재 monolith ingest와 동일)
- [ ] `SEARCH_BACKEND` 전환 시 reindex 주체 명확화 (ingest vs RAG admin job)

---

## 8. FAQ

**Q. RAG만 두면 S3 원본이 없어도 되나?**  
A. query/retrieve만 제공하면 **런타임에 S3 불필요**. reindex·감사 추적은 ingest 측 책임.

**Q. filename만 있고 source가 없으면?**  
A. ingest에서 `source = filename` fallback (현재 monolith와 동일). 둘 다 없으면 citation 품질 저하.

**Q. page가 없는 MD/TXT는?**  
A. `page: null` 허용. citation에서 page 생략.

**Q. 메타데이터 유실을 CI에서 막으려면?**  
A. ingest integration test: golden doc ingest → RAG `/v1/retrieve` → citation 필드 non-empty assert.

---

## 9. 관련 문서

- [RAG_PLANNING.md](./RAG_PLANNING.md) — 목표·API·로드맵
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 컴포넌트·데이터 흐름
- [SEARCH_BACKENDS.md](./SEARCH_BACKENDS.md) — 백엔드 전환
