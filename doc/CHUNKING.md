# 청킹 전략

> **목적:** `ParseResponse.results`를 `chunks` 행으로 만드는 전략.  
> **구현:** [`src/rag/ingestion/parse_items.py`](../src/rag/ingestion/parse_items.py)  
> **설정:** [`configs/default.yaml`](../configs/default.yaml) `chunking.max_tokens`

관련: [`PARSE_BOUNDARY.md`](PARSE_BOUNDARY.md) · DocuOps 대비 [`DOCUOPS_RAG_STRATEGY.md`](DOCUOPS_RAG_STRATEGY.md)

입력은 Parser Service(또는 `/documents/parse/file`)가 준 **레이아웃 단위**다. Markdown 전체를 SemanticChunker로 다시 자르지 않는다.

---

## 1. 파라미터

| 키 | 기본값 | 역할 |
|----|--------|------|
| `max_tokens` | 768 | 한 청크(원본/행)가 이보다 클 때만 문장·단어로 분할 |

토큰 수: tiktoken `cl100k_base`. 아이템 간 **overlap 없음**.

---

## 2. 규칙

| 규칙 | 동작 |
|------|------|
| 단위 | 1 item → 1+ chunk (표는 원본 + 행; **검색은 행만**) |
| 스킵 | `number`, `header`, `footer`, 빈 markdown |
| 제목 | `doc_title` / `paragraph_title` / `section_header` → 단독 임베딩 금지, 다음 본문(또는 **원본 표**) prefix |
| page | `prov[0].page_no` → `chunks.page` |
| type | 본문 item `type` → `chunks.type` |
| bbox | `prov[0].bbox` → `chunks.bbox` (JSONB) |
| 초과 | 단일 청크만 `max_tokens` 초과 시 분할; type/bbox/page 동일 유지 |

본문 예: `text`, `table`, `table_row`, `header_image`, `vision_footnote` 등.

### 2.1 표 정규화 + row-split (DocuOps MVP A)

`type`이 `table`/`table_text` 이거나 파이프·`<table>` 본문일 때:

1. **HTML이면** `prepare_table_content`로 파이프 Markdown 변환 (rowspan/colspan 격자 전개, style 제거)
2. **원본 표** 청크 1개 유지 (`type=table`, heading prefix는 여기에만) — DB에는 저장
3. 데이터 행 ≥ 2이면 행마다 `type=table_row` 추가 (`헤더줄\n데이터줄`, `|---|` 제외)
4. **검색:** row-split된 원본 `table`은 embedding/FTS **미적재** (`searchable=false`). 행만 검색
5. **컨텍스트:** `table_row` hit → `parent_chunk_id`로 부모 표 content expand + 같은 부모 dedupe ([`table_expand.py`](../src/rag/retrieval/table_expand.py)). FK 없으면 레거시로 앞쪽 최근 `table` 청크 id를 찾음.
6. 행 1개 이하면 split 없음 (원본만 검색)
7. 행 청크의 `page`/`bbox`는 부모 표와 동일

재 ingest + **worker/API 재배포** 후에야 검색에 반영된다.

---

## 3. 파이프라인

`IngestionPipeline`이 `documents.parse_json`을 `ParseResponse`로 읽고 `parse_response_to_chunks` → embed → bulk_index.

문서 원문/파싱 결과는 **Postgres JSONB**에만 있다 (S3 없음).
