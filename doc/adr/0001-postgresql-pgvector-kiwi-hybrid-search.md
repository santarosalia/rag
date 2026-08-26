# ADR-0001: PostgreSQL pgvector + Kiwi FTS 하이브리드 검색

- **상태:** Accepted
- **날짜:** 2026-08-25
- **관련:** ADR-0002

## 맥락

RAG 검색 파이프라인에 **Dense(의미)** 와 **Sparse(키워드)** 검색이 모두 필요하다.

초기 설계 후보:
- **OpenSearch** — BM25(Nori) + kNN 단일 클러스터
- **PostgreSQL pgvector + FTS** — DB 하나에 벡터·키워드 통합
- **Qdrant + Elasticsearch** — 역할 분리 + RRF

팀은 이미 PostgreSQL을 메타데이터 저장소로 사용 중이며, 운영 포인트 최소화와 한국어 sparse 품질을 동시에 만족해야 한다.

## 결정

**PostgreSQL pgvector(HNSW) + tsvector FTS + Kiwi 형태소 분석기**로 하이브리드 검색을 구현한다.

- Dense: `chunks.embedding vector(1024)` + HNSW (`vector_cosine_ops`)
- Sparse: `chunks.tsv` (Kiwi morph → `to_tsvector('simple', ...)`) + `ts_rank`
- 메타데이터·청크·검색 인덱스를 **동일 DB**에서 관리

## 대안

| 대안 | 기각 이유 |
|------|-----------|
| OpenSearch 단일 | 별도 클러스터 운영 부담; 벤치마크상 품질 동점·검색 sub-stage latency 차이 미미 |
| Qdrant + ES | 인프라 2개, dual-write 복잡도 |
| pgvector only (sparse 없음) | 고유명사·코드 recall 저하 |

## 결과

### 장점

- 인프라 단순화 (Postgres + Redis + MinIO)
- 메타·벡터·FTS **단일 트랜잭션** 일관성
- Kiwi로 한국어 sparse 처리
- Alembic migration으로 스키마 버전 관리

### 단점

- OpenSearch Nori 대비 한국어 BM25 튜닝 레퍼런스 적음
- billion-scale / 고QPS 검색 시 PG 단독 한계
- `simple` text search config — 도메인 사전 튜닝 필요

### 후속 조치

- [x] Alembic `002_pgvector_fts` migration
- [x] `pgvector/pgvector:pg16` Docker/K8s 이미지
- [ ] 대규모 시 read replica / 전용 벡터 DB 분리 검토 (Phase 3)
