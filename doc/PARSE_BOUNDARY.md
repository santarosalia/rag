# 파싱 경계 · 이중 인제스트 진입점

> **목적:** 이 저장소는 **적재(chunk → embed → Kiwi → PostgreSQL)와 검색·생성**을 담당한다. 바깥으로 빼는 것은 **원본 파싱**뿐이며, 진입점은 두 개다.  
> **전제:** ADR-0002 — 검색 스택은 **PostgreSQL pgvector + Kiwi FTS**. ADR-0008 — 파싱 경계.

**Ingest 전체를 별도 프로젝트로 이전하고 이 저장소는 retrieve/query만 남긴다**는 이전 전제는 **폐기**한다. 구 문서명 `INGEST_BOUNDARY.md`는 이 파일(`PARSE_BOUNDARY.md`)로 대체한다.

---

## 1. 결론

**적재는 여기.** 외부 서비스가 공유 PostgreSQL에 `chunks`를 직접 쓰지 않는다.

합류점(내부 계약)은 **Markdown 텍스트**다. 그 다음부터는 동일 파이프라인이다.

```
                    ┌─ A. 원본 업로드 ──► MarkItDown (이 저장소)
원본 PDF/DOCX/... ──┤
                    └─ B. 외부 파서 ──► Markdown POST ──┐
                                                         ▼
                                              Markdown
                                                         ▼
                                    Semantic Chunker → BGE-M3 → Kiwi
                                                         ▼
                                    PostgreSQL documents + chunks
                                                         ▼
                                    retrieve / query (이 저장소)
```

| 경로 | API | 이 저장소가 하는 일 |
|------|------------|---------------------|
| **A. 원본** | `POST /v1/documents` | 파일 수신 → S3 → **MarkItDown** → 아래와 동일 |
| **B. 파싱본** | `POST /v1/documents/parsed` (JSON) 또는 `/parsed/file` (multipart) | **Markdown** 수신 → S3에 `.md` 보관 → 아래와 동일 |
| **공통 이후** | Celery `ingest_document` | chunk → embed → Kiwi morph → PG 적재 |
| **검색** | `POST /v1/retrieve`, `/v1/query` | 변경 없음 |

`group_id`는 두 업로드 모두 **필수**.

**현재 코드:** `POST /v1/documents`(경로 A, MarkItDown)와 `POST /v1/documents/parsed`(경로 B)가 같은 적재 파이프라인으로 합류한다.

---

## 2. 역할 분담

| 담당 | 하는 일 | 하지 않는 일 |
|------|---------|--------------|
| **외부 파서 (선택)** | 원본 → Markdown (자체 툴·Doc Intelligence·다른 MarkItDown 인스턴스 등) | chunk / embedding / Kiwi / PG write / retrieve |
| **이 저장소** | 원본 경로의 MarkItDown, 두 경로 모두 적재·검색·생성, 원본/변환본 S3, job 상태 | 외부 파서의 포맷별 OCR 파이프라인 운영 |

외부 파서가 보내는 본문은 **MarkItDown 출력과 같은 Markdown**이다. 이미 쪼갠 chunk JSON, embedding 배열은 받지 않는다 — 적재 품질·모델 버전을 이 저장소가 소유한다.

---

## 3. API

둘 다 즉시 `doc_id` / `job_id`를 돌려주고, 적재는 기존처럼 Celery가 수행한다 (ADR-0005).

### 3.1 `POST /v1/documents` — 원본 업로드 (경로 A)

multipart:

| 필드 | 필수 | 설명 |
|------|------|------|
| `file` | yes | 원본 바이트 |
| `group_id` | yes | 소속 그룹 ID (문자열, UUID 아니어도 됨) |

이후: S3 원본 저장 → worker에서 MarkItDown → Markdown → 공통 적재.

`filename` / `content_type`은 **원본** 기준 (citation).

### 3.2 `POST /v1/documents/parsed` — 파싱 결과 수신 (경로 B)

