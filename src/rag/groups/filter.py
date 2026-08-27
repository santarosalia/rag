from rag.groups.ids import parse_group_id


def group_filter_clause(group_id: str | None) -> tuple[str, dict[str, str]]:
    if group_id is None:
        return "", {}
    gid = parse_group_id(group_id, required=True)
    return "AND c.group_id = :group_id", {"group_id": gid}
