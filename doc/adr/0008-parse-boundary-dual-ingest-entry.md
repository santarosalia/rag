# ADR-0008: 파싱 경계와 이중 인제스트 진입점

- **상태:** Accepted
- **날짜:** 2026-08-27
- **관련:** [PARSE_BOUNDARY.md](../PARSE_BOUNDARY.md), ADR-0002, ADR-0005

## 맥락

이전 `INGEST_BOUNDARY.md`(현재 [`PARSE_BOUNDARY.md`](../PARSE_BOUNDARY.md))는 ingest 전체(파싱·청킹·임베딩·PG 적재)를 별도 프로젝트로 빼고, 이 저장소는 retrieve/query만 남기는 그림을 그렸다.

실제로는:

- citation·그룹 필터·검색 인덱스는 **이 저장소의 PostgreSQL 스키마와 모델 버전**에 묶여 있다.
- 바깥에서 `chunks`를 직접 쓰면 embedding/Kiwi drift와 메타 누락이 난다.
- 한편 스캔 PDF·복잡 Office·도메인 OCR은 **여기 MarkItDown 한 종류로 다 감당하기 어렵다.** 그런 파싱은 외부에서 하고 싶다.

필요한 분리 지점은 ingest 전체가 아니라 **원본 → Markdown 파싱**이다.

## 결정

**적재(chunk → embed → Kiwi → PG)는 이 저장소에 둔다.** 외부와 주고받는 중간 포맷은 **Markdown**이다.

진입점 두 개:

| 경로 | 입력 | 파싱 |
|------|------|------|
| A | 원본 파일 `POST /v1/documents` | 이 저장소 **MarkItDown** |
| B | 이미 파싱된 Markdown `POST /v1/documents/parsed` | 호출측 (외부 파서) |

이후 파이프라인은 공유한다. 외부 파서는 PG에 쓰지 않고, chunk/embedding도 보내지 않는다.

`group_id`는 두 API 모두 필수 (ADR-0009). UUID가 아니어도 된다.

## 대안

| 대안 | 기각 이유 |
|------|-----------|
| Ingest 프로젝트 전면 분리 + 공유 PG write | 스키마·모델 소유권이 둘로 갈림. 메타 누락 리스크 |
| 경로 B에서 chunk JSON + embedding 수신 | 적재 품질을 호출측이 좌우. 모델 pin이 깨짐 |
| 원본 업로드만 (외부 파서 없음) | 무거운 OCR/특화 파서를 이 API 프로세스에 넣게 됨 |
| Markdown을 retrieve에 직접 전달 | 검색 계약이 PG JOIN인데 우회 경로가 생김 |

## 결과

### 장점

- 검색·citation·그룹 필터의 단일 원천 유지
- 파싱 품질이 필요한 문서는 외부로, 일반 문서는 내부 MarkItDown
- Celery 적재·재처리·삭제 정책을 한곳에서 유지 (ADR-0005)

### 단점

- 경로 A MarkItDown과 경로 B 외부 변환 품질이 달라질 수 있음 (golden set으로 맞춤)
- `/parsed`는 아직 golden-set 통합 테스트가 없다. 경로 A는 MarkItDown, 경로 B는 Markdown 패스스루.

### 후속 조치

- [x] `ingestion/parsers.py` → MarkItDown
- [x] `POST /v1/documents/parsed`
- [ ] 두 경로 golden set + retrieve citation 테스트
