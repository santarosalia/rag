# 그룹 트리 기획서 (superseded)

> **상태:** Superseded — 2026-08-27  
> **대체:** [`GROUP_PLANNING.md`](GROUP_PLANNING.md) · [ADR-0009](adr/0009-flat-groups-caller-defined-id.md)

ADR-0007의 자기참조 트리(`parent_id` / `path` / `depth` / `include_descendants`)는 쓰지 않는다.  
그룹은 평면 컬렉션이고, 생성 시 호출측이 UUID가 아닌 문자열 ID(`ga` 등)를 지정할 수 있다.

당시 트리 설계의 상세는 git 이력의 이 파일과 [ADR-0007](adr/0007-groups-tree-replaces-tenant-id.md)를 본다.
