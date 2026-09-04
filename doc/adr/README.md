# Architecture Decision Records (ADR)

이 디렉터리는 Hybrid RAG 플랫폼의 주요 아키텍처 결정을 기록합니다.

## 형식

[MADR](https://adr.github.io/madr/) 스타일을 따릅니다.

| 필드 | 설명 |
|------|------|
| **상태** | Proposed / Accepted / Deprecated / Superseded |
| **맥락** | 왜 결정이 필요했는지 |
| **결정** | 무엇을 선택했는지 |
| **결과** | 장단점, 후속 조치 |

## 목록

| ADR | 제목 | 상태 |
|-----|------|------|
| [0001](0001-postgresql-pgvector-kiwi-hybrid-search.md) | PostgreSQL pgvector + Kiwi FTS 하이브리드 검색 | Accepted |
| [0002](0002-remove-opensearch-single-db-stack.md) | OpenSearch 제거, 단일 DB 스택 | Accepted |
| [0003](0003-bge-m3-and-bge-reranker-models.md) | BGE-M3 + bge-reranker-v2-m3 모델 선택 | Accepted |
| [0004](0004-rrf-hybrid-fusion.md) | RRF로 Dense/Sparse 결과 융합 | Accepted |
| [0005](0005-celery-redis-async-ingestion.md) | Celery + Redis 비동기 인제스트 | Accepted |
| [0006](0006-openai-compatible-llm-api.md) | OpenAI-compatible LLM API | Accepted |
| [0007](0007-groups-tree-replaces-tenant-id.md) | tenant_id를 그룹 트리로 교체 | Superseded by 0009 |
| [0008](0008-parse-boundary-dual-ingest-entry.md) | 파싱 경계 (Markdown-only로 supersede) | Superseded |
| [0009](0009-flat-groups-caller-defined-id.md) | 평면 그룹 + 호출측 문자열 ID | Accepted |

## 관련 문서

- [RAG 기획서](../RAG_PLANNING.md)
- [아키텍처 상세](../ARCHITECTURE.md)
- [그룹 기획](../GROUP_PLANNING.md)
- [파싱 경계](../PARSE_BOUNDARY.md)
- [청킹 규칙](../CHUNKING.md)
- [parent-child 청킹 기획](../PARENT_CHILD_PLANNING.md)
