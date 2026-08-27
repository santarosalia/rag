# 그룹(평면) 문서 관리 기획서

> **프로젝트명:** Hybrid RAG Platform  
> **대상:** 그룹 트리 → **평면 `groups` + 호출측이 지정하는 문자열 ID**  
> **버전:** 0.3.0  
> **작성일:** 2026-08-27  
> **상태:** 구현 대상 (ADR-0009)

관련: [`RAG_PLANNING.md`](RAG_PLANNING.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`PARSE_BOUNDARY.md`](PARSE_BOUNDARY.md) · [`CHUNKING.md`](CHUNKING.md) · [`ADR-0009`](adr/0009-flat-groups-caller-defined-id.md)

트리 시절 기획은 [`GROUP_TREE_PLANNING.md`](GROUP_TREE_PLANNING.md) (superseded).

---

## 0. 결론

그룹은 **폴더 트리가 아니라 평면 컬렉션**이다. 문서는 그룹 하나에만 속하고, 검색은 `group_id` 정확 일치만 한다.

호출측(다른 서비스·테넌트 코드)이 이미 쓰는 ID를 그대로 쓰게 한다. UUID일 필요는 없다. 예: `ga`, `tax-2024`.

| 한다 | 하지 않는다 |
|------|-------------|
| `groups` 1급 엔티티, 계층 없음 | `parent_id` / `path` / `depth` / 트리 CRUD |
| 생성 시 `id`를 호출측이 지정 (생략 시 UUID 문자열 생성) | 업로드 시 그룹 자동 생성 |
| 업로드 `group_id` 필수, 없는 그룹은 400 | `include_descendants` / `group_path` / 표시용 `name` |
| 빈 그룹만 삭제 (문서 있으면 409) | 문서 N:M 다중 그룹 |

---

## 1. 왜 트리를 접는가

ADR-0007 트리는 폴더 이동·하위 포함 검색을 위해 `path`를 청크에 복제했다. 실제 사용은 예전 `tenant_id`처럼 **평면 필터 + 외부에서 정한 ID**에 가깝다.

- 부모/자식·순환·max_depth·이동 시 path 재기록이 운영 비용만 키운다.
- 외부 시스템이 UUID가 아닌 `ga` 같은 키를 이미 가지고 있다.
- 하위 포함 검색이 없으면 `group_path` 복제는 불필요하다.

---

## 2. ID 규칙

| 항목 | 규칙 |
|------|------|
| 타입 | `VARCHAR(128)` PK |
| 생성 | `POST /v1/groups` body `id` **선택**. 있으면 그 값, 없으면 UUID 문자열 |
| 문자 | `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$` (UUID·`ga`·`tax-2024` 허용) |
| 공백·`/` | 거부 (path param·Form과 충돌) |
| 중복 ID | **409** |
| 업로드/검색 | 같은 문자열을 `group_id`로 사용 |

기존 트리 그룹 UUID는 마이그레이션에서 `id::text`로 남긴다. 새로 `ga`를 쓰려면 그 ID로 그룹을 만든다.

---

## 3. 스키마

```
groups
├── id            VARCHAR(128) PK
├── slug          VARCHAR(128) NULL
├── created_at
└── updated_at

documents.group_id  VARCHAR(128) NOT NULL  FK → groups.id  ON DELETE RESTRICT
chunks.group_id     VARCHAR(128) NOT NULL  FK → groups.id  ON DELETE RESTRICT
```

- `chunks.group_id`는 검색 필터용 복제 (JOIN 없이 WHERE).
- `parent_id`, `path`, `depth`, `chunks.group_path` **삭제**.

---

## 4. API

| Method | Path | 설명 |
|--------|------|------|
| POST | `/v1/groups` | `{ "id"?: "ga" }` — `id` 생략 시 UUID 문자열 |
| GET | `/v1/groups` | 전체 목록 (`id` 정렬) |
| GET | `/v1/groups/{id}` | 단건 |
| DELETE | `/v1/groups/{id}` | 문서 없는 그룹만 |
| GET | `/v1/groups/{id}/documents` | 소속 문서 |

제거: `GET /v1/groups/tree`, `parent_id`, `name`, PATCH, 이동, `include_descendants`.

업로드·검색:

| API | `group_id` |
|-----|------------|
| `POST /v1/documents` Form | 필수. 없는 그룹 → 400 |
| `POST /v1/documents/parsed` | 필수 |
| `POST /v1/documents/parsed/file` | 필수 |
| `GET /v1/documents/{id}` | 응답 `group_id` (path 없음) |
| `POST /v1/retrieve`, `/v1/query` | 선택. 생략 시 전체, 있으면 `c.group_id = :group_id` |

---

## 5. 검색 필터

```sql
AND c.group_id = :group_id
```

`group_id` 생략 시 필터 없음 (전체 코퍼스).

---

## 6. 마이그레이션

- Alembic `006`: 트리 컬럼 drop, id를 `VARCHAR(128)`로 캐스트
- Alembic `007`: `groups.name` drop

다운그레이드 `006`은 비-UUID id가 있으면 실패할 수 있다.

---

## 7. 성공 기준

| 기준 | 측정 |
|------|------|
| 외부 ID | `POST {"id":"ga"}` 후 업로드 `group_id=ga` |
| UUID 생략 | `{}` → 서버가 UUID 문자열 id 부여 |
| 평면 | 부모/트리 필드 없음. retrieve에 descendants 없음 |
| 삭제 | 문서 있으면 409 |
| 검색 | `group_id` 있으면 해당 그룹만, 없으면 전체 |
