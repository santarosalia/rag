# Parent-child · 표 행 단위 청킹 기획서

> **프로젝트명:** Hybrid RAG Platform  
> **대상:** 검색 단위(child)와 생성 단위(parent) 분리 + 거대 표만 행 그룹 child  
> **버전:** 0.4.0  
> **작성일:** 2026-08-27  
> **상태:** 구현 대상

관련: [`CHUNKING.md`](CHUNKING.md) (현재: Element 경계 + ChunkBag) · [`RAG_PLANNING.md`](RAG_PLANNING.md) · [`PARSE_BOUNDARY.md`](PARSE_BOUNDARY.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md)

현재 청커는 표·코드를 atomic으로 두되 **예산 안이면 prose와 같은 가방**에 넣고, 메타 표·푸터는 본문에 붙인다. 검색·생성 단위는 아직 같다. 이 문서는 그 다음 단계(parent-child + 거대 표 행 그룹)다.

---

## 0. 결론

**2단만 둔다.** 문서–섹션–표–행 같은 3단 FK는 만들지 않는다.

| | Child (검색) | Parent (생성) |
|--|--------------|---------------|
| **본문** | 지금 768 가방 | 헤딩 섹션. 섹션이 `parent_max_tokens` 이하면 섹션 전체 |
| **작은 표** (≤ `max_tokens`) | 통째 1개 (지금과 같음) | 같은 헤딩 섹션 |
| **큰 표** (> `max_tokens`) | 헤더를 붙인 행 그룹 | **헤더 + 인접 행 윈도우** (표 전체·섹션 전체 아님) |

임베딩·FTS·rerank는 **child만**. LLM 컨텍스트는 히트된 child의 **부모 `content`**. API `snippet`은 child 미리보기.

그룹 트리 때 지운 `groups.parent_id`와 구분하려고 컬럼 이름은 **`parent_chunk_id`** 다.

| 한다 | 하지 않는다 |
|------|-------------|
| `chunks.role` `parent` \| `child`, `parent_chunk_id` | 부모 HNSW/FTS 인덱싱 |
| 헤딩 섹션 = 본문·작은 표의 부모 | 임베딩 유사도 semantic chunking |
| 768 넘는 표만 행 그룹으로 쪼갬 | 작은 표를 행 단위로 쪼갬 |
| 큰 표 부모 = 토큰 상한 윈도우 | 거대 HTML 표 전체를 부모로 넣기 |
| rowspan/colspan 값을 child에 반복 | 완벽한 HTML 재구성 파서 |
| 검색 SQL `role = 'child'` | 3단 계층, 별도 parent 테이블 |
| overlap은 본문·섹션 내부만 | 표 행에 토큰 overlap (헤더 반복 + 윈도우가 대체) |

---

## 1. 왜 지금인가

세무과 매뉴얼(`group_id=dc`)은 헤딩 청킹으로 화면번호·짧은 조항은 잘 맞는다. 남는 구조 문제는 두 가지다.

1. **생성 문맥이 히트 조각에 묶임.** 같은 섹션의 예외(`단,`)·인접 문단이 top-k에 없으면 답에 안 들어간다. parent-child가 이 간극을 메운다.
2. **HTML `<table>` atomic이 수천 토큰.** `context_max_tokens` 4096이면 표 하나가 예산을 채운다. 행 그룹 child + 윈도우 부모가 예산을 나눈다.

DocuOps 0점(키워드 표기, 질의에 없는 `매수인`)은 이 기획의 성공 기준이 아니다. 표·섹션 문맥 문항과 재적재 후 토큰 분포로 본다.

현재 `MarkdownChunker`(Element + ChunkBag) 위에 **부모를 얹고, 거대 표만 조건부 행 그룹**한다.

---

## 2. 모델

```
Markdown
  → ATX 헤딩 섹션
       ├─ 본문 블록 → 768 가방 = prose child
       │                 부모 = 섹션 (또는 섹션이 크면 연속 가방 윈도우)
       ├─ 표 ≤ 768     = table child 1개, 부모 = 섹션
       ├─ 표 > 768     = 헤더+행 그룹 child들
       │                 부모 = 연속 행 윈도우 (≤ parent_max_tokens)
       └─ 코드 펜스    = 지금처럼 atomic child, 부모 = 섹션
  → 검색: child only → rerank → parent_chunk_id unique → LLM
```

