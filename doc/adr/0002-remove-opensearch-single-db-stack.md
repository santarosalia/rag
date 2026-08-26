# ADR-0002: OpenSearch 제거, 단일 DB 스택

- **상태:** Accepted
- **날짜:** 2026-08-26
- **관련:** ADR-0001 (Supersedes dual-backend with OpenSearch)
- **대체:** ADR-0001

## 맥락

Phase 1에서 OpenSearch(BM25+Nori)와 pgvector(Kiwi FTS) **dual backend**를 구현해 A/B 테스트를 수행했다.

벤치마크 결과:
- **품질:** citation 49/50 일치, rerank 이후 사실상 무승부 (동일 embedding + reranker)
- **지연:** dense/sparse sub-stage에서 pgvector 우세, **total retrieve 차이 ~53ms** (rerank ~410ms 지배)
- **LLM 포함 end-to-end:** 23.3s vs 23.1s — 체감 차이 없음

OpenSearch 클러스터는 dev 환경에서 **~512MB+ RAM**, K8s 3-node StatefulSet 운영 부담을 추가한다.

## 결정

**OpenSearch를 완전히 제거**하고 pgvector + Kiwi FTS 단일 스택만 유지한다.

- `opensearch-py`, OpenSearch Docker/K8s 서비스 삭제
- `SearchBackend` → `PgVectorBackend` 단일 구현
- API `backend` 파라미터, `SEARCH_BACKEND` env 제거

## 대안

| 대안 | 기각 이유 |
|------|-----------|
| Dual backend 유지 | 운영·코드 복잡도 대비 이득 없음 |
| OpenSearch only | 인프라 단순성 목표와 상충 |
| Feature flag로 OS 잔류 | dead code·테스트 부담 |

## 결과

### 장점

- docker-compose 서비스 4개 → 3개 (api, worker, postgres, redis, minio)
- 코드베이스 ~850 LOC 감소
- readiness probe·배포·백업 포인트 단순화
- 벤치마크 결론(인프라 선택 기준)과 코드 정합

### 단점

- Nori analyzer 기반 BM25 비교 불가 (Kiwi FTS만)
- billion-scale / 검색 QPS 500+ 시 PG 한계 — Phase 3에서 분리 검토

### 후속 조치

- [x] 기존 OpenSearch 인덱스 → **re-ingest** 필요 (마이그레이션 경로 없음)
- [ ] Phase 3: 필요 시 Qdrant/전용 검색 엔진 분리 ADR 추가
