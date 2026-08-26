# ADR-0005: Celery + Redis 비동기 인제스트

- **상태:** Accepted
- **날짜:** 2026-08-25

## 맥락

문서 ingest는 parse → chunk → embed → index로 **수 초~수 분** 걸릴 수 있다.  
API 요청을 동기 blocking하면 timeout·UX 문제가 발생한다.

요구사항:
- 대량 PDF/Office 업로드
- idempotent re-ingest
- retry on failure
- API는 즉시 job_id 반환

## 결정

**Celery worker + Redis broker/backend** 로 ingest/delete 작업을 비동기 처리한다.

| Task | 설명 |
|------|------|
| `rag.ingest_document` | parse → chunk → embed → pgvector index |
| `rag.delete_document` | S3 + chunks index clear + soft delete |
| `rag.reindex_document` | ingest 재실행 |

- Idempotency key: `{doc_id}:{content_hash}`
- max_retries: 3, exponential backoff

## 대안

| 대안 | 기각 이유 |
|------|-----------|
| FastAPI BackgroundTasks | 프로세스 재시작 시 유실, scale-out 어려움 |
| ARQ / Dramatiq | Celery 생태계·레퍼런스 풍부한 Celery 선택 |
| Kafka | 현재 규모에 과잉 |
| Sync ingest | 대용량 PDF timeout |

## 결과

### 장점

- API/worker 분리 → 독립 scale-out
- Redis embedding cache와 broker 공유
- job 상태 PostgreSQL `ingest_jobs` 추적

### 단점

- Redis 추가 의존성
- Celery worker에 embedding/rerank 모델 로드 → 메모리 heavy
- at-least-once → idempotency 필수

### 후속 조치

- [ ] ingest queue depth metric → HPA 연동 (Phase 2)
- [ ] dead letter queue formalization
