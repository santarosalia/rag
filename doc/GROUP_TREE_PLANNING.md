# 그룹 트리 문서 관리 기획서

> **프로젝트명:** Hybrid RAG Platform  
> **대상:** `tenant_id` 평면 필터 → `groups` 자기참조 트리  
> **버전:** 0.2.0  
> **작성일:** 2026-08-27  
> **상태:** Phase A·B 구현 완료

관련: [`RAG_PLANNING.md`](RAG_PLANNING.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`INGEST_BOUNDARY.md`](INGEST_BOUNDARY.md)

---

## 0. 결론

**가능하며, 현재 아키텍처와 잘 맞는다.**

`tenant_id`는 인증·스키마 격리가 아니라 **문서/청크에 붙는 문자열 필터**다. 검색 백엔드(pgvector)는 `chunks.tenant_id = :id` 한 줄이고, 업로드 API는 Form 필드 하나다. 이 자리를 `group_id` FK + 하위 그룹 포함 조회로 바꾸면 폴더 트리로 문서를 관리할 수 있다.

OpenSearch를 쓰던 시절과 같이 **청크에 필터 키를 복제**하는 패턴을 유지하면 검색 경로를 크게 바꾸지 않아도 된다.

권장 범위:

| 한다 | 하지 않는다 (이번 Phase) |
|------|--------------------------|
| `groups` 자기참조 트리 | 그룹별 다른 임베딩/청킹 파이프라인 |
| 문서는 **하나의 그룹**에만 소속 | 문서 다중 그룹(N:M) |
| 검색 시 하위 포함은 API body로 명시 (`false` 기본) | RLS / schema-per-tenant |
| 기존 `tenant_id` → 루트 그룹으로 이관 | `tenant_id` Form 별칭 유지 |
| 업로드 `group_id` 필수 | 그룹 ACL·멤버십 |

---

## 1. 현황

### 1.1 `tenant_id`가 하는 일

| 위치 | 역할 |
|------|------|
| `documents.tenant_id` | 업로드 시 임의 문자열, FK 없음, nullable |
| `chunks.tenant_id` | 문서 값을 복제해 검색 필터에 사용 |
| `POST /v1/documents` Form | `tenant_id` optional |
| `POST /v1/retrieve`, `/v1/query` | body `tenant_id` — 있으면 **정확 일치**만 |
| pgvector `knn_search` / `bm25_search` | `AND c.tenant_id = :tenant_id` |
| 인덱스 문서 빌더 | 없으면 `"default"` 로 저장 |

생략하면 **전체 문서**가 검색된다. 팀 격리가 아니라 “태그처럼 쓰는 평면 컬렉션”에 가깝다.

### 1.2 한계

- 계층이 없다. `team-a/프로젝트-1`을 문자열로 우회하면 이동·이름 변경·하위 검색이 깨진다.
- 존재하지 않는 ID도 그대로 들어간다 (고아 값).
- 하위 폴더를 포함해 검색할 수 없다.
- 그룹 CRUD·트리 조회 API가 없다.

---

## 2. 목표

조직/폴더 트리를 1급 엔티티로 두고, 문서는 그 트리의 한 노드에 속하게 한다.

```
루트(구 tenant)
 ├── 세무과
 │    ├── 2024 지침
 │    └── 2025 지침
 └── 인사
```

- 업로드: `group_id` **필수** (생략 시 400)
- 검색: 기본은 **해당 그룹에 직접 속한 문서만**. 하위 포함은 body `include_descendants: true`
- 그룹 이동 시 문서 FK는 유지하고, 검색용 경로만 갱신
- 최대 깊이 기본 8, `configs/default.yaml`의 `groups.max_depth`로 변경

### 2.1 성공 기준

| 기준 | 측정 |
|------|------|
| 트리 CRUD | 생성·이름변경·이동·삭제(정책 준수) |
| 순환 없음 | `parent_id` 갱신 시 자기 자손을 부모로 지정 거부 |
| 하위 포함 검색 | body `include_descendants=true` 일 때만 자손 그룹 문서 포함. 기본 `false` |
| 업로드 검증 | `group_id` 없음/잘못된 UUID/없는 그룹 → 400 |
| 기존 데이터 | 기존 `tenant_id` 값이 루트 그룹으로 매핑되어 검색이 동일하게 동작 |
| 깊이 제한 | 생성·이동 시 `depth < groups.max_depth` (기본 8, yaml) |
| 지연 | 그룹 깊이 ≤ max_depth, 자손 ≤ 500 기준 retrieve 필터 오버헤드 p95 +20ms 이내 |

