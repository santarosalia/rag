# ADR-0005: Celery + Redis 비동기 인제스트

- **상태:** Superseded (2026-09-08) — sync ingest로 전환
- **날짜:** 2026-08-25

## 맥락 (당시)

문서 ingest는 parse → chunk → embed → index로 **수 초~수 분** 걸릴 수 있다.  
API 요청을 동기 blocking하면 timeout·UX 문제가 발생한다.

## 당시 결정

**Celery worker + Redis broker/backend** 로 ingest/delete 작업을 비동기 처리한다.

## 폐기 사유 (현행)

- Parser / TEI가 외부 I/O라 API `await`로도 다른 요청 처리 가능
- Celery worker·`ingest_jobs` 운영 비용 대비 이득이 작음
- 현행: `POST /v1/documents`, `POST /v1/documents/files`에서 **동기 ingest**
- Redis는 쿼리 임베딩 캐시용으로만 유지

대체 문서: [`PARSE_BOUNDARY.md`](../PARSE_BOUNDARY.md)
