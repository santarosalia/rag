# 파싱 경계 · Parser Service + ParseResponse 적재

> **목적:** 이 저장소는 **적재(chunk → embed → Kiwi → PostgreSQL)와 검색·생성**을 담당한다.  
> 원본 파싱은 외부 **Parser Service** (`PARSE_API_BASE_URL`)에 위임한다.  
> 문서 본문은 S3에 두지 않고 `documents.parse_json`(JSONB)에 저장한다.  
> Ingest는 **동기**(요청이 끝날 때까지 chunk/embed/index).

---

## 1. 결론

```
원본 PDF/Office                    이미 DB에 있는 documents 행
    │                                      │
    ▼                                      ▼
POST /v1/documents/files              POST /v1/documents/{id}/index
    │                                      │
    ▼ Parser Service                       │
ParseResponse → documents 행 생성          │
    │                                      │
    └──────────────┬───────────────────────┘
                   ▼ 동기 index (parse_json)
results[] 청킹 → TEI embed → Kiwi → PostgreSQL
```

| API | 동작 |
|-----|------|
| `POST /v1/documents/{id}/index` | `documents.parse_json` 읽어 동기 chunk/embed |
| `POST /v1/documents/files` | 원본 파일 → Parser Service → 행 생성 → 동기 index |

`group_id`는 `/documents/files`에서 필수. Celery / `ingest_jobs` 없음.

---

## 2. ParseResponse (Parser Service 스키마)

모델: [`src/rag/models/parse.py`](../src/rag/models/parse.py)

| 필드 | 타입 | 설명 |
|------|------|------|
| `status` | string | `SUCCESS` / `FAIL` |
| `results` | `ResultItem[]` | 요소별 id, type, markdown, prov |
| `pages` | map → `PageInfo` | 페이지 메타 |
| `processing_time_ms` | number? | |
| `error` | string? | |
| `rendered_document` | string? | 전체 Markdown (청킹에는 사용하지 않음) |

청킹은 **`results[]`만** 사용한다. 상세: [`CHUNKING.md`](CHUNKING.md).

`POST /v1/documents/{id}/index` 예:

```bash
curl -X POST http://localhost:8000/v1/documents/a941cf4c-5025-4e9c-b6d4-7d86bc8d2121/index
```

---

## 3. 설정

| env | 기본 |
|-----|------|
| `PARSE_API_BASE_URL` | `http://192.168.14.248:17000` |
| `PARSE_API_TIMEOUT_SECONDS` | `300` |

---

## 4. 관련

- Parser Service docs: `http://192.168.14.248:17000/docs`
- [`CHUNKING.md`](CHUNKING.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`DOCUOPS_RAG_STRATEGY.md`](DOCUOPS_RAG_STRATEGY.md)
