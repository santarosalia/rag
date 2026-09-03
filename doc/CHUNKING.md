# 청킹 전략

> **목적:** Markdown을 `chunks` 행으로 나누는 전략을 한곳에 둔다.  
> **구현:** [`src/rag/ingestion/chunker.py`](../src/rag/ingestion/chunker.py) `SemanticChunker`  
> **설정:** [`configs/default.yaml`](../configs/default.yaml) `chunking`

관련: [`PARSE_BOUNDARY.md`](PARSE_BOUNDARY.md) (입력은 Markdown) · [`RAG_PLANNING.md`](RAG_PLANNING.md) §3.3 · 다음 단계 [`PARENT_CHILD_PLANNING.md`](PARENT_CHILD_PLANNING.md)

청커는 **원본 PDF/DOCX를 보지 않는다.** 입력은 이미 파싱된 UTF-8 Markdown이다.

---

## 1. 파라미터

| 키 | 기본값 | 역할 |
|----|--------|------|
| `max_tokens` | 768 | 한 청크 상한. 이보다 큰 블록은 더 잘게 자른다 |
| `overlap_tokens` | 128 | flush 때 다음 청크로 넘기는 겹침 예산 |
| `min_chunk_tokens` | 64 | 이보다 짧으면 이전 청크에 붙일지, 단독으로 남길지 가르는 임계값. **버리지는 않는다** |

토큰 수는 **tiktoken `cl100k_base`**. 인코딩을 못 불러오면 같은 이름으로 재시도한다.

`IngestionPipeline`이 YAML을 읽어 `SemanticChunker(...)`에 넘긴다. 키가 없으면 위 기본값.

---

## 2. 설계 원칙

- 고정 길이 슬라이딩보다 **헤딩·atomic 블록(표·펜스·HTML 표)** 경계를 먼저 지킨다.
- overlap으로 경계에 걸린 문단의 recall 손실을 줄인다. 겹침은 **토큰 단위 슬라이딩이 아니라 통째 블록**이다.
- 파이프 표, 코드 펜스, HTML `<table>`은 가능하면 한 청크에 둔다.
- 그래도 큰 문단은 **문장 → 단어** 순으로 자른다.
- 짧은 본문 leftover는 검색 노이즈로 버리지 않는다. 이전 청크에 붙이거나 헤딩이면 단독 청크로 남긴다.

---

## 3. 분할 순서

빈 입력(`strip` 후 빈 문자열)은 청크 0개. ingest는 이때 `No content extracted`로 실패한다.

### 3.1 헤딩 섹션

`(?m)^#{1,6}\s+` (줄 시작 ATX, `#`–`######` 뒤 공백/탭)으로 섹션을 나눈다. leftover 헤딩 판별과 **같은 패턴**이다.

코드 펜스와 HTML `<table>…</table>` **안**의 `#` 줄은 섹션 경계가 아니다.

첫 헤딩 앞 본문이 있으면 그 구간도 섹션 하나다. 각 섹션은 헤딩 줄부터 다음 ATX 경계 직전까지다. Setext(`제목` + `===`)는 헤딩이 아니다.

### 3.2 Markdown 블록

섹션을 줄 단위로 읽으며 블록을 만든다.

- 빈 줄 → 현재 버퍼 flush (문단·목록 경계)
- **Atomic 블록**은 빈 줄로 가르지 않는다. 앞 버퍼를 먼저 flush한 뒤 닫힐 때까지 한 덩어리:
  - 파이프 표: `| ... |` 연속 줄. `|`가 아닌 줄에서 닫힌다.
  - 코드 펜스: 줄 시작 ` ``` ` 또는 `~~~` (3개 이상). 같은 문자·길이 이상으로 닫힌다. 닫히지 않으면 끝까지.
  - HTML 표: `<table` … `</table>` (대소문자 무시, 중첩은 depth). 닫히지 않으면 끝까지.

목록은 빈 줄이 없으면 한 블록이다. 인라인 코드·들여쓰기 코드(4칸)는 atomic이 아니다.

### 3.3 가방에 담기 (`max_tokens`)

섹션 순서로 블록을 현재 가방(`current_parts`)에 넣는다. 가방 안 블록은 `\n\n`로 이어 붙인다.

**일반 블록**

1. 블록 토큰 + 현재 가방 > 768 이고 가방이 비어 있지 않으면: overlap을 집고 flush한 뒤, overlap 블록만 새 가방에 남긴다.
2. 블록을 가방에 넣는다.

**Atomic 블록** (파이프 표, 코드 펜스, HTML `<table>`)

1. 합치면 768을 넘고 가방이 있으면 **overlap 없이** flush한다.
2. 통째로 가방에 넣는다. 문장/단어로 쪼개지 않는다.
3. 따라서 **거대 atomic 하나**는 768을 넘은 채 한 청크가 될 수 있다.

**768을 넘는 일반 블록**

1. 가방이 있으면 overlap을 집고 flush한 뒤 overlap을 임시 가방에 둔다.
2. 블록을 §3.4로 자른다.
3. 잘린 조각마다: 임시 가방이 있으면 그걸 먼저 flush하고, 조각은 **overlap 없이** 단독 청크다.

문서 끝 가방도 같은 `flush`를 탄다 (§3.6).

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
- atomic 블록 때문에 flush할 때는 overlap을 복사하지 않는다.

### 3.6 `min_chunk_tokens`

64토큰은 **검색 품질 때문에 버리는 하한**이 아니다. 짧은 leftover를 어디에 붙일지 가르는 값이다. 비어 있지 않은 flush는 유실하지 않는다.

헤딩 시작 판별은 §3.1과 같다: `(?m)^#{1,6}\s+`. leftover는 `content.strip()` 뒤 `match`만 본다 (`(?m)`이 있어도 `match`는 문자열 시작만).

| flush 결과 | 동작 |
|------------|------|
| 토큰 ≥ 64 | 새 청크 |
| 청크가 아직 없음 (짧은 문서 전체) | 새 청크 1개 |
| < 64 이고 헤딩으로 시작 | 새 청크 (이전 섹션에 헤딩을 붙이지 않음) |
| < 64 이고 본문이며 이전 청크가 있음 | **이전 청크에 `\n\n` append** |

append 하면 이전 청크가 `max_tokens`를 조금 넘을 수 있다. 거대 atomic과 같은 예외로 둔다.

하지 않는 것: 다음 청크 prepend, 헤딩만 있는 줄 폐기, 완결 문장 NLP 판별.

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
- Parent-child · 거대 표 행 단위 — 아직 미구현. 기획: [`PARENT_CHILD_PLANNING.md`](PARENT_CHILD_PLANNING.md)
- 토큰 윈도우 슬라이딩 overlap
- 인라인 코드·들여쓰기 코드(4칸)·깨진 HTML을 완벽 파싱

---

## 6. 관련 코드

| 위치 | 역할 |
|------|------|
| `configs/default.yaml` `chunking` | 운영 값 |
| `src/rag/ingestion/chunker.py` | 분할 |
| `src/rag/ingestion/pipeline.py` | YAML → chunker, `chunk(markdown)` |
| `tests/unit/test_chunker.py` | 긴 문단, 헤딩, 파이프/HTML 표, 코드 펜스, 짧은 leftover |
