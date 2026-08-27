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

**메타데이터 유실 방지:** ingest가 `documents` 행과 `chunks` 검색 컬럼(`embedding`, `content_morph`, `tsv`)을 빠짐없이 채워야 citation·그룹 필터·검색이 동작한다.

**중간 포맷:** 외부 ingest는 원본(PDF/DOCX/PPTX 등)을 **[MarkItDown](https://github.com/microsoft/markitdown)으로 Markdown 변환한 뒤** chunking하는 것을 **표준 파이프라인**으로 고정한다. RAG는 변환된 Markdown을 직접 받지 않고, ingest가 적재한 PostgreSQL만 읽는다.

---

## 2. 현재 메타데이터가 흐르는 경로

### 2.1 PostgreSQL `documents` (문서 단위)

| 필드 | 용도 |
|------|------|
| `id` | doc_id — citation, 삭제, 그룹 필터 기준키 |
| `group_id` | 소속 그룹 FK (`groups.id`, **필수**) |
| `filename` | citation 표시 (원본 파일명 또는 논리 경로) |
| `content_type` | MIME (ingest·운영용) |
| `content_hash` | 중복·변경 감지 |
| `s3_key` | 원본 파일 위치 (ingest·reindex 전용) |
| `status` | **`completed`만 검색 대상** |

### 2.2 PostgreSQL `chunks` (청크 단위)

| 필드 | 검색/RAG 사용 |
|------|----------------|
| `id` | chunk_id (citation) |
| `doc_id` | `documents` FK |
| `group_id` | 검색 필터용 복제 (`documents.group_id`) |
| `group_path` | 하위 그룹 포함 검색용 materialized path |
| `content` | rerank, LLM context, snippet |
| `page` | citation (PDF 등) |
| `chunk_index`, `token_count`, `content_hash` | 운영·디버깅 |
| `embedding` | Dense kNN (vector 1024, HNSW) |
| `content_morph` | Kiwi 형태소 분석 결과 |
| `tsv` | Sparse FTS (`to_tsvector('simple', content_morph)`) |

ingest 2단계 적재 (현재 monolith와 동일):

1. `chunks` INSERT — `content`, `page`, `group_id`, `group_path` 등
2. `PgVectorBackend.bulk_index()` — `embedding`, `content_morph`, `tsv` UPDATE

### 2.3 RAG 검색 SQL (citation 메타 출처)

```sql
SELECT
    c.id::text AS chunk_id,
    c.doc_id::text AS doc_id,
    c.content,
    d.filename,
    c.page,
    ...
FROM chunks c
JOIN documents d ON c.doc_id = d.id
WHERE c.embedding IS NOT NULL
  AND d.status = 'completed'
```

→ **`documents`에 `filename`이 없거나 `status != completed`이면 검색·citation에서 제외**된다.

---

## 3. Ingest 분리 시 메타데이터가 유실되는 대표 시나리오

| 시나리오 | 증상 |
|----------|------|
| ingest가 `chunks.content`만 INSERT, `embedding`/`tsv` 미갱신 | dense/sparse 검색 결과 0건 |
| `documents` 행 누락 | JOIN 실패 → 검색 불가 |
| `documents.status`가 `completed`가 아님 | 검색 WHERE 조건에서 제외 |
| `filename`/`page` 누락 | citation 출처 표시 불가 (**핵심 리스크**) |
| Kiwi morph 생략 (`content_morph`, `tsv` 불일치) | 한국어 sparse recall 저하 |
| ingest가 자체 doc_id/chunk_id 체계 사용 | RAG 삭제·추적 불일치 |
| `group_id`/`group_path` 누락 | 그룹 필터 검색 무력화 |

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
- citation 메타의 단일 원천: `documents.filename` + `chunks.page`, `chunks.content`

### 패턴 B — 이벤트 기반

- ingest 완료 이벤트 → indexer worker가 PG에 동일 스키마로 적재
- 이벤트에 `schema_version` 포함 (하위 호환)
- **최종 저장소는 여전히 PostgreSQL** — RAG는 PG만 읽음

---

## 5. MarkItDown 중간 포맷 (표준)

### 5.1 왜 Markdown으로 고정하는가

| 이점 | 설명 |
|------|------|
| **단일 파싱 경로** | ingest 내부에서 PDF/DOCX/PPTX/HTML 등 → MarkItDown → `.md` 한 경로 |
| **LLM/RAG 친화** | 제목·목록·표 구조 유지 → Semantic Chunker 경계 품질 향상 |
| **RAG 단순화** | 본 저장소는 PyMuPDF/BeautifulSoup 등 **포맷 파서 불필요** |
| **포맷 확장** | MarkItDown `[all]` extras로 Office·이미지(OCR) 등 ingest 측에서 흡수 |

MarkItDown은 **고품질 인쇄용 변환**이 아니라 **텍스트 분석·LLM ingest용** 도구임을 전제로 한다.

### 5.2 ingest 파이프라인 (고정)

```
원본 파일 (any)
  → MarkItDown.convert*()
  → Markdown 텍스트 (+ 선택: S3에 {doc_id}.md 저장)
  → Semantic Chunker (헤딩 `#`/`##` 경계 우선)
  → BGE-M3 embed + Kiwi morph
  → PostgreSQL documents/chunks
```

`*` MarkItDown API: 로컬 파일은 `convert_local()`, URL은 `convert()` / `convert_stream()` 등 입력 유형에 맞는 메서드 사용.

RAG 계약 경계는 **PostgreSQL**이다. Markdown 파일/API로 RAG에 직접 넘기지 않는다.

### 5.3 `documents` 메타데이터 규칙 (원본 vs 변환본)

| 필드 | 값 | 비고 |
|------|-----|------|
| `filename` | **원본** 파일명 또는 논리 경로 (`세무조사.pdf`, `업무지침/2024/세무.pdf`) | citation UI용 |
| `content_type` | **원본** MIME (`application/pdf`) | 변환본 MIME 아님 |
| `content_hash` | **원본** 바이트 SHA256 | 중복 업로드 감지 |
| `s3_key` | 원본 객체 키 | 감사·재처리 |
| (선택) `extra_metadata.converted_s3_key` | `{doc_id}.md` | re-chunk·디버깅용 |

변환본 Markdown hash는 `extra_metadata.markdown_hash` 등으로 **선택** 기록 (re-chunk 트리거용).

### 5.4 page(citation) 보존 — **필수 설계 결정**

MarkItDown 기본 출력은 **단일 Markdown 스트림**이라 PDF **페이지 번호가 사라질 수 있다.**

| 전략 | `chunks.page` | 권장 |
|------|---------------|------|
| A. page 포기 | `null` | MD/일반 문서, page citation 불필요 시 |
| B. ingest가 페이지 마커 주입 | MarkItDown 전후 또는 PDF 페이지별 convert 후 `<!-- page: N -->` 삽입 → chunker가 파싱 | **PDF citation 필요 시 권장** |
| C. Azure Document Intelligence (`[az-doc-intel]`) | bbox/page 메타 확보 | 스캔 PDF·복잡 레이아웃 |

**계약:** PDF 등 page citation이 필요한 tenant/문서유형은 ingest가 **B 또는 C**를 적용하고, 불가 시 `page: null`을 명시적으로 허용한다.

### 5.5 Chunking 규칙 (Markdown 입력)

- `#` / `##` / `###` 헤딩 경계 **우선** 분할 (현재 SemanticChunker 문단 경계와 병행)
- 표(table)는 **가능한 한 하나의 chunk에 유지** (행 단위 분할 지양)
- 코드블록·목록은 overlap(`overlap_tokens`)으로 경계 recall 보완

### 5.6 MarkItDown 운영 주의

| 항목 | 내용 |
|------|------|
| 의존성 | `pip install 'markitdown[all]'` 또는 포맷별 extras (`[pdf]`, `[docx]` …) |
| 품질 | 스캔 PDF·한글 복잡 레이아웃 → golden set으로 ingest 품질 gate |
| OCR/이미지 | MarkItDown LLM 연동 시 **ingest 측** 비용·지연 — RAG와 분리 |
| 버전 고정 | ingest `markitdown==x.y.z` pin → 변환 결과 drift 방지 |

### 5.7 품질 검증 (ingest 책임)

- 원본 → MD → chunk 샘플을 ingest golden set에 저장
- RAG `/v1/retrieve` Recall@5는 **최종 chunk 품질**을 반영 — MD 변환 품질 저하는 ingest CI에서 먼저 걸러야 함

---

## 6. Ingest → PostgreSQL 계약

### 6.1 문서 (`documents`)

```json
{
  "doc_id": "uuid",
  "group_id": "uuid",
  "filename": "업무지침/2024/세무조사.pdf",
  "content_type": "application/pdf",
  "content_hash": "sha256...",
  "s3_key": "documents/{doc_id}/세무조사.pdf",
  "status": "completed",
  "chunk_count": 42
}
```

논리 경로가 필요하면 **`filename`에 전체 경로**를 넣거나 `extra_metadata.canonical_path`를 사용한다.

### 6.2 청크 (`chunks`) — 1단계 INSERT

```json
{
  "chunk_id": "uuid",
  "doc_id": "uuid",
  "group_id": "uuid",
  "group_path": "/{root}/{...}/{leaf}",
  "chunk_index": 0,
  "content": "청크 본문",
  "token_count": 412,
  "page": 3,
  "content_hash": "sha256..."
}
```

### 6.3 청크 — 2단계 검색 컬럼 UPDATE (ingest 필수)

ingest는 `PgVectorBackend.bulk_index()`와 동등하게 아래를 수행해야 한다:

| 컬럼 | 값 |
|------|-----|
| `embedding` | BGE-M3 1024-dim vector |
| `content_morph` | Kiwi 형태소 분석(`kiwipiepy`) 결과 |
| `tsv` | `to_tsvector('simple', content_morph)` |

**embedding 모델·차원·Kiwi analyzer는 RAG와 ingest가 동일해야 한다** (ADR-0003: `BAAI/bge-m3`).

### 6.4 `build_index_document()` 페이로드 (monolith 호환)

ingest가 monolith ingest pipeline과 동일 API를 쓸 경우:

```json
{
  "chunk_id": "uuid",
  "doc_id": "uuid",
  "group_id": "uuid",
  "group_path": "/{root}/{...}/{leaf}",
  "content": "청크 본문",
  "embedding": [0.1, "..."],
  "filename": "업무지침/2024/세무조사.pdf",
  "page": 3,
  "chunk_index": 0,
  "token_count": 412,
  "content_hash": "sha256..."
}
```

`filename`은 `documents`에도 기록하고, `bulk_index` 시 `content_morph`/`tsv`/`embedding`만 UPDATE한다.

---

## 7. 이 프로젝트(RAG)에서 제거·유지할 범위

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

## 8. Ingest 분리 체크리스트

- [ ] ingest와 RAG **동일 PostgreSQL** (스키마·migration 공유 또는 ingest가 migration 소유)
- [ ] `documents.status = completed` **후** chunk embedding/tsv UPDATE
- [ ] chunk INSERT → commit → embedding UPDATE 순서 (monolith와 동일)
- [ ] citation 필수: `chunk_id`, `doc_id`, `filename`, `page`(nullable)
- [ ] `group_id`·`group_path` 문서·청크 양쪽 기록
- [ ] 삭제: `documents.status = deleted` + `chunks.embedding/content_morph/tsv = NULL`
- [ ] MarkItDown 변환 + Markdown chunking 파이프라인 golden set CI
- [ ] PDF page citation 필요 시 page 마커 또는 Doc Intelligence 적용
- [ ] integration test: ingest golden doc → RAG `/v1/retrieve` → citation 필드 assert

---

## 9. 확장 메타데이터 (Phase 2+)

부서, 문서유형, effective_date 등 도메인 메타가 필요하면:

1. `documents.extra_metadata JSONB` (ingest가 기록, RAG는 pass-through)
2. 검색 필터용 키만 PG generated column 또는 partial index로 승격
3. contract 문서에 allowed keys 목록 명시

---

## 10. FAQ

**Q. MarkItDown 변환 Markdown을 RAG API로 직접 넘겨도 되나?**  
A. **비권장.** RAG 계약 경계는 PostgreSQL이다. ingest 내부에서 MD → chunk → PG 적재 후 RAG는 PG만 읽는다.

**Q. RAG-only면 S3 원본이 필요한가?**  
A. query/retrieve 런타임에는 **불필요**. reindex·감사는 ingest 책임.

**Q. ingest만 PG 쓰고 RAG는 API로 chunks를 받을 수 있나?**  
A. 현재 RAG는 PG 직접 read. 별도 API 레이어를 두려면 retrieval pipeline 전면 교체 필요 — **비권장**.

**Q. OpenSearch dual-write는?**  
A. ADR-0002로 **제거됨**. re-ingest 없이 OS → PG 마이그레이션 경로 없음.

**Q. page 없는 MD/TXT는?**  
A. `page: null` 허용.

---

## 11. 관련 문서

- [RAG_PLANNING.md](./RAG_PLANNING.md) — 목표·API·로드맵
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 컴포넌트·chunks 스키마
- [adr/0001-postgresql-pgvector-kiwi-hybrid-search.md](./adr/0001-postgresql-pgvector-kiwi-hybrid-search.md)
- [adr/0002-remove-opensearch-single-db-stack.md](./adr/0002-remove-opensearch-single-db-stack.md)
