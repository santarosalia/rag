# Kiwi 형태소 · Sparse FTS

> **목적:** 한국어 Sparse 검색을 위해 문서·쿼리를 같은 방식으로 형태소 분해한다.  
> **구현:** [`morphology.py`](../src/rag/indexing/morphology.py) · [`pgvector_backend.py`](../src/rag/indexing/pgvector_backend.py) · [`glossary/`](../src/rag/glossary/)  
> **의존:** `kiwipiepy` (`pyproject.toml`)  
> **결정:** [ADR-0001](adr/0001-postgresql-pgvector-kiwi-hybrid-search.md)

관련: [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`CHUNKING.md`](CHUNKING.md)

---

## 0. 역할

Dense(BGE-M3 임베딩)와 별도로, PostgreSQL **tsvector FTS**용 텍스트를 만든다.

| 단계 | 입력 | Kiwi | 결과 |
|------|------|------|------|
| Ingest (`bulk_index`) | 청크 `content` | `analyze` | `content_morph` + `tsv = to_tsvector('simple', content_morph)` |
| Retrieve (Sparse / `fts_search`) | 사용자 질의 | 용어집 확장 B 후 alias별 `analyze` | `to_tsquery('simple', …)` · `ts_rank` |

문서와 쿼리를 **동일 analyzer**(기본 `Kiwi()`)로 맞춘다. PG `korean` 사전 대신 **앱에서 Kiwi → `simple` config** (ADR-0001).

임베딩·rerank·LLM에는 Kiwi/용어집 결과를 **넣지 않는다.** Sparse 전용.

**Kiwi 사용자 사전(`add_user_word`)에 용어집을 일괄 등록하지 않는다.** 긴 동의어 구가 한 토큰이 되면 문서 `tsv`(잘게 분절)와 어긋난다. 동의어는 아래 확장 B로만 처리한다.

---

## 1. Analyzer (`KiwiMorphAnalyzer`)

```python
Kiwi()  # lazy load, get_morph_analyzer() process당 1회

def analyze(text) -> str:
    for token in kiwi.tokenize(text):
        form = token.form.strip()
        if len(form) > 1 or form.isalnum():
            tokens.append(form)
    return " ".join(tokens) if tokens else text
```

---

## 2. 용어집 (Postgres) + Sparse 확장 B

표 `glossary_terms` (전역). API: `/v1/glossary` CRUD, `POST /v1/glossary/reload`.  
시드: `uv run python scripts/seed_glossary.py ad_glossary_v1.0_20260828.csv`

메모리 `GlossaryStore`: surface → alias 집합. API lifespan / Celery worker init / CRUD·`POST /v1/glossary/reload` 시 해당 프로세스만 갱신. **worker는 HTTP가 없으므로 용어집 변경 후 worker 재시작**이 필요하다.

```text
Query (원문)
 ├─ Dense → BGE-M3
 └─ Sparse:
      longest surface match (원문)
        → 매칭 용어: alias 각각 Kiwi.analyze → lexeme OR 그룹
        → 잔여: Kiwi.analyze → AND
        → to_tsquery('simple', "(a|b) & c & ...")
```

Dense/rerank는 원문 쿼리 유지. Sparse는 Postgres **`ts_rank` FTS** (`fts_search`).

`POST /v1/query`의 `include_glossary_definitions`(default **false**): true면 질의에서 매칭된 용어의 `definition`만 LLM 컨텍스트 앞에 `[Glossary]` 블록으로 붙인다.

---

## 3. Ingest

searchable 청크만 embed + Kiwi → `content_morph` / `tsv`. 용어집 변경만으로는 **재 ingest 불필요**(사용자 사전 미사용).

---

## 4. 코드 맵

| 파일 | 역할 |
|------|------|
| `indexing/morphology.py` | Kiwi analyze |
| `glossary/store.py` | 인메모리 surface 맵 |
| `glossary/expand.py` | longest-match + OR tsquery |
| `glossary/csv_io.py` / `scripts/seed_glossary.py` | CSV 시드 |
| `api/glossary.py` | `/v1/glossary` |
| `indexing/pgvector_backend.py` | FTS에 확장 쿼리 적용 |
| alembic `012` | `glossary_terms` |
