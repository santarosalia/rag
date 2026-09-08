# ADR-0008: Parse boundary · dual ingest entry

- **상태:** Accepted (updated 2026-09-08)
- **날짜:** 2026-08

## 결정

- `POST /v1/documents` — ParseResponse JSON 또는 `ResultItem[]` → **동기** ingest (`parse_json`)
- `POST /v1/documents/files` — 원본 → Parser Service → 동기 ingest
- 청킹은 `results[]` 단위 (`parse_items.py`). Markdown SemanticChunker·S3·Celery 없음

## 결과

- 기존 `/v1/documents/parse/file` 클라이언트는 `/v1/documents`로 이전
- 기존 원본 업로드(`/v1/documents` multipart)는 `/v1/documents/files`로 이전