같은 부모를 가리키는 child가 여러 개 히트되면 **부모 1개만** 컨텍스트에 넣는다. 점수는 그중 최고 rerank.

섹션이 `parent_max_tokens`보다 크고 표가 아니면, 본문도 **연속 child를 묶어 윈도우 부모**를 만든다. 규칙은 큰 표와 같다. 부모 종류를 두 개로 나누지 않는다. 차이는 child `kind`뿐이다.

---

## 3. 표 행 단위

코드 펜스는 행이 없으므로 계속 atomic이다.

### 3.1 언제 쪼개는가

| 조건 | 동작 |
|------|------|
| 파이프 표·HTML 표, 토큰 ≤ `max_tokens` | 통째 child |
| 같은 표, 토큰 > `max_tokens` | 행 그룹 child |
| 파싱 실패(행을 못 나눔) | 지금처럼 통째. 768을 넘을 수 있음 (기존 예외) |

### 3.2 Child 직렬화

원본 HTML을 슬라이스하지 않고 **헤더+행을 다시 직렬화**한다. `rowspan`/`colspan`이 있는 세목 표에서 행만 자르면 상위 칸이 사라진다.

각 child에 반복:

- 컬럼 헤더
- 그 행 그룹이 속한 rowspan 값 (예: `시세`)
- 데이터 1~N행

파이프 표: 헤더 줄 + 구분 줄 + 데이터 행.  
HTML 표: 가능하면 작은 `<table>…</table>` 또는 동등한 파이프/텍스트. 완벽한 DOM 보존은 목표가 아니다.

### 3.3 행 묶음 크기

한 행 = 한 child는 짧은 달력 표에서 child가 과다하다.

- child 예산: `table_child_max_tokens` (기본 **256**, `max_tokens`보다 작게)
- 하한: 헤더 + 데이터 1행. `min_chunk_tokens` 미만이면 **다음 행과 합친다. 행을 버리지 않는다.**

### 3.4 Overlap

표 행 child에는 토큰 overlap을 넣지 않는다. 헤더 반복과 윈도우 부모가 경계 문맥을 담당한다. 앞뒤 1행 중복은 선택이며 1차 구현에 넣지 않는다.

---

## 4. 부모 윈도우

큰 표의 부모를 표 전체로 두면 생성 단계가 지금과 같아진다.

- 연속 child를 `parent_max_tokens` (기본 **2048**)까지 묶어 부모 1행
- 부모 `content` = 그 윈도우에 속한 child를 헤더 1회 + 행 순서로 이어 붙인 텍스트 (child마다 헤더를 중복하지 않음)
- 부모는 `embedding` / `content_morph` / `tsv` **NULL**

본문 섹션이 2048 이하면 부모 `content` = 섹션 Markdown 그대로 (헤딩 줄 포함).

---

## 5. 스키마

`chunks` 한 테이블을 유지한다.

```
chunks
├── (기존 컬럼)
├── role              VARCHAR(16)  NOT NULL  DEFAULT 'child'   -- 'parent' | 'child'
├── parent_chunk_id   UUID NULL    FK → chunks.id  ON DELETE CASCADE
└── kind              VARCHAR(16)  NOT NULL  DEFAULT 'prose'   -- 'prose' | 'table' | 'fence'
```

제약·인덱스:

- `role = 'parent'` → `parent_chunk_id IS NULL`, 검색 컬럼 NULL
- `role = 'child'` → `parent_chunk_id` NOT NULL
- 검색: `ix_chunks_parent_chunk_id`, 기존 HNSW/GIN은 NULL 임베딩 부모를 자연히 제외. SQL에 `AND c.role = 'child'`를 **명시**한다 (실수 방지)
- `documents.chunk_count` = **child 수** (검색 단위). 부모 수는 넣지 않는다

