# 청킹 전략

> **목적:** Markdown을 `chunks` 행으로 나누는 전략을 한곳에 둔다.  
> **구현:** [`src/rag/ingestion/chunker.py`](../src/rag/ingestion/chunker.py) `MarkdownChunker`  
> **설정:** [`configs/default.yaml`](../configs/default.yaml) `chunking`

관련: [`PARSE_BOUNDARY.md`](PARSE_BOUNDARY.md) · [`RAG_PLANNING.md`](RAG_PLANNING.md) · [`PARENT_CHILD_PLANNING.md`](PARENT_CHILD_PLANNING.md)

청커는 **원본 PDF/DOCX를 보지 않는다.** 합류점은 Markdown이다.

---

## 1. 파라미터

| 키 | 기본값 | 역할 |
|----|--------|------|
| `max_tokens` | 768 | leaf(child) 상한 |
| `parent_max_tokens` | 2048 | parent 상한 |
| `overlap_tokens` | 128 | Hierarchical 레벨 간 overlap |

토큰 수는 **tiktoken `cl100k_base`** (청크 메타 `token_count`). 분할 자체는 LlamaIndex `SentenceSplitter` 토큰 규칙을 쓴다.

---

## 2. 설계 원칙

- **LlamaIndex `HierarchicalNodeParser` 2단:** `chunk_sizes=[parent_max_tokens, max_tokens]`.
- **parent:** 큰 토큰 창. DB에 저장하되 **임베딩/FTS 없음**.
- **child (leaf):** 검색·rerank 단위. 부모 `parent_chunk_id`로 연결.
- retrieve 후 **항상** 부모로 expand (`retrieval.expand_to_parent`). `AutoMergingRetriever` 미사용.
- PG에는 평문 `content` + `role` / `kind` / `parent_chunk_id`.
- 헤딩 섹션 부모·표 행 그룹·ChunkBag은 이번 구현에 **없음** (표는 토큰 경계에서 잘릴 수 있음).

---

## 3. 분할 순서

```
Markdown
  → Document
  → HierarchicalNodeParser (2048 → 768)
  → parent nodes + leaf nodes
  → TextChunk (role=parent|child)
```

빈 입력 → 청크 0개.

---

## 4. 청크 필드

| 필드 | 값 |
|------|-----|
| `content` | 평문 조각 (parent=큰 창, child=leaf) |
| `chunk_index` | role별 0부터 (child는 검색 단위 순서) |
| `token_count` | cl100k_base |
| `role` | `parent` \| `child` |
| `kind` | 기본 `prose` |
| `parent_key` | 청커 임시 키 (ingest가 UUID FK로 치환) |
| `page` | 항상 `NULL` (파이프라인이 page 미전달) |

`documents.chunk_count` = **child 수**.

---

## 5. 검색 · 생성

- SQL: `role = 'child'` (+ embedding/tsv NOT NULL)
- `Citation.chunk_id` / `snippet` = child
- `Citation.content` = parent (FK NULL 구문서는 child 본문)

---

## 6. 하지 않는 것

- Element + ChunkBag / 타입별 HTML·JSON·Code 라우팅
- 헤딩 섹션 = parent / 표 행 그룹 (후속 가능)
- `AutoMergingRetriever` / 부모 임베딩 / 3단 계층 / VectorStoreIndex

---

## 7. 관련 코드

| 위치 | 역할 |
|------|------|
| `configs/default.yaml` | chunking / expand_to_parent |
| `src/rag/ingestion/chunker.py` | Hierarchical 조립 |
| `src/rag/ingestion/pipeline.py` | parent INSERT → child embed |
| `src/rag/indexing/pgvector_backend.py` | child-only 검색 |
| `src/rag/retrieval/pipeline.py` | expand_to_parent |
| `tests/unit/test_chunker.py` | 계층·expand |
