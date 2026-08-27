# 청킹 규칙

> **목적:** Markdown을 `chunks` 행으로 나누는 규칙을 한곳에 둔다.  
> **구현:** [`src/rag/ingestion/chunker.py`](../src/rag/ingestion/chunker.py) `SemanticChunker`  
> **설정:** [`configs/default.yaml`](../configs/default.yaml) `chunking`

관련: [`PARSE_BOUNDARY.md`](PARSE_BOUNDARY.md) (입력은 Markdown) · [`RAG_PLANNING.md`](RAG_PLANNING.md) §3.3

청커는 **원본 PDF/DOCX를 보지 않는다.** 경로 A(MarkItDown)든 경로 B(파싱본)든 합류점은 Markdown이다.

---

## 1. 파라미터

| 키 | 기본값 | 역할 |
|----|--------|------|
| `max_tokens` | 768 | 한 청크 상한. 이보다 큰 블록은 더 잘게 자른다 |
| `overlap_tokens` | 128 | flush 때 다음 청크로 넘기는 겹침 예산 |
| `min_chunk_tokens` | 64 | 이보다 짧은 자투리는 버린다 (아래 예외) |

토큰 수는 **tiktoken `cl100k_base`**. 인코딩을 못 불러오면 같은 이름으로 재시도한다.

`IngestionPipeline`이 YAML을 읽어 `SemanticChunker(...)`에 넘긴다. 키가 없으면 위 기본값.

---

## 2. 설계 원칙

- 고정 길이 슬라이딩보다 **헤딩·표 경계**를 먼저 지킨다.
- overlap으로 경계에 걸린 문단의 recall 손실을 줄인다. 겹침은 **토큰 단위 슬라이딩이 아니라 통째 블록**이다.
- 표는 가능하면 한 청크에 둔다.
- 그래도 큰 문단은 **문장 → 단어** 순으로 자른다.

---

## 3. 분할 순서

빈 입력(`strip` 후 빈 문자열)은 청크 0개. ingest는 이때 `No content extracted`로 실패한다.

### 3.1 헤딩 섹션

`#{1,3} `(줄 시작, `#`/`##`/`###` 뒤에 공백)으로 섹션을 나눈다. `####` 이하는 경계가 아니다.

첫 헤딩 앞 본문이 있으면 그 구간도 섹션 하나다. 각 섹션은 헤딩 줄부터 다음 동급 경계 직전까지다.

### 3.2 Markdown 블록

섹션을 줄 단위로 읽으며 블록을 만든다.

- 빈 줄 → 현재 버퍼 flush (문단·목록 경계)
- `| ... |` 형태의 연속 줄 → **표 한 블록**. 표가 시작되면 그 앞 버퍼를 먼저 flush한다. 표가 아닌 줄이 나오면 표를 flush한다.

코드 펜스(`` ``` ``)는 따로 취급하지 않는다. 펜스 안에 빈 줄이 있으면 블록이 갈라진다. 목록도 빈 줄이 없으면 한 블록이다.

### 3.3 가방에 담기 (`max_tokens`)

섹션 순서로 블록을 현재 가방(`current_parts`)에 넣는다. 가방 안 블록은 `\n\n`로 이어 붙인다.

**일반 블록**

1. 블록 토큰 + 현재 가방 > 768 이고 가방이 비어 있지 않으면: overlap을 집고 flush한 뒤, overlap 블록만 새 가방에 남긴다.
2. 블록을 가방에 넣는다.

**표 블록** (`|` 줄만으로 이뤄진 블록)

1. 합치면 768을 넘고 가방이 있으면 **overlap 없이** flush한다.
2. 표를 통째로 가방에 넣는다. 표 자체는 문장/단어로 쪼개지 않는다.
3. 따라서 **거대 표 하나**는 768을 넘은 채 한 청크가 될 수 있다.

**768을 넘는 일반 블록**

1. 가방이 있으면 overlap을 집고 flush한 뒤 overlap을 임시 가방에 둔다.
2. 블록을 §3.4로 자른다.
3. 잘린 조각마다: 임시 가방이 있으면 그걸 먼저 flush하고, 조각은 **overlap 없이** 단독 청크다.

문서 끝 가방은 `min_chunk_tokens`를 통과하면 마지막 청크가 된다.

### 3.4 Oversized 재분할

1. `(?<=[.!?。！？])\s+` 로 문장 분리.
2. 문장을 768 이하로 묶는다.
3. 문장 하나가 768을 넘으면 공백 `split()` 단어 단위로 자른다.
4. 여기에는 overlap을 넣지 않는다.

한국어처럼 구두점·공백이 드문 긴 줄은 한 “문장/단어”로 남아 768을 넘을 수 있다.

### 3.5 Overlap

`flush` 직전, 가방의 **뒤에서부터** 블록을 모아 토큰 합이 `overlap_tokens`(128) 이하인 접두를 만든다.

- 한 블록이 128보다 크면 그 블록은 overlap에 안 들어간다. 그 앞 작은 블록만 남거나, overlap이 빈다.
- 블록을 잘라 128에 맞추지 않는다.
- 표 때문에 flush할 때는 overlap을 복사하지 않는다.

### 3.6 `min_chunk_tokens`

flush 결과 토큰 < 64 이면 **그 내용을 버린다.** 이전 청크에 합치지 않는다.

예외: 아직 청크가 하나도 없으면(문서 전체가 짧음) 그대로 1청크다.

---

## 4. 청크에 실리는 값

| 필드 | 지금 |
|------|------|
| `content` | 이어 붙인 Markdown 조각 |
| `chunk_index` | 문서 안 0부터 |
| `token_count` | `cl100k_base` 길이 |
| `page` | 파이프라인이 `chunk(markdown)`만 호출해서 **항상 `NULL`** |

검색용 `embedding` / `content_morph` / `tsv`는 청킹 다음 단계에서 채운다.

---

## 5. 하지 않는 것

- 원본 페이지 번호 복원
- Parent-child chunking (small 검색 → large context) — 기획 Phase 3
- 토큰 윈도우 슬라이딩 overlap
- `####` 이상 헤딩을 섹션 경계로 쓰기
- 코드 펜스·HTML 테이블을 표와 같이 특수 처리

---

## 6. 관련 코드

| 위치 | 역할 |
|------|------|
| `configs/default.yaml` `chunking` | 운영 값 |
| `src/rag/ingestion/chunker.py` | 분할 |
| `src/rag/ingestion/pipeline.py` | YAML → chunker, `chunk(markdown)` |
| `tests/unit/test_chunker.py` | 긴 문단 분할, 빈 입력, 헤딩 경계, 표 유지 |
