# 파싱 경계 · Parser Service + Markdown 적재

> **목적:** 이 저장소는 **적재(chunk → embed → Kiwi → PostgreSQL)와 검색·생성**을 담당한다.  
> 원본 파싱은 외부 **Parser Service** (`PARSE_API_BASE_URL`, 기본 `http://192.168.14.248:17000`)에 위임한다.

---

## 1. 결론

```
원본 PDF/Office
    │
    ▼
POST /v1/documents  ──►  Parser Service POST /parse?output_format=markdown
    │                         │
    │                         ▼ ParseResponse
    │                    rendered_document / results[].markdown
    ▼
S3 content.md → Semantic Chunker → BGE-M3 → Kiwi → PostgreSQL
```

| API | 동작 |
|-----|------|
| `POST /v1/documents` | 원본 → Parser Service → Markdown 적재. 응답에 `parse: ParseResponse` |
| `POST /v1/documents/parsed` | Markdown JSON 직적재 (파서 스킵) |
| `POST /v1/documents/parsed/file` | Markdown 파일 직적재 (파서 스킵) |

`group_id` 필수. chunk/embedding 직접 수신은 하지 않는다.

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
| `rendered_document` | string? | `output_format=markdown`일 때 전체 Markdown |

Markdown 추출: `rendered_document` 우선, 없으면 `results[].markdown` 결합.

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