기존 행은 `role='child'`, `parent_chunk_id` NULL이 된다. 마이그레이션만으로는 검색이 깨지지 않게, **`parent_chunk_id` NULL인 child는 자기 자신을 부모로 취급**하는 호환 경로를 둔다. 재적재 전에는 expand가 no-op에 가깝다.

컬럼 이름 `parent_id`는 쓰지 않는다.

`TextChunk` (청커 출력) 예:

| 필드 | 의미 |
|------|------|
| `content` | child 본문 |
| `chunk_index` | 문서 안 child 순서 (0부터, 부모 제외) |
| `token_count` | child 토큰 |
| `kind` | `prose` \| `table` \| `fence` |
| `section_index` | 헤딩 섹션 순번 |
| `parent_content` | 이 child가 붙을 부모 본문 (같은 윈도우 child는 동일 문자열) |
| `parent_key` | ingest가 부모 행을 묶는 키 (섹션 인덱스 또는 표+윈도우 순번) |

청커는 DB UUID를 만들지 않는다. `IngestionPipeline`이 `parent_key`별로 부모 행을 먼저 insert한 뒤 child에 FK를 단다. **embed / Kiwi / bulk_index는 child만.**

---

## 6. 청커 변경

`MarkdownChunker.chunk()`를 parent-child 출력으로 확장한다. LlamaIndex 헤딩 분할은 유지하고, 표 분기·부모 윈도우를 얹는다.

1. 헤딩 섹션마다 child를 닫는다. 섹션을 넘는 leftover append는 하지 않는다.
2. 본문: `max_tokens` 가방 + 섹션 내부 overlap.
3. 표 블록: §3. 큰 표면 본문 가방을 먼저 flush하고 표 child를 이어 붙인다.
4. 펜스: atomic, 섹션 부모.
5. 섹션(또는 표 윈도우)이 `parent_max_tokens`를 넘으면 연속 child로 부모를 나눈다.
6. leftover `< min_chunk_tokens`(이 단계에서 재도입)이고 같은 섹션 이전 child가 있으면 append. **다른 섹션에는 붙이지 않음.**

빈 입력 → 청크 0개는 [`CHUNKING.md`](CHUNKING.md)와 같다.

---

## 7. 검색 · 생성

`knn_search` / `bm25_search` WHERE에 `c.role = 'child'` (및 기존 `embedding`/`tsv` NOT NULL, `documents.status = 'completed'`).

rerank 입력은 **child `content`**. 부모로 rerank하면 큰 표 윈도우가 서로 비슷해진다.

`RetrievalPipeline` rerank 이후:

1. top-k child의 `parent_chunk_id`로 부모 `content` load (호환: FK NULL이면 child `content`)
2. 같은 부모 unique, 최고 점수 유지, 최초 히트 순서
3. `Citation.content` = 부모, `snippet` = child 앞 300자, `chunk_id` = **child** (추적)
4. `build_context`는 지금처럼 부모 전문을 순위대로, tiktoken `context_max_tokens`, 마지막만 자름

unique 후 부모가 3개 × 2048이면 예산에 2개만 들어갈 수 있다. `rerank_top_n` 기본 5는 유지하고, **unique 부모 기준으로 예산을 자른다.** 1차에서 top_n을 내리지 않는다.

retrieve-only(`POST /v1/retrieve`)도 같은 expand를 탄다. snippet은 child라 히트 근거가 보이고, 생성과 검색 경로가 갈라지지 않는다.

---

## 8. 설정

[`configs/default.yaml`](../configs/default.yaml) `chunking` / `retrieval`에 추가. 키가 없으면 아래 기본값.

| 키 | 기본 | 역할 |
|----|------|------|
| `chunking.max_tokens` | 768 | 본문 child 상한 (유지) |
| `chunking.overlap_tokens` | 128 | 본문·섹션 내부만 (유지) |
| `chunking.min_chunk_tokens` | 64 | leftover 결합 (**이 단계에서 재도입**) |
| `chunking.parent_max_tokens` | 2048 | 부모 윈도우 상한 |
| `chunking.table_child_max_tokens` | 256 | 큰 표 행 그룹 child 상한 |
| `retrieval.expand_to_parent` | true | false면 생성도 child `content` (A/B용) |