---

## 3. 데이터 모델

### 3.1 `groups` (자기참조)

인접 리스트(`parent_id`)를 원본으로 두고, 검색용으로 **경로를 비정규화**한다.

```
groups
├── id            UUID PK
├── parent_id     UUID NULL  FK → groups.id  ON DELETE RESTRICT
├── name          VARCHAR(256)  NOT NULL
├── slug          VARCHAR(128)  NULL   -- URL/표시용, 트리 내 유일 제약 선택
├── path          VARCHAR(2048) NOT NULL  -- materialized path, 예: /{root}/{...}/{id}
├── depth         INT NOT NULL DEFAULT 0
├── created_at
└── updated_at
```

- 루트: `parent_id IS NULL`, `path = '/{id}'`, `depth = 0`
- 자식: `path = parent.path || '/' || id`, `depth = parent.depth + 1`

**왜 path를 같이 두나:** 매 검색마다 recursive CTE만 쓰면 부하가 커진다. `path LIKE '/root-uuid/%'` 또는 `path LIKE parent.path || '/%'` 로 자손을 한 번에 고른다.

PostgreSQL `ltree`도 가능하나 UUID를 label로 쓰려면 치환이 필요하다. **text path + 인덱스로 충분**하다.

인덱스:

- `ix_groups_parent_id`
- `ix_groups_path` (`text_pattern_ops` — prefix LIKE)
- UNIQUE `(parent_id, name)` — 같은 부모 아래 이름 중복 방지 (`NULL` 루트는 partial unique)

### 3.2 문서·청크

```
documents.group_id  UUID NOT NULL  FK → groups.id
chunks.group_id     UUID NOT NULL  FK → groups.id   -- 검색 필터용 복제
chunks.group_path   VARCHAR(2048) NOT NULL          -- 하위 포함 검색용 복제
```

청크에 `group_id` + `group_path`를 복제하는 이유:

- retrieve는 `chunks`만 본다 (`JOIN documents`는 citation용).
- 그룹 이동 시 문서 1행만 바꾸면 검색이 어긋난다 → **이동 시 해당 문서의 모든 chunk path를 UPDATE**.

기존 `tenant_id` 컬럼은 마이그레이션 후 **폐기** (또는 한 버전 동안 deprecated 컬럼으로 유지).

### 3.3 소속 규칙

| 규칙 | 내용 |
|------|------|
| 소속 | 문서 1건 → 그룹 1개 (N:1) |
| 업로드 시 그룹 | **필수.** 생략·빈 값·존재하지 않는 ID → `400`. 기본 그룹 자동 생성 없음 |
| 그룹에 문서+자식 그룹 동시 | 허용 (폴더에 파일과 하위 폴더가 같이 있는 모델) |

---

## 4. 트리 연산

### 4.1 조회

| 연산 | 방법 |
|------|------|
| 자식만 | `WHERE parent_id = :id` |
| 자손 전체 | `WHERE path LIKE :parent_path || '/%'` |
| 조상 경로 | `path`를 `/`로 split 후 `id = ANY(...)` |
| 트리 JSON | 한 번에 groups 로드 후 메모리에서 조립 (규모가 작음) 또는 recursive CTE |

### 4.2 이동 (`parent_id` 변경)

1. 새 부모가 자기 자신 또는 자손이면 400
2. 새 노드(또는 이동 후 서브트리 최댓값) `depth >= groups.max_depth` 이면 400. 기본값 **8**, `configs/default.yaml`에서 변경
3. 서브트리 모든 노드의 `path`, `depth` 재계산
4. 그 서브트리에 속한 **모든 chunks.group_path** (필요 시 `group_id`는 문서가 붙은 리프만) 갱신  
   - 문서의 `group_id`는 “직접 소속 그룹”이므로 그룹 **이동만** 하면 문서 FK는 그대로, path만 바뀐다.