JSON:

```json
{
  "group_id": "ga",
  "filename": "업무지침/2024/세무조사.pdf",
  "content_type": "application/pdf",
  "markdown": "# 제목\n\n본문..."
}
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `group_id` | yes | 소속 그룹 |
| `filename` | yes | citation용 **원본** 파일명 또는 논리 경로 |
| `markdown` | yes | 파싱된 Markdown (빈 문자열 거부) |
| `content_type` | no | 원본 MIME. 없으면 `text/markdown` |

원본 파일은 이 API로 받지 않는다. 재파싱이 필요하면 경로 A로 다시 올린다.

### 3.3 `POST /v1/documents/parsed/file` — 파싱된 Markdown 파일 (경로 B)

JSON 대신 `.md` 바이너리를 보낼 때 쓴다. MarkItDown은 타지 않는다. `POST /v1/documents`에 `.md`를 올리면 경로 A다.

multipart:

| 필드 | 필수 | 설명 |
|------|------|------|
| `file` | yes | UTF-8 Markdown 바이트 |
| `group_id` | yes | 소속 그룹 |
| `filename` | no | citation용 이름. 없으면 업로드 파일명 |

이후 적재는 JSON 경로 B와 같다.

---

## 4. 공통 적재 파이프라인 (Markdown 이후)

```
Markdown
  → Semantic Chunker (ATX 헤딩·atomic 표/펜스 경계 우선)
  → BGE-M3 embed + Kiwi morph
  → chunks INSERT (content, group_id, …)
  → commit
  → embedding / content_morph / tsv UPDATE
  → documents.status = completed
```

검색·citation은 항상 `chunks` JOIN `documents`다. `status != completed` 또는 `embedding` NULL이면 안 나온다.

### 4.1 `documents`

| 필드 | 용도 |
|------|------|
| `id` | doc_id |
| `group_id` | 소속 그룹 FK (**필수**) |
| `filename` | citation (원본 파일명/논리 경로) |
| `content_type` | 원본 MIME |
| `s3_key` | 경로 A: 원본. 경로 B: 변환 Markdown (`.md`) |
| `parse_kind` | `original` (경로 A) / `markdown` (경로 B) |
| `status` | **`completed`만 검색 대상** |

### 4.2 `chunks`

| 필드 | 검색/RAG |
|------|----------|
| `id` / `doc_id` | citation, 삭제 |
| `group_id` | 그룹 필터 |
| `content` | rerank, LLM, snippet |
| `embedding` | Dense kNN |
| `content_morph` / `tsv` | Sparse FTS |

### 4.3 검색 SQL (citation 출처)

```sql
SELECT
    c.id::text AS chunk_id,
    c.doc_id::text AS doc_id,
    c.content,
    d.filename,
    ...
FROM chunks c
JOIN documents d ON c.doc_id = d.id
WHERE c.embedding IS NOT NULL
  AND d.status = 'completed'
```

---

## 5. MarkItDown (경로 A 표준 파서)

경로 A는 원본을 **[MarkItDown](https://github.com/microsoft/markitdown)** 으로 Markdown 변환한다. 경로 B의 `markdown`도 같은 중간 포맷으로 취급한다.

| 이점 | 설명 |
|------|------|
| 단일 적재 입력 | PDF/DOCX/PPTX/HTML → MD 한 종류만 chunker가 본다 |
| LLM/RAG 친화 | 제목·목록·표가 Semantic Chunker 경계에 유리 |
| 포맷 확장 | extras는 경로 A 또는 **외부 파서**가 흡수. 이 저장소 chunker는 MD만 |

MarkItDown은 인쇄용 변환기가 아니라 **텍스트 분석·LLM ingest용**이다.

```
원본 → MarkItDown.convert*() → Markdown → (공통 적재)
```

### 5.1 Chunking (Markdown)

헤딩(ATX `#`–`######`)·파이프 표·코드 펜스·HTML 표 경계 우선. 규칙 전부: [`CHUNKING.md`](CHUNKING.md).

