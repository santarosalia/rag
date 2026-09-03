# 청킹 전략

> **목적:** `ParseResponse.results`를 `chunks` 행으로 만드는 전략.  
> **구현:** [`src/rag/ingestion/parse_items.py`](../src/rag/ingestion/parse_items.py)  
> **설정:** [`configs/default.yaml`](../configs/default.yaml) `chunking.max_tokens`

관련: [`PARSE_BOUNDARY.md`](PARSE_BOUNDARY.md)

입력은 Parser Service(또는 `/documents/parse/file`)가 준 **레이아웃 단위**다. Markdown 전체를 SemanticChunker로 다시 자르지 않는다.

---

## 1. 파라미터

| 키 | 기본값 | 역할 |
|----|--------|------|
| `max_tokens` | 768 | 한 item이 이보다 클 때만 문장·단어로 분할 |

토큰 수: tiktoken `cl100k_base`. 아이템 간 **overlap 없음**.

---

## 2. 규칙

| 규칙 | 동작 |
|------|------|
| 단위 | 1 embeddable item → 1 chunk |
| 스킵 | `number`, `header`, `footer`, 빈 markdown |
| 제목 | `doc_title` / `paragraph_title` / `section_header` → 단독 임베딩 금지, 다음 본문 prefix |
| page | `prov[0].page_no` → `chunks.page` |
| type | 본문 item `type` → `chunks.type` |
| bbox | `prov[0].bbox` → `chunks.bbox` (JSONB) |
| 초과 | 단일 item만 `max_tokens` 초과 시 분할; type/bbox/page 동일 유지 |

본문 예: `text`, `table`, `header_image`, `vision_footnote` 등.

---

## 3. 파이프라인

`IngestionPipeline`이 `documents.parse_json`을 `ParseResponse`로 읽고 `parse_response_to_chunks` → embed → bulk_index.

문서 원문/파싱 결과는 **Postgres JSONB**에만 있다 (S3 없음).
