# ADR-0008: 파싱 경계와 이중 인제스트 진입점

- **상태:** Superseded (Markdown-only ingest)
- **날짜:** 2026-08-27
- **관련:** [PARSE_BOUNDARY.md](../PARSE_BOUNDARY.md), ADR-0002, ADR-0005

## 맥락

적재(chunk → embed → Kiwi → PG)는 이 저장소에 두고, 원본 → Markdown 파싱만 분리하려 했다.

## 원래 결정 (폐기된 이중 경로)

| 경로 | 입력 | 파싱 |
|------|------|------|
| A | 원본 `POST /v1/documents` | 이 저장소 MarkItDown |
| B | Markdown `POST /v1/documents/parsed` | 외부 |

## 현재 결정

**이 저장소는 파싱하지 않는다.** UTF-8 Markdown만 받는다 (`/documents`, `/documents/parsed`, `/documents/parsed/file`). MarkItDown·Docling·`parse_kind`는 제거됐다. 상세: [`PARSE_BOUNDARY.md`](../PARSE_BOUNDARY.md).