### 5.2 운영

| 항목 | 내용 |
|------|------|
| 의존성 | `markitdown` extras (`[pdf]`, `[docx]`, …) — 경로 A |
| 버전 pin | 경로 A drift 방지. 경로 B는 외부 파서 버전을 호출측이 관리 |
| OCR/이미지 | 무거운 LLM/OCR은 **외부 파서(경로 B)** 쪽. 이 저장소 MarkItDown은 가벼운 변환 |

---

## 6. 메타가 빠지면

적재를 여기서 하므로 “다른 서비스가 embedding을 안 씀” 부류는 줄어든다. 남은 리스크:

| 시나리오 | 증상 |
|----------|------|
| `/parsed`에 `filename` 없음 | citation 출처 부실 |
| `group_id` 없음/없는 그룹 | 400 |
| 빈 markdown | 400 |
| worker가 embed/`tsv` 갱신 전 실패 | `status=failed`, 검색 0건 |

---

## 7. 이 저장소 범위

### 유지·강화

| 컴포넌트 | 역할 |
|----------|------|
| `POST /v1/documents` | 경로 A (MarkItDown으로 교체) |
| `POST /v1/documents/parsed` | 경로 B (신규) |
| Celery ingest/delete | 공통 적재·삭제 |
| Chunker, embedding, Kiwi, PG write | 적재 |
| S3 | 경로 A 원본, 선택적으로 경로 B `.md` |
| retrieve / query | 검색·생성 |
| `GET`/`DELETE /v1/documents/{id}` | 상태·소프트 삭제 |

### 밖으로

- 도메인 특화 파서, 스캔 PDF OCR, 대용량 Office 변환 팜 — **경로 B를 호출하는 쪽**

---

## 8. 체크리스트 (구현 시)

- [x] 경로 A: `parsers.py` → MarkItDown, 이후 기존 chunk/embed와 연결
- [x] 경로 B: `POST /v1/documents/parsed` JSON, `POST /v1/documents/parsed/file` 파일
- [x] 두 경로 모두 동일 Celery 적재, `group_id` 기록
- [x] `documents.status = completed` 후에만 검색
- [x] chunk INSERT → commit → embedding/`tsv` UPDATE 순서 유지
- [x] citation: `chunk_id`, `doc_id`, `filename`
- [x] 삭제: `status=deleted` + 검색 컬럼 NULL
- [ ] golden set: 원본→MD(경로 A) / 외부 MD(경로 B) → retrieve citation assert

---

## 9. 확장 메타데이터 (Phase 2+)

부서, 문서유형, effective_date:

1. `documents.extra_metadata JSONB`
2. 검색 필터 키만 generated column / partial index
3. `/parsed` body에 허용 키만 받기

---

## 10. FAQ

**Q. 외부에서 chunk나 embedding까지 해서 PG에 직접 쓰면 안 되나?**  
A. **하지 않는다.** 모델·Kiwi·스키마 버전이 갈라진다. 바깥 경계는 Markdown.

**Q. 경로 B Markdown을 retrieve에 바로 넣나?**  
A. **아니다.** 반드시 적재 파이프라인을 탄다. 검색 계약은 PostgreSQL.

**Q. 경로 B에 원본 PDF도 같이 올리나?**  
A. 초안은 Markdown만. 원본 보관이 필요하면 경로 A 또는 이후 multipart 확장.

**Q. OpenSearch dual-write는?**  
A. ADR-0002로 제거. 없음.

---

## 11. 관련 문서

- [ADR-0008](./adr/0008-parse-boundary-dual-ingest-entry.md) — 이 결정
- [RAG_PLANNING.md](./RAG_PLANNING.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [CHUNKING.md](./CHUNKING.md) — Markdown 청킹 규칙
- [adr/0002](./adr/0002-remove-opensearch-single-db-stack.md) · [adr/0005](./adr/0005-celery-redis-async-ingestion.md)