### 4.3 삭제 정책 (권장: Restrict)

| 상황 | 동작 |
|------|------|
| 자식 그룹 있음 | 409 — 먼저 비우거나 이동 |
| 문서가 직접 붙어 있음 | 409 — 문서 이동/삭제 후 |
| 빈 리프 | DELETE |

대안 `CASCADE`는 문서 대량 삭제와 검색 인덱스 삭제까지 묶어 Celery 작업이 필요하므로 Phase 1에서는 넣지 않는다.

### 4.4 순환 방지

`parent_id` UPDATE 전에:

```sql
-- 새 부모가 현재 노드의 path 접두가 되면 순환
새_부모.path LIKE 현재.path || '/%'  OR  새_부모.id = 현재.id
```

트리거로 강제하는 것을 권장한다.

---

## 5. 검색 연동

현재 retrieve는 `tenant_id` 정확 일치만 지원한다. 그룹으로는 두 모드가 필요하다.

| 모드 | 의미 | SQL (개념) |
|------|------|------------|
| `include_descendants=false` **(기본)** | 이 폴더에 **직접** 올린 문서만 | `c.group_id = :group_id` |
| `include_descendants=true` | 이 폴더와 하위 전부 | `c.group_path = :path OR c.group_path LIKE :path \|\| '/%'` |

기본값은 **하위 미포함**. 자손을 넣으려면 retrieve/query body에 `include_descendants: true`를 보낸다. yaml 기본값으로 바꾸지 않는다.

`group_id` 생략 시 현재와 같이 **전체 검색**.

### 5.1 pgvector

`knn_search` / `bm25_search` 시그니처를 `tenant_id` → `group_id` + `include_descendants` 로 변경.

자손 포함은 **IN 리스트 확장보다 path prefix**가 낫다. 자손 그룹이 수백 개여도 인덱스 prefix 스캔 한 번이다.

HNSW + 추가 WHERE는 후보를 줄이므로, 그룹이 매우 작으면 recall이 떨어질 수 있다. 기존 tenant 필터와 동일한 트레이드오프다.

### 5.2 검색 인덱스 문서 (청크 payload)

`tenant_id` 대신:

```json
{
  "group_id": "...",
  "group_path": "/{root}/{...}/{leaf}"
}
```

OpenSearch를 다시 켤 경우 `group_id` keyword + `group_path` keyword(prefix) 로 동일 의미를 맞춘다.

### 5.3 그룹 이동 후 검색 일관성

그룹 이동은 메타데이터 UPDATE이므로 **재임베딩은 불필요**. `chunks.group_path`만 갱신하면 된다. 트랜잭션으로 groups + chunks를 같이 커밋한다.

---

## 6. API (초안)

Base: `/v1/groups`

| Method | Path | 설명 |
|--------|------|------|
| POST | `/v1/groups` | 생성. body: `name`, `parent_id?` |
| GET | `/v1/groups` | 루트 목록 또는 `parent_id` 자식 |
| GET | `/v1/groups/tree` | 전체 트리 |
| GET | `/v1/groups/{id}` | 단건 + 자식 요약 |
| PATCH | `/v1/groups/{id}` | 이름, `parent_id`(이동) |
| DELETE | `/v1/groups/{id}` | 빈 그룹만 |
| GET | `/v1/groups/{id}/documents` | 직접 소속 문서 목록 |

문서:

| 변경 | 내용 |
|------|------|
| `POST /v1/documents` | Form `tenant_id` **삭제**, `group_id` (UUID) **필수**. 별칭 없음 |
| `GET /v1/documents/{id}` | 응답에 `group_id`, `group_path` |
| `POST /v1/retrieve`, `/v1/query` | body `group_id` (optional, 생략 시 전체), `include_descendants` (bool, **default `false`**) |

목록 API가 없던 문서를 그룹 하위로 보여주는 것은 이번 범위에 넣는 것을 권장한다. 트리만 있고 문서 목록이 없으면 UI를 못 만든다.

---

## 7. 기존 `tenant_id` 마이그레이션

