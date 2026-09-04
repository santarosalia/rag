# ADR-0007: tenant_id 평면 필터를 그룹 트리로 교체

- **상태:** Superseded
- **날짜:** 2026-08-27
- **관련:** ADR-0002
- **대체:** [ADR-0009](0009-flat-groups-caller-defined-id.md) — 평면 그룹 + 호출측 문자열 ID. 그룹 트리는 채택하지 않음.

## 맥락

`tenant_id`는 인증·스키마 격리가 아니라 문서/청크에 붙는 **임의 문자열 필터**였다.

- 계층이 없어 `팀/프로젝트` 같은 폴더 구조를 표현할 수 없다.
- 존재하지 않는 값도 그대로 들어가 고아 필터가 생긴다.
- 검색은 정확 일치만 가능하고, 하위 폴더를 포함할 수 없다.
- 업로드 Form 생략 시 전체 코퍼스가 검색되어, “기본 테넌트”와 전체 검색이 혼동된다.

문서 관리 UI와 retrieve 범위를 폴더 트리로 맞출 필요가 있다.

## 결정

**자기참조 `groups` 트리**를 1급 엔티티로 두고, 문서는 그룹 하나에만 속하게 한다.

- `groups`: `parent_id` + materialized `path` / `depth`
- `documents.group_id` NOT NULL FK. 업로드 시 생략·없는 ID는 **400**. 기본 그룹 자동 생성 없음
- `chunks.group_id` + `chunks.group_path` 복제 (retrieve는 chunks를 본다)
- 검색: `group_id` 생략 시 전체. `include_descendants` 기본 **false**. true일 때만 path prefix
- 구 `tenant_id` Form 별칭 없음. 기존 값은 마이그레이션에서 루트 그룹으로 이관 후 컬럼 drop
- 최대 깊이 기본 8 (`configs/default.yaml` `groups.max_depth`)
- 삭제: 자식 그룹 또는 직접 소속 문서가 있으면 **409** (RESTRICT)

## 대안

| 대안 | 기각 이유 |
|------|-----------|
| `tenant_id` 문자열에 `/` path 우회 | 이동·이름 변경·하위 검색이 깨짐 |
| 문서 N:M 다중 그룹 | 이번 Phase 범위 초과 (태그/컬렉션) |
| 매 검색 recursive CTE | 자손 필터마다 부하. path prefix + 인덱스로 충분 |
| PostgreSQL `ltree` | UUID를 label로 쓰려면 치환 필요. text path로 충분 |
| 업로드 시 default 그룹 자동 생성 | 실수 업로드가 한 폴더에 몰림. 명시적 `group_id` 강제 |
| 그룹 삭제 CASCADE | 문서·검색 인덱스 대량 삭제와 Celery 작업이 묶임 |

## 결과

### 장점

- 폴더 CRUD·이동·하위 포함 검색이 스키마와 API로 표현됨
- 검색 경로는 기존 pgvector WHERE 한 줄 수준을 유지 (`group_id` 또는 `group_path LIKE`)
- 그룹 이동 시 재임베딩 없이 `path`/`group_path`만 갱신

### 단점

- 그룹 ACL 없음. `group_id`를 알면 검색 가능 (구 tenant와 동일)
- `group_id` 생략 시 전체 코퍼스 검색 — 운영 플래그 `REQUIRE_GROUP_FILTER`는 미도입
- 문서 그룹 이동 API(`PATCH /v1/documents/{id}`)는 Phase C로 미구현

### 후속 조치

- [x] Alembic `003_groups_tree` + 기존 `tenant_id` → 루트 그룹 이관
- [x] 그룹 CRUD / tree / 문서 목록 API
- [ ] 문서 그룹 이동 API, 그룹 통계
- [ ] JWT와 함께 그룹 단위 권한
