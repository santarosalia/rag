from collections.abc import Sequence
from typing import Any
from uuid import UUID

from rag.models.schemas import GroupTreeNode


def root_path(group_id: UUID) -> str:
    return f"/{group_id}"


def child_path(parent_path: str, group_id: UUID) -> str:
    return f"{parent_path.rstrip('/')}/{group_id}"


def is_under(parent_path: str, path: str) -> bool:
    prefix = parent_path.rstrip("/")
    return path.startswith(prefix + "/")


def would_create_cycle(
    moving_id: UUID,
    moving_path: str,
    new_parent_id: UUID | None,
    new_parent_path: str | None,
) -> bool:
    if new_parent_id is None:
        return False
    if moving_id == new_parent_id:
        return True
    if not new_parent_path:
        return False
    return is_under(moving_path, new_parent_path)


def exceeds_max_depth(new_depth: int, max_depth: int) -> bool:
    return new_depth >= max_depth


def subtree_new_max_depth(
    moving_depth: int,
    subtree_max_depth: int,
    new_parent_depth: int | None,
) -> int:
    parent_depth = -1 if new_parent_depth is None else new_parent_depth
    new_moving_depth = parent_depth + 1
    delta = new_moving_depth - moving_depth
    return subtree_max_depth + delta


def rewrite_subtree_path(old_prefix: str, new_prefix: str, path: str) -> str:
    if path == old_prefix or path.startswith(old_prefix + "/"):
        return new_prefix + path[len(old_prefix) :]
    return path


def assemble_tree(groups: Sequence[Any]) -> list[GroupTreeNode]:
    nodes = {
        group.id: GroupTreeNode(
            id=group.id,
            parent_id=group.parent_id,
            name=group.name,
            slug=group.slug,
            path=group.path,
            depth=group.depth,
            created_at=group.created_at,
            updated_at=group.updated_at,
            children=[],
        )
        for group in groups
    }
    roots: list[GroupTreeNode] = []
    for group in groups:
        node = nodes[group.id]
        if group.parent_id is None or group.parent_id not in nodes:
            roots.append(node)
        else:
            nodes[group.parent_id].children.append(node)

    def sort_nodes(items: list[GroupTreeNode]) -> None:
        items.sort(key=lambda item: item.name)
        for item in items:
            sort_nodes(item.children)

    sort_nodes(roots)
    return roots
