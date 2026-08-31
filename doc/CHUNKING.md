# 청킹 전략

> **목적:** Markdown을 `chunks` 행으로 나누는 전략을 한곳에 둔다.  
> **구현:** [`src/rag/ingestion/chunker.py`](../src/rag/ingestion/chunker.py) `MarkdownChunker` (LlamaIndex `MarkdownElementNodeParser`)  
> **설정:** [`configs/default.yaml`](../configs/default.yaml) `chunking`

관련: [`PARSE_BOUNDARY.md`](PARSE_BOUNDARY.md) (입력은 Markdown) · [`RAG_PLANNING.md`](RAG_PLANNING.md) §3.3 · 다음 단계 [`PARENT_CHILD_PLANNING.md`](PARENT_CHILD_PLANNING.md)

청커는 **원본 PDF/DOCX를 보지 않는다.** 경로 A(MarkItDown)든 경로 B(파싱본)든 합류점은 Markdown이다.

---

## 1. 파라미터

| 키 | 기본값 | 역할 |
|----|--------|------|
| `max_tokens` | 768 | `SentenceSplitter.chunk_size` — 본문 청크 상한 |
| `overlap_tokens` | 128 | `SentenceSplitter.chunk_overlap` |

토큰 수는 **tiktoken `cl100k_base`**. 같은 인코더를 LlamaIndex `tokenizer`와 `token_count`에 쓴다.

---

## 2. 설계 원칙

- `MarkdownElementNodeParser`로 제목/본문/표/코드를 나눈다.
- **표·코드는 atomic**, 본문만 `SentenceSplitter`.
- LLM 표 요약은 쓰지 않는다 (`extract_elements`만 사용). PG에는 평문 `content`만.
- IndexNode / DataFrame / parent 관계는 저장하지 않는다.

---

## 3. 분할 순서

빈 입력(`strip` 후 빈 문자열)은 청크 0개. ingest는 이때 `No content extracted`로 실패한다.

```
Markdown
  → MarkdownElementNodeParser.extract_elements (+ HTML table)
  → title은 다음 본문/표/코드에 접두
  → table / table_text / code → 통째 1청크
  → text → SentenceSplitter
  → TextChunk 목록
```

헤딩 줄의 `#`는 Element가 떼어 내므로, 저장 전에 `#{level} `를 다시 붙인다.

---

## 4. 청크에 실리는 값

| 필드 | 지금 |
|------|------|
| `content` | 평문 Markdown 조각 |
| `chunk_index` | 문서 안 0부터 |
| `token_count` | `cl100k_base` 길이 |
| `page` | 파이프라인이 `chunk(markdown)`만 호출해서 **항상 `NULL`** |

---

## 5. 하지 않는 것

- 원본 페이지 번호 복원
- LLM 표 요약 / IndexNode recursive retrieve
- Parent-child · 거대 표 행 단위 — 기획: [`PARENT_CHILD_PLANNING.md`](PARENT_CHILD_PLANNING.md)
- `SemanticSplitterNodeParser`
- VectorStoreIndex / QueryEngine

---

## 6. 관련 코드

| 위치 | 역할 |
|------|------|
| `configs/default.yaml` `chunking` | 토큰 예산 |
| `src/rag/ingestion/chunker.py` | `MarkdownChunker` |
| `src/rag/ingestion/pipeline.py` | YAML → chunker |
| `tests/unit/test_chunker.py` | 헤딩, 표/코드 atomic, 긴 본문 |
