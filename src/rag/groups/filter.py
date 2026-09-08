from rag.groups.ids import parse_group_id


def group_filter_clause(group_id: str | None) -> tuple[str, dict[str, str]]:
    if group_id is None:
        return "", {}
    gid = parse_group_id(group_id, required=True)
    return "AND c.group_id = :group_id", {"group_id": gid}


def normalize_tags(tags: list[str] | str | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        values = [tags]
    else:
        values = list(tags)
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = str(value).strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        cleaned.append(tag)
    return cleaned


def tag_filter_clause(tags: list[str] | str | None) -> tuple[str, dict[str, str]]:
    """AND filter: document.tag (text[]) must contain every requested tag."""
    cleaned = normalize_tags(tags)
    if not cleaned:
        return "", {}
    params: dict[str, str] = {}
    placeholders: list[str] = []
    for i, tag in enumerate(cleaned):
        key = f"doc_tag_{i}"
        placeholders.append(f":{key}")
        params[key] = tag
    clause = f"AND d.tag @> ARRAY[{', '.join(placeholders)}]::text[]"
    return clause, params
