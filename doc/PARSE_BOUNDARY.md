# 파싱 경계 · Parser Service + ParseResponse 적재

> **목적:** 이 저장소는 **적재(chunk → embed → Kiwi → PostgreSQL)와 검색·생성**을 담당한다.  
> 원본 파싱은 외부 **Parser Service** (`PARSE_API_BASE_URL`)에 위임한다.  
> 문서 본문은 S3에 두지 않고 `documents.parse_json`(JSONB)에 저장한다.

---

## 1. 결론

```
원본 PDF/Office
    │
    ▼
POST /v1/documents  ──►  Parser Service POST /parse (서비스 기본 output_format)
    │                         │
    │                         ▼ ParseResponse
    ▼
documents.parse_json → results[] 단위 청킹 → BGE-M3 → Kiwi → PostgreSQL
```

| API | 동작 |
|-----|------|
| `POST /v1/documents` | 원본 → Parser Service → `parse_json` 적재. 응답에 `parse: ParseResponse` |
| `POST /v1/documents/parse/file` | ParseResponse JSON 또는 `ResultItem[]` 직적재 (파서 스킵) |

`group_id` 필수. Markdown 직적재·S3 문서 저장은 없다.

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

---

## 3. 설정

| env | 기본 |
|-----|------|
| `PARSE_API_BASE_URL` | `http://192.168.14.248:17000` |
| `PARSE_API_TIMEOUT_SECONDS` | `300` |

---

## 4. 관련

- Parser Service docs: `http://192.168.14.248:17000/docs`
- [`CHUNKING.md`](CHUNKING.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md)
