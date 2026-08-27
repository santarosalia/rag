from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from rag.groups.tree import assemble_tree


def test_assemble_tree_nests_children_under_parent():
    root_id = uuid4()
    child_id = uuid4()
    now = datetime.now(UTC)
    groups = [
        SimpleNamespace(
            id=root_id,
            parent_id=None,
            name="root",
            slug=None,
            path=f"/{root_id}",
            depth=0,
            created_at=now,
            updated_at=now,
        ),
        SimpleNamespace(
            id=child_id,
            parent_id=root_id,
            name="child",
            slug=None,
            path=f"/{root_id}/{child_id}",
            depth=1,
            created_at=now,
            updated_at=now,
        ),
    ]
    tree = assemble_tree(groups)
    assert len(tree) == 1
    assert tree[0].id == root_id
    assert len(tree[0].children) == 1
    assert tree[0].children[0].id == child_id