`context_max_tokens` 4096은 유지한다.

---

## 9. 마이그레이션 · 재적재

- Alembic: `role`, `parent_chunk_id`, `kind`. 기존 행 `role='child'`, `kind='prose'`, FK NULL
- 검색 필터 `role = 'child'`는 FK NULL child도 포함한다
- **품질을 쓰려면 문서를 다시 ingest**해야 한다. 스키마만으로는 표가 쪼개지지 않고 부모 행도 없다
- `dc` 매뉴얼 재적재 후 child 수·표 child 토큰 분포를 기록한다 (지금은 표 통째 4123토큰 청크가 있음)

API 계약(`Citation`의 공개 필드)은 바꾸지 않는다. `content`는 계속 `exclude=True`.

---

## 10. 하지 않는 것

- 부모 임베딩, HyDE, Graph RAG, 질의 “전부/모두” → 문서 전체 반환
- 표 목록 완전 나열(enumeration) 전용 라우팅 — 행 단위의 반대급부. 필요하면 별 기획
- 원본 페이지 번호 복원
- 깨진 HTML·중첩 표의 완전 파싱. 실패 시 통째 child
- 그룹 `parent_id` / `group_path` 부활

---

## 11. 구현 순서

테스트와 재적재를 나누기 쉽게 **두 스텝**으로 넣는다. 모델은 이 문서 하나다.

| 스텝 | 내용 | 검증 |
|------|------|------|
| **A** | 섹션 parent-child. 표·펜스는 아직 atomic child | 유닛: 섹션을 넘는 overlap 없음. retrieve expand. 본문 질의 DocuOps 회귀 없음 |
| **B** | `max_tokens` 넘는 표만 행 그룹 + 윈도우 부모 | 유닛: 파이프 헤더 반복, HTML rowspan 반복, 작은 표는 1 child. 거대 표 child 토큰 ≪ 4096 |

ingest → 검색 SQL → expand 순으로 머지한다. expand 없는 child 분할은 snippet만 좋아지고 생성 예산은 그대로다.

---

## 12. 성공 기준

| 기준 | 측정 |
|------|------|
| 검색 단위 | HNSW/FTS 히트는 `role=child`만 |
| 생성 단위 | `/v1/query` 컨텍스트는 부모 본문 (`expand_to_parent: false`면 child) |
| 작은 표 | ≤768 토큰 표는 child 1개 |
| 큰 표 | child `token_count` ≤ `table_child_max_tokens` + 헤더 여유. 부모 ≤ `parent_max_tokens` |
| API | `snippet`은 child, `chunk_id`는 child, 공개 JSON에 부모 필드 없음 |
| 회귀 | DocuOps `dc` 재실행. 화면번호(Q6·Q7) 실사용 통과 유지 |
| 표 문항 | 월별/세목 표에서 해당 행이 snippet에 있고, 부모가 이웃 행을 포함 |
| 호환 | 재적재 전 문서도 retrieve 200, 답변 가능 |

평가 세트는 [`tests/eval/DOCUOPS_TAX.md`](../tests/eval/DOCUOPS_TAX.md). 키워드 채점 오탐은 이 기획의 실패로 치지 않는다.

---

## 13. 관련 코드 (구현 시)

| 위치 | 역할 |
|------|------|
| `src/rag/ingestion/chunker.py` | 섹션 단위 flush, 표 행 그룹, `parent_content` |
| `src/rag/ingestion/pipeline.py` | 부모 행 insert, child만 embed/index |
| `src/rag/db/models.py` · Alembic | `role`, `parent_chunk_id`, `kind` |
| `src/rag/indexing/pgvector_backend.py` | `role = 'child'` |
| `src/rag/retrieval/pipeline.py` | expand, snippet=child / content=parent |
| `tests/unit/test_chunker.py` | 섹션 경계, 파이프/HTML 표 분할 |
| `configs/default.yaml` | §8 키 |
