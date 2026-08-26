# ADR-0006: OpenAI-compatible LLM API

- **상태:** Accepted
- **날짜:** 2026-08-25

## 맥락

RAG 최종 단계에서 retrieved context 기반 **답변 생성 + citation** 이 필요하다.  
Self-host LLM(vLLM/Ollama) vs API provider 선택이 필요하다.

## 결정

**OpenAI-compatible Chat Completions API**를 기본 LLM 인터페이스로 사용한다.

- `LLM_BASE_URL` + `LLM_API_KEY` env 설정
- 기본 모델: `gpt-4o-mini` ([`configs/default.yaml`](../../configs/default.yaml))
- `LLM_API_KEY` 미설정 시: retrieved context fallback 답변 (dev용)

Citation: system prompt에서 `[1]`, `[2]` 번호 매칭

## 대안

| 대안 | 기각 이유 |
|------|-----------|
| Self-host Llama/Mistral | GPU infra, ops 부담 — Phase 2+ 옵션 |
| Anthropic native SDK | vendor lock-in, OpenAI-compatible이 더 범용 |
| Retrieve-only (no LLM) | `/v1/retrieve`로 분리 제공 — generation은 optional |

## 결과

### 장점

- OpenAI / Azure OpenAI / LiteLLM / vLLM proxy **동일 코드**
- dev 환경에서 API key 없이 retrieve 테스트 가능
- latency 대부분 LLM (~23s) — 백엔드 선택과 독립

### 단점

- API 비용·rate limit
- PII가 외부 API로 전송 — prod에서 data residency 검토 필요

### 후속 조치

- [ ] self-host LLM via vLLM (동일 OpenAI-compatible endpoint)
- [ ] streaming SSE (Phase 3)