1. `groups` 테이블 생성
2. `INSERT` 기본 루트: id 고정 가능, `name='default'`
3. `documents.tenant_id` distinct 값마다 루트 그룹 생성 (`name = tenant_id`, `parent_id NULL`)
4. `documents.group_id` / `chunks.group_id` / `chunks.group_path` 채움  
   - `tenant_id IS NULL` 인 **기존 행만** `default` 루트에 붙인다 (신규 업로드 생략 허용이 아님)
5. 애플리케이션 배포. Form/JSON 필드명은 `group_id`만
6. `tenant_id` 컬럼 drop (다음 마이그레이션)

검색 호환: 예전 `tenant_id=ga` 질의는 `{"group_id": "<ga 루트 UUID>"}` 와 동치다. 당시 평면 구조라 자손이 없으므로 `include_descendants`와 무관하다.

---

## 8. 영향 범위

| 영역 | 변경 |
|------|------|
| Alembic | `003_groups_tree.py` |
| `db/models.py` | `Group`, Document/Chunk FK |
| ingest `create_document_record` | `group_id` 필수, 청크에 path 복제 |
| `pgvector_backend` | 필터 SQL (`group_id` / path prefix) |
| `indexing/documents.py` | payload 필드 |
| `retrieval/pipeline.py`, `generation/service.py` | `group_id`, `include_descendants` |
| `api/routes.py`, schemas | 그룹 CRUD + Form `group_id` + retrieve body |
| `configs/default.yaml` | `groups.max_depth` |
| `scripts/ingest_cli.py` | `--group-id` (필수) |
| ingest 외부 계약 | `INGEST_BOUNDARY.md`의 `tenant_id`를 `group_id`/`group_path`로 |

임베딩 모델·청커·LLM은 **변경 없음**.

---

## 9. 위험과 제약

| 위험 | 대응 |
|------|------|
| path 갱신 누락 | 트리거: `groups.path` 변경 시 자식·chunks 동기화. 테스트로 이동 후 retrieve 검증 |
| 깊은 트리 + LIKE | `groups.max_depth` (기본 8), path 길이 제한 |
| 루트 과다 | 루트 = 구 tenant. 남용 시 나중에 `org_id` 도입 |
| 검색 시 그룹 생략 | 실수로 전체 코퍼스 검색. 운영 플래그 `REQUIRE_GROUP_FILTER` 검토 |
| 동시 이동 | groups 행 `SELECT FOR UPDATE` |
| API 키만 있는 현재 인증 | 그룹 ACL은 없음. 아는 `group_id`면 검색 가능 (현 tenant와 동일) |

---

## 10. 구현 Phase

### Phase A — 스키마 + 이관 (필수)

- `groups` + 문서/청크 FK·path
- 데이터 마이그레이션
- 업로드/검색이 `group_id`로 동작. 검색 기본은 직접 소속만

### Phase B — 그룹 API + 문서 목록

- CRUD, 트리, 이동, 삭제 정책
- `GET /v1/groups/{id}/documents`

### Phase C — UI 편의 (선택)

- 문서 그룹 이동 API (`PATCH /v1/documents/{id}` `group_id`)
- 그룹 통계 (문서 수, 자손 수)

---

## 11. 비목표

- 문서가 여러 그룹에 동시에 속함 (태그/컬렉션 N:M)
- 그룹 단위 권한(RBAC) — 이후 JWT와 함께
- 그룹마다 다른 검색 백엔드/모델
- schema-per-tenant
- 그룹 삭제 시 문서 일괄 물리 삭제

---

## 12. 확정 결정

| 항목 | 결정 |
|------|------|
| 검색 기본값 | **하위 포함 `false`**. retrieve/query **body** `include_descendants`로만 켠다 |
| 업로드 시 `group_id` 생략 | **거부** (`400`). 기본 그룹 자동 생성 없음 |
| 구 `tenant_id` Form | **삭제.** 필드명을 `group_id`로 교체. 별칭·매핑 없음 |
| 최대 깊이 | **8**, `configs/default.yaml` `groups.max_depth`로 변경 가능 |

설정 예시:

```yaml
groups:
  max_depth: 8
```

생성·이동 시 `parent.depth + 1 >= max_depth` 이면 400. 검색 기본값(`include_descendants`)은 yaml이 아니라 API 스키마 default다.
