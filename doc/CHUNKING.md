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
| `max_tokens` | 768 | 한 청크 상한 (가방) |
| `overlap_tokens` | 128 | flush 시 다음 가방으로 넘기는 블록 겹침 |
| `min_chunk_tokens` | 64 | 짧은 leftover·말미 조각을 이전 청크에 붙이는 임계 |
| `small_table_max_tokens` | 128 | 이하면 표를 prose로 가방에 넣음 |
| `small_table_max_rows` | 8 | 작은 표 최대 행 수 |

토큰 수는 **tiktoken `cl100k_base`**.

---

## 2. 설계 원칙

- **LlamaIndex `MarkdownElementNodeParser`**: title / text / table / code **경계만** 탐지 (`extract_elements`, LLM 요약 없음).
- **ChunkBag**: 28일 SemanticChunker와 같이 heading·prose·(작은) 표를 768까지 **이어 붙임**.
- **큰 표·코드**: atomic. 예산이 남으면 **앞 prose와 같은 가방**에 둘 수 있음 (C01).
- **작은 표** (토큰·행 수 이하): prose로 가방에 넣어 본문과 합침.
- **짧은 말미 청크** (`min_chunk_tokens` 미만, 헤딩 아님): 직전 청크에 append. 도메인 키워드 목록 없음.
- PG에는 평문 `content`만. element type / IndexNode는 저장하지 않음.

---

## 3. 분할 순서

```
Markdown
  → extract_elements (+ HTML table)
  → Block: heading | prose | atomic
  → ChunkBag (max / overlap / min_chunk_tokens)
  → tail merge
  → TextChunk 목록
```

빈 입력 → 청크 0개.

### leftover (`min_chunk_tokens`)

| flush 결과 | 동작 |
|------------|------|
| ≥ min | 새 청크 |
| 문서 첫 청크 | 새 청크 |
| `#`로 시작 | 새 청크 |
| 그 외 짧음 | 이전 청크에 `\n\n` append |

---

## 4. 청크 필드

| 필드 | 값 |
|------|-----|
| `content` | 평문 Markdown 조각 |
| `chunk_index` | 0부터 |
| `token_count` | cl100k_base |
| `page` | 항상 `NULL` (파이프라인이 page 미전달) |

---

## 5. 하지 않는 것

- LLM 표 요약 / HierarchicalNodeParser / AutoMergingRetriever
- parent-child DB 스키마 — 기획: [`PARENT_CHILD_PLANNING.md`](PARENT_CHILD_PLANNING.md)
- VectorStoreIndex

---

## 6. 관련 코드

| 위치 | 역할 |
|------|------|
| `configs/default.yaml` | chunking 키 |
| `src/rag/ingestion/chunker.py` | 하이브리드 조립 |
| `src/rag/ingestion/pipeline.py` | YAML → chunker |
| `tests/unit/test_chunker.py` | C01 co-location, 메타/푸터, atomic, leftover |
