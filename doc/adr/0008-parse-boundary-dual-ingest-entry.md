# ADR 0008 — 파싱 경계 (Parser Service + ParseResponse)

## Status

Accepted (supersedes Markdown-only dual ingest)

## Context

원본 파싱은 외부 Parser Service에 위임한다. 이 저장소는 적재·검색·생성만 담당한다.

## Decision

- `POST /v1/documents` — 원본 → Parser Service → `documents.parse_json` (JSONB) → Celery 청킹
- `POST /v1/documents/parse/file` — ParseResponse JSON 또는 `ResultItem[]` 직적재
- 청킹은 `results[]` 단위 (`parse_items.py`). Markdown SemanticChunker·S3 문서 저장·`/documents/parsed*` 없음

상세: [`PARSE_BOUNDARY.md`](../PARSE_BOUNDARY.md) · [`CHUNKING.md`](../CHUNKING.md)

## Consequences

- citation에 `page`/`type`/`bbox`를 DB에 보관 가능
- 기존 Markdown 직적재 클라이언트는 `/documents/parse/file`로 마이그레이션 필요
