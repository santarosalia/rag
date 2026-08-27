# ADR-0009: 그룹을 평면 구조로 두고 호출측이 ID를 지정한다

- **상태:** Accepted
- **날짜:** 2026-08-27
- **관련:** [GROUP_PLANNING.md](../GROUP_PLANNING.md), ADR-0007 (Superseded)
- **대체:** [ADR-0007](0007-groups-tree-replaces-tenant-id.md)

## 맥락

ADR-0007은 `tenant_id` 문자열 필터를 **자기참조 그룹 트리**로 바꿨다. `parent_id` + materialized `path`/`depth`, 청크 `group_path`, `include_descendants`가 따라왔다.

실제 호출은 트리보다 **컬렉션 ID**에 가깝다. 외부 시스템은 UUID가 아닌 `ga` 같은 키를 이미 갖고 있고, 하위 포함 검색·그룹 이동은 쓰지 않는다. 트리 제약(순환, max_depth, path 재기록)만 남았다.

그룹은 1급 엔티티로 유지하되, 계층과 UUID 강제는 접는다.

## 결정

**평면 `groups` + 호출측이 지정하는 문자열 PK.**

- `groups.id`는 `VARCHAR(128)`. `POST /v1/groups` body `id`는 선택. 있으면 그대로 쓰고, 없으면 UUID 문자열을 만든다.
- 허용 문자: ASCII 영숫자로 시작, 이후 영숫자·`.` `_` `-` `:` (길이 ≤ 128). UUID도 이 패턴에 맞다.
- 문서는 그룹 하나에만 속한다. 업로드 `group_id` 필수, 없는 그룹은 **400**. 기본 그룹 자동 생성 없음.
- `chunks.group_id`만 복제한다. `group_path` / `include_descendants` / `parent_id` / `path` / `depth` 제거.
- 검색: `group_id` 생략 시 전체, 있으면 `c.group_id = :group_id`.
- 이름 전역 UNIQUE. ID 중복·이름 중복은 **409**.
- 삭제: 소속 문서가 있으면 **409** (RESTRICT).
- 그룹 ID 변경 API는 두지 않는다 (문서·청크 FK).

## 대안

| 대안 | 기각 이유 |
|------|-----------|
| 트리 유지 + slug만 외부 ID | path/이동/descendants 복잡도가 그대로다 |
| `tenant_id` 문자열로 되돌리고 groups 테이블 삭제 | 고아 필터가 다시 생긴다. 그룹 CRUD가 없어진다 |
| ID를 UUID만 허용 | 외부 테넌트 코드(`ga`)를 매핑 테이블 없이 쓸 수 없다 |
| 업로드 시 없는 ID면 그룹 자동 생성 | 오타 ID가 그대로 컬렉션이 된다 |

## 결과

### 장점

- 외부 ID를 매핑 없이 업로드·검색에 쓴다
- 검색 WHERE가 한 줄로 단순해진다
- 트리 이동 시 청크 path 갱신 버그가 사라진다

### 단점

- 폴더 계층·하위 일괄 검색은 API에 없다. 필요하면 호출측이 그룹을 여러 번 질의한다
- 이미 발급된 UUID 그룹은 마이그레이션 후 문자열 UUID로 남는다. `ga`로 쓰려면 새 그룹을 만든다
- 그룹 ACL은 여전히 없다. ID를 알면 검색 가능하다

### 후속 조치

- [x] Alembic `006_flat_groups`
- [x] 그룹 CRUD에서 tree/parent 제거, 생성 시 `id` 수용
- [x] retrieve/query에서 `include_descendants` 제거
- [ ] 문서 그룹 이동 API는 여전히 미도입
