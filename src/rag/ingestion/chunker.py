from __future__ import annotations

from dataclasses import dataclass

import tiktoken
from llama_index.core import Document
from llama_index.core.node_parser import HierarchicalNodeParser, get_leaf_nodes
from llama_index.core.schema import NodeRelationship


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page: int | None = None
    token_count: int = 0
    role: str = "child"
    kind: str = "prose"
    parent_key: str | None = None


class MarkdownChunker:
    """Markdown → HierarchicalNodeParser (2-level) → parent + child TextChunks.

    Parent level uses ``parent_max_tokens``; leaf level uses ``max_tokens``.
    Only leaves are meant for embedding/search; parents provide generation context.
    """

    def __init__(
        self,
        max_tokens: int = 768,
        parent_max_tokens: int = 2048,
        overlap_tokens: int = 128,
        encoding_name: str = "cl100k_base",
    ) -> None:
        self.max_tokens = max_tokens
        self.parent_max_tokens = parent_max_tokens
        self.overlap_tokens = overlap_tokens
        try:
            self.encoding = tiktoken.get_encoding(encoding_name)
        except Exception:
            self.encoding = tiktoken.get_encoding("cl100k_base")

        self._parser = HierarchicalNodeParser.from_defaults(
            chunk_sizes=[self.parent_max_tokens, self.max_tokens],
            chunk_overlap=self.overlap_tokens,
        )

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def chunk(self, text: str, page: int | None = None) -> list[TextChunk]:
        text = text.strip()
        if not text:
            return []

        nodes = self._parser.get_nodes_from_documents([Document(text=text)])
        by_id = {node.node_id: node for node in nodes}
        leaves = get_leaf_nodes(nodes)

        parents: dict[str, TextChunk] = {}
        children: list[TextChunk] = []

        for leaf in leaves:
            parent_rel = leaf.relationships.get(NodeRelationship.PARENT)
            parent_node = by_id.get(parent_rel.node_id) if parent_rel else None
            parent_key = parent_node.node_id if parent_node is not None else None

            if parent_node is not None and parent_key not in parents:
                parent_content = parent_node.get_content().strip()
                parents[parent_key] = TextChunk(
                    content=parent_content,
                    chunk_index=len(parents),
                    page=page,
                    token_count=self.count_tokens(parent_content),
                    role="parent",
                    kind="prose",
                    parent_key=parent_key,
                )

            child_content = leaf.get_content().strip()
            if not child_content:
                continue
            children.append(
                TextChunk(
                    content=child_content,
                    chunk_index=len(children),
                    page=page,
                    token_count=self.count_tokens(child_content),
                    role="child",
                    kind="prose",
                    parent_key=parent_key,
                )
            )

        return [*parents.values(), *children]
