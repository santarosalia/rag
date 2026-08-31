# 청킹 전략

> **목적:** Markdown을 `chunks` 행으로 나누는 전략을 한곳에 둔다.  
> **구현:** [`src/rag/ingestion/chunker.py`](../src/rag/ingestion/chunker.py) `MarkdownChunker` (LlamaIndex)  
> **설정:** [`configs/default.yaml`](../configs/default.yaml) `chunking`

관련: [`PARSE_BOUNDARY.md`](PARSE_BOUNDARY.md) (입력은 Markdown) · [`RAG_PLANNING.md`](RAG_PLANNING.md) §3.3 · 다음 단계 [`PARENT_CHILD_PLANNING.md`](PARENT_CHILD_PLANNING.md)

청커는 **원본 PDF/DOCX를 보지 않는다.** 경로 A(MarkItDown)든 경로 B(파싱본)든 합류점은 Markdown이다.

---

## 1. 파라미터

| 키 | 기본값 | 역할 |
|----|--------|------|
| `max_tokens` | 768 | `SentenceSplitter.chunk_size` — 한 청크 상한 |
| `overlap_tokens` | 128 | `SentenceSplitter.chunk_overlap` — 청크 간 토큰 겹침 |

토큰 수는 **tiktoken `cl100k_base`**. 같은 인코더를 LlamaIndex `tokenizer`와 `token_count`에 쓴다.

`IngestionPipeline`이 YAML을 읽어 `MarkdownChunker(...)`에 넘긴다. 키가 없으면 위 기본값.

---

## 2. 설계 원칙

- 자체 헤딩/표/펜스 파서를 두지 않는다. **LlamaIndex**가 분할한다.
- ATX 헤딩 섹션을 먼저 나눈 뒤, 섹션 안에서 문장·토큰 예산으로 자른다.
- 파이프 표·코드 펜스·HTML `<table>`을 **atomic으로 보장하지 않는다.** 잘릴 수 있다.
- 짧은 leftover를 이전 청크에 붙이지 않는다. (`min_chunk_tokens` 없음)

---

## 3. 분할 순서

빈 입력(`strip` 후 빈 문자열)은 청크 0개. ingest는 이때 `No content extracted`로 실패한다.

```
Markdown
  → MarkdownNodeParser  (ATX 헤딩 섹션)
  → SentenceSplitter    (섹션별 chunk_size / chunk_overlap)
  → TextChunk 목록
```

### 3.1 헤딩 섹션

`MarkdownNodeParser`가 ATX 헤딩(`#`–`######`)으로 섹션을 나눈다. 각 섹션 노드를 `SentenceSplitter.split_text`로 재분할한다.

### 3.2 문장·토큰 분할

`SentenceSplitter`가 `max_tokens` / `overlap_tokens`에 맞춰 자른다. overlap은 라이브러리 기본(토큰 슬라이딩)이다. 한국어 문장 경계는 LlamaIndex 기본 구두점 규칙에 따른다 — 별도 Kiwi 문장 분리는 없다.

---

## 4. 청크에 실리는 값

| 필드 | 지금 |
|------|------|
| `content` | 노드 텍스트 |
| `chunk_index` | 문서 안 0부터 |
| `token_count` | `cl100k_base` 길이 |
| `page` | 파이프라인이 `chunk(markdown)`만 호출해서 **항상 `NULL`** |

검색용 `embedding` / `content_morph` / `tsv`는 청킹 다음 단계에서 채운다. 헤딩 경로 메타는 `TextChunk`에 넣지 않는다.

---

## 5. 하지 않는 것

- 원본 페이지 번호 복원
- 표·펜스 atomic 보장
- Parent-child · 거대 표 행 단위 — 기획: [`PARENT_CHILD_PLANNING.md`](PARENT_CHILD_PLANNING.md)
- `SemanticSplitterNodeParser` (임베딩 유사도 분할)
- VectorStoreIndex / QueryEngine — 청킹만 LlamaIndex

---

## 6. 관련 코드

| 위치 | 역할 |
|------|------|
| `configs/default.yaml` `chunking` | 운영 값 |
| `src/rag/ingestion/chunker.py` | `MarkdownChunker` 어댑터 |
| `src/rag/ingestion/pipeline.py` | YAML → chunker, `chunk(markdown)` |
| `tests/unit/test_chunker.py` | 빈 입력, 헤딩 경계, 긴 본문, `chunk_index` |
