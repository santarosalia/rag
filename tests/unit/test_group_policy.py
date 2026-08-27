from rag.groups.policy import can_delete_group, exceeds_after_move, new_child_depth


def test_delete_allowed_only_for_empty_leaf():
    assert can_delete_group(has_children=False, has_documents=False)
    assert not can_delete_group(has_children=True, has_documents=False)
    assert not can_delete_group(has_children=False, has_documents=True)


def test_new_child_depth_from_parent():
    assert new_child_depth(None) == 0
    assert new_child_depth(0) == 1
    assert new_child_depth(6) == 7


def test_move_rejected_when_subtree_would_exceed_max_depth():
    assert exceeds_after_move(
        moving_depth=1,
        subtree_max_depth=3,
        new_parent_depth=6,
        max_depth=8,
    )
    assert not exceeds_after_move(
        moving_depth=1,
        subtree_max_depth=3,
        new_parent_depth=0,
        max_depth=8,
    )
