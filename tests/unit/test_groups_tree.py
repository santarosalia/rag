import uuid

from rag.groups.tree import (
    child_path,
    exceeds_max_depth,
    is_under,
    rewrite_subtree_path,
    root_path,
    subtree_new_max_depth,
    would_create_cycle,
)


def test_root_and_child_path():
    gid = uuid.UUID("11111111-1111-4111-8111-111111111111")
    cid = uuid.UUID("22222222-2222-4222-8222-222222222222")
    root = root_path(gid)
    assert root == f"/{gid}"
    assert child_path(root, cid) == f"/{gid}/{cid}"


def test_is_under():
    parent = "/aaa"
    assert is_under(parent, "/aaa/bbb")
    assert not is_under(parent, "/aaa")
    assert not is_under(parent, "/aaax/bbb")


def test_cycle_when_parent_is_self_or_descendant():
    moving_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    child_id = uuid.UUID("22222222-2222-4222-8222-222222222222")
    moving_path = f"/{moving_id}"
    child_path_str = f"{moving_path}/{child_id}"
    assert would_create_cycle(moving_id, moving_path, moving_id, moving_path)
    assert would_create_cycle(moving_id, moving_path, child_id, child_path_str)
    other_id = uuid.UUID("33333333-3333-4333-8333-333333333333")
    assert not would_create_cycle(moving_id, moving_path, other_id, f"/{other_id}")
    assert not would_create_cycle(moving_id, moving_path, None, None)


def test_max_depth_root_plus_seven_children():
    assert not exceeds_max_depth(0, 8)
    assert not exceeds_max_depth(7, 8)
    assert exceeds_max_depth(8, 8)


def test_subtree_depth_after_move():
    # moving node depth 1, deepest descendant 3, new parent is root (depth 0)
    # new moving depth = 1, max becomes 3
    assert subtree_new_max_depth(moving_depth=1, subtree_max_depth=3, new_parent_depth=0) == 3
    # move under depth 6: new moving depth 7, descendant relative +2 => 9
    assert subtree_new_max_depth(moving_depth=1, subtree_max_depth=3, new_parent_depth=6) == 9
    # move to root
    assert subtree_new_max_depth(moving_depth=2, subtree_max_depth=4, new_parent_depth=None) == 2


def test_rewrite_subtree_path_updates_node_and_descendants():
    old = "/aaa/bbb"
    new = "/ccc/bbb"
    assert rewrite_subtree_path(old, new, old) == new
    assert rewrite_subtree_path(old, new, f"{old}/ddd") == f"{new}/ddd"
    assert rewrite_subtree_path(old, new, "/aaa") == "/aaa"
