# ADR-0008: Parse boundary · dual ingest entry

- **상태:** Accepted (updated 2026-09-08)
- **날짜:** 2026-08

## 결정

- `POST /v1/documents/{id}/index` — 기존 행의 `parse_json`으로 **동기** chunk/embed
- `POST /v1/documents/files` — 원본 → Parser Service → 행 생성 → 동기 index
- 청킹은 `results[]` 단위 (`parse_items.py`). Markdown SemanticChunker·S3·Celery 없음

## 결과

- ParseResponse body 직적재는 제거. 외부에서 `documents` 행을 만든 뒤 `/index`로 적재
- 원본 업로드는 `/v1/documents/files`
