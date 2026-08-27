from rag.groups.tree import exceeds_max_depth, subtree_new_max_depth


def can_delete_group(*, has_children: bool, has_documents: bool) -> bool:
    return not has_children and not has_documents


def new_child_depth(parent_depth: int | None) -> int:
    return 0 if parent_depth is None else parent_depth + 1


def exceeds_after_move(
    *,
    moving_depth: int,
    subtree_max_depth: int,
    new_parent_depth: int | None,
    max_depth: int,
) -> bool:
    return exceeds_max_depth(
        subtree_new_max_depth(moving_depth, subtree_max_depth, new_parent_depth),
        max_depth,
    )
