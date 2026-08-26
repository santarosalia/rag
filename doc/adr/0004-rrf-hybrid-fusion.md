# ADR-0004: RRF로 Dense/Sparse 결과 융합

- **상태:** Accepted
- **날짜:** 2026-08-25

## 맥락

Dense(pgvector cosine)와 Sparse(FTS ts_rank)는 **점수 스케일이 다르다**.  
단순 가중합은 튜닝이 fragile하고, 백엔드 교체 시 재튜닝이 필요하다.

## 결정

**Reciprocal Rank Fusion (RRF)** 으로 dense top-50과 sparse top-50을 융합한다.

```
score(chunk) = Σ 1 / (k + rank_i)   , k = 60
```

구현: [`src/rag/retrieval/fusion.py`](../../src/rag/retrieval/fusion.py)

파이프라인:
1. Dense kNN top-50
2. Sparse FTS top-50
3. RRF fuse
4. Cross-encoder rerank top-5

## 대안

| 대안 | 기각 이유 |
|------|-----------|
| Linear score fusion | dense/sparse scale 정규화 필요, 백엔드별 재튜닝 |
| Dense only | 키워드·고유명사 recall 저하 |
| Sparse only | paraphrase·의미 질의 recall 저하 |
| Learned fusion | 학습 데이터·운영 복잡도 |

## 결과

### 장점

- rank-only → scale-invariant, 백엔드 교체에 robust
- OpenSearch ↔ pgvector A/B 시 fusion 로직 **재사용**
- 구현 단순 (~30 LOC)

### 단점

- absolute score 정보 손실 (reranker가 보정)
- k=60 하이퍼파라미터 — golden set으로 검증 필요

### 후속 조치

- [x] `tests/eval/test_benchmark.py` fusion golden set
- [ ] corpus별 k 튜닝
