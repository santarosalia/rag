from uuid import UUID


def group_filter_clause(
    group_id: UUID | None,
    include_descendants: bool,
    group_path: str | None,
) -> tuple[str, dict[str, str]]:
    if group_id is None:
        return "", {}

    if not include_descendants:
        return "AND c.group_id = :group_id", {"group_id": str(group_id)}

    if not group_path:
        raise ValueError("group_path is required when include_descendants is true")

    return (
        "AND (c.group_path = :group_path OR c.group_path LIKE :group_path_prefix)",
        {
            "group_path": group_path,
            "group_path_prefix": f"{group_path}/%",
        },
    )
