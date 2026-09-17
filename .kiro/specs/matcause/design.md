# MatCause — 기술 설계 문서 (Technical Design)

> 문서 버전 0.1 · 예선 제출용
> 대상 독자: 개발팀 (백엔드/소재/공정/프론트 담당)

## 1. 설계 원칙

1. **코어 ↔ 도메인 분리**: 코어 엔진은 "이슈를 받아 분기하고, 도메인 분석기를 호출하고, 리포트를 만들고, 피드백을 저장"하는 오케스트레이터일 뿐 반도체 지식을 모른다. 반도체 지식은 전부 플러그인 안에 있다.
2. **인터페이스 우선(Contract-first)**: 코어는 추상 인터페이스(Protocol)에만 의존한다. 팀원이 병렬로 작업하려면 인터페이스를 먼저 확정한다.
3. **데이터 정직성**: 모든 근거는 출처 ID를 가진 `Evidence` 객체로 흐른다. 값이 없으면 "없음"을 명시한다. 합성 금지.
4. **폴백 가능**: 외부 API/LLM 실패 시에도 데모가 끝까지 돈다(캐시·규칙 기반 폴백).
5. **점진적 스코프**: 소재 경로(3-A)는 완성도 최상, 공정 경로(3-B)와 RAG(5)는 인터페이스만 맞추면 나중에 채울 수 있게.

---

## 2. 기술 스택 결정

| 레이어 | 선택 | 근거 / 대안 |
|---|---|---|
| 백엔드 | **Python 3.11 + FastAPI** | 요청대로. 소재/데이터 생태계(pymatgen, pandas, scikit-learn)와 자연스럽게 맞음 |
| 프론트 | **Streamlit** (예선), React는 후순위 | 2주 일정에서 데이터 대시보드를 가장 빠르게 구현. 단계별 흐름 표현에 충분. React는 예선 통과 후 고려 |
| LLM | **AWS Bedrock** (Claude 3.5 Sonnet 우선, Haiku 폴백) | 요구사항. boto3 `bedrock-runtime` 사용. 모델 ID는 설정으로 추상화 |
| 소재 데이터 | **mp-api (MPRester)** + pymatgen | Materials Project 공식 클라이언트. thermo/summary 엔드포인트 |
| 공정 데이터 | **UCI SECOM CSV** + pandas/scikit-learn | 1567×590, Pass/Fail. 로컬/S3 로드 |
| 벡터 검색/RAG | **경량: SQLite + FAISS(또는 sqlite-vec) + Bedrock Titan Embeddings** | 별도 벡터 DB 인프라 없이 파일 기반. 예선 규모(수십~수백 사례)에 충분. 대안: Chroma(로컬). 무거운 pgvector/OpenSearch는 예선 스코프 밖 |
| 저장소 | **SQLite** (진단 기록, 피드백 KB) | 설정 없이 즉시 사용. 마이그레이션 부담 없음 |
| 설정/비밀 | pydantic-settings + .env | NFR-5 |
| 패키지 | uv 또는 pip + venv | Windows 환경 고려, uv 권장 |

### 왜 Streamlit인가 (트레이드오프)
- 장점: 백엔드 로직 재사용, 표/차트/파일 업로드 기본 제공, 배포 간단.
- 단점: 세밀한 UX 커스터마이징 한계.
- 결론: 예선은 "흐름과 근거"를 보여주는 게 핵심 → Streamlit. FastAPI는 코어 로직을 HTTP로도 노출해 향후 React/외부 연동 대비.

> 참고: 아래 검색으로 확인한 데이터 제약을 설계에 반영함.
> - SECOM: 1567 records, 590 anonymized features, ~104 fails (약 1:14 불균형). 변수 익명 → 물리 원인 직접 매핑 불가. ([UCI SECOM](http://archive.ics.uci.edu/ml/datasets/SECOM))
> - Materials Project: thermo 엔드포인트로 formation energy 등 조회 가능하나, 일반적 결함 형성 에너지 직접값은 본 DB 표준 필드가 아님 → energy above hull 등 안정성 프록시 사용. ([MP Docs](https://docs.materialsproject.org/downloading-data/using-the-api/querying-data))
> 위 출처 내용은 라이선스 준수를 위해 재구성함.

---

## 3. 전체 아키텍처

```
┌───────────────────────────────────────────────────────────────┐
│                         Web UI (Streamlit)                     │
│   입력 → 분기표시 → 근거표시 → 리포트 → 피드백                    │
└───────────────┬───────────────────────────────────────────────┘
                │ (HTTP, 또는 직접 import)
┌───────────────▼───────────────────────────────────────────────┐
│                       FastAPI (API 계층)                        │
│  POST /diagnose  GET /diagnosis/{id}  POST /feedback  ...       │
└───────────────┬───────────────────────────────────────────────┘
                │
┌───────────────▼───────────────────────────────────────────────┐
│                     CORE ENGINE (도메인 무지)                    │
│  ┌──────────┐ ┌───────────┐ ┌──────────────┐ ┌──────────────┐  │
│  │ Triage   │ │ Orchestr- │ │ Report       │ │ Feedback /   │  │
│  │ Engine   │ │ ator      │ │ Template Eng │ │ KB Logger    │  │
│  └────┬─────┘ └─────┬─────┘ └──────┬───────┘ └──────┬───────┘  │
│       │             │              │                │          │
│  ┌────▼─────────────▼──────────────▼────────────────▼───────┐  │
│  │      LLM Client (Bedrock)   │   Plugin Registry           │  │
│  └──────────────────────────────┬──────────────────────────┘  │
└─────────────────────────────────┼─────────────────────────────┘
                                   │  implements interfaces
┌──────────────────────────────────▼────────────────────────────┐
│           DOMAIN PLUGIN: semiconductor                          │
│  ┌───────────────┐ ┌──────────────┐ ┌────────────────────────┐ │
│  │ MaterialAnalyzer│ ProcessAnalyzer│ DomainKnowledgeBase      │ │
│  │ (MP connector)  │ (SECOM loader) │ (소재-결함 KB, 매핑)      │ │
│  └───────────────┘ └──────────────┘ └────────────────────────┘ │
│  ReportTemplate (Gap Analysis / OCAP)                           │
└─────────────────────────────────────────────────────────────────┘
        │                    │
   Materials Project     UCI SECOM CSV
   API (mp-api)          (local / S3)
```

---

## 4. 디렉토리 구조

```
matcause/
├─ pyproject.toml
├─ .env.example
├─ README.md
├─ data/
│  ├─ secom/                    # UCI SECOM 원본 CSV (다운로드 스크립트로 확보)
│  └─ cache/                    # MP 조회 캐시 스냅샷(폴백용)
├─ src/matcause/
│  ├─ core/                     # ── 도메인 무지 코어 ──
│  │  ├─ models.py              # IssueRequest, TriageResult, Evidence, Report, Feedback ...
│  │  ├─ interfaces.py          # Protocol: DomainPlugin, MaterialAnalyzer, ProcessAnalyzer, KnowledgeBase, ReportTemplate
│  │  ├─ triage.py              # TriageEngine (규칙 신호 + LLM)
│  │  ├─ orchestrator.py        # 분기→분석기 호출→리포트→피드백 조율
│  │  ├─ report_engine.py       # 템플릿 렌더링(엔진), 근거 바인딩
│  │  ├─ feedback.py            # 피드백 로깅 + KB 기록
│  │  ├─ rag.py                 # 경량 벡터 검색(임베딩 인덱스)
│  │  ├─ llm/
│  │  │  ├─ bedrock_client.py   # boto3 bedrock-runtime 래퍼
│  │  │  └─ prompts.py          # 프롬프트 템플릿(모델 독립)
│  │  ├─ plugin_registry.py     # 플러그인 등록/조회
│  │  └─ config.py              # pydantic-settings
│  ├─ plugins/
│  │  └─ semiconductor/         # ── 반도체 도메인 플러그인 ──
│  │     ├─ __init__.py         # register(): DomainPlugin 구현체 노출
│  │     ├─ material_analyzer.py# MP 커넥터 + 리스크 산정 + 대체 랭킹
│  │     ├─ mp_connector.py     # mp-api 호출 + 캐시 폴백
│  │     ├─ process_analyzer.py # SECOM 로더 + 이상 변수 규명
│  │     ├─ secom_loader.py     # CSV 로드/전처리/불균형 처리
│  │     ├─ knowledge_base.py   # 소재-결함 KB, 변수→원인 매핑
│  │     ├─ report_templates.py # Gap Analysis / OCAP 템플릿
│  │     └─ resources/          # KB seed(공개 문헌 인용), 매핑 테이블(YAML)
│  ├─ api/
│  │  ├─ main.py                # FastAPI 앱
│  │  └─ routes.py              # /diagnose /feedback ...
│  └─ ui/
│     └─ app.py                 # Streamlit 대시보드
├─ scripts/
│  ├─ download_secom.py         # UCI에서 SECOM 다운로드
│  └─ warm_mp_cache.py          # 데모용 MP 조회 캐시 생성
└─ tests/
   ├─ test_triage.py
   ├─ test_material_analyzer.py
   └─ test_report_engine.py
```

---

## 5. 코어 인터페이스 (Contract-first)

```python
# core/interfaces.py  (요약)
from typing import Protocol
from .models import (IssueRequest, MaterialFinding, ProcessFinding,
                     Report, Evidence, RankedCandidate)

class MaterialAnalyzer(Protocol):
    def analyze(self, issue: IssueRequest) -> MaterialFinding: ...
    # MaterialFinding: risk_score, per-metric breakdown, evidences[], ranked_candidates[]

class ProcessAnalyzer(Protocol):
    def analyze(self, issue: IssueRequest) -> ProcessFinding: ...
    # ProcessFinding: anomalous_vars[], stats, evidences[], cause_mappings[]

class KnowledgeBase(Protocol):
    def search(self, query: str, k: int) -> list[Evidence]: ...
    def add_feedback(self, feedback) -> None: ...

class ReportTemplate(Protocol):
    def render(self, finding, issue: IssueRequest, refs: list[Evidence]) -> Report: ...

class DomainPlugin(Protocol):
    name: str
    def material_analyzer(self) -> MaterialAnalyzer: ...
    def process_analyzer(self) -> ProcessAnalyzer: ...
    def knowledge_base(self) -> KnowledgeBase: ...
    def report_template(self, kind: str) -> ReportTemplate: ...
    def triage_signals(self, issue: IssueRequest) -> dict: ...  # 도메인 키워드/규칙
```

핵심: 코어의 `Orchestrator`, `TriageEngine`, `ReportEngine`은 위 Protocol만 안다. `semiconductor` 플러그인이 이를 구현한다. 새 산업은 새 플러그인 디렉토리를 추가해 `DomainPlugin`을 구현하면 끝.

### 공통 데이터 모델 (핵심 필드)
```python
Evidence: id, source_type("MP"|"SECOM"|"LITERATURE"|"FEEDBACK"), source_ref, value, unit, note, url
IssueRequest: id, raw_text, attachments[], parsed_specs{}, created_at
TriageResult: category("MATERIAL"|"PROCESS"|"AMBIGUOUS"), confidence, rationale, signals{}
Report: id, cause, evidences[], recommended_actions[], recommended_experiments[], sources[], format("GAP"|"OCAP"), markdown
Feedback: id, diagnosis_id, field, original, corrected, reason, created_at
```

---

## 6. 주요 플로우 상세

### 6.1 Triage (US-A2)
1. `triage_signals()`로 도메인 규칙 신호 수집(키워드: 조성/화학식/밴드갭 → material; 센서/수율/설비/장비ID → process; 전기특성 수치 파싱).
2. 규칙 신호 + 이슈 텍스트를 Bedrock 프롬프트에 주입 → 구조화 JSON(category, confidence, rationale) 응답.
3. 규칙 점수와 LLM 확신도를 결합(가중 평균). 임계값 미만이면 `AMBIGUOUS`.
4. RAG로 과거 유사 사례를 주입해 분류 품질 보정.
5. 사용자 override 허용.

### 6.2 소재 경로 (3-A, US-B1~B3) — 최우선
1. 이슈에서 화학식/조성/물질군 추출(LLM + 정규식).
2. `mp_connector`가 MPRester로 `summary`/`thermo` 조회: formation_energy_per_atom, energy_above_hull, band_gap, density, symmetry 등.
3. **결함 형성 에너지 직접값 부재** → energy_above_hull(안정성), 다형체 상대에너지 등 프록시로 리스크 산정하고 리포트에 한계 명시. 관련 공개 문헌 인용을 KB에서 첨부.
4. 리스크 스코어 = 지표별 정규화값의 가중합(0~100), breakdown 제공.
5. 유사 조성/화학공간에서 대체 후보 조회 → 지표 기준 랭킹, 개선폭·트레이드오프 계산.
6. 모든 수치는 `Evidence(source_type="MP", source_ref=mp-id, url=...)`로 래핑.
7. API 실패 시 `data/cache` 스냅샷 폴백(출처·시점 표기).

### 6.3 공정 경로 (3-B, US-C1~C2) — 축소 가능
1. `secom_loader`가 CSV 로드(1567×590), 결측 처리, Pass/Fail(-1/+1) 라벨 정렬.
2. 이상 변수 규명:
   - 통계: Pass vs Fail 그룹 간 검정(Welch t-test / Mann-Whitney), 다중검정 보정(FDR).
   - ML: 불균형 처리(class_weight 또는 SMOTE) 후 트리 기반 모델의 feature importance / permutation importance.
   - 두 신호를 종합해 상위 N개 이상 변수 선정.
3. 변수→원인 매핑: SECOM 변수는 익명 → `resources/secom_mapping.yaml`(사용자 편집)로만 매핑. 없으면 "통계 이상만 확인(원인 미매핑)"으로 정직 표기.
4. 결과를 `Evidence(source_type="SECOM")`로 래핑.

> 축소 시나리오: 시간 부족하면 3-B는 (1)+(2)-통계만 제공하고 ML/매핑은 P2로 남긴다. 인터페이스는 유지하므로 UI/리포트는 그대로 동작.

### 6.4 리포트 (4, US-D1~D2)
1. 경로별 Finding + 근거 Evidence 목록 + RAG 참고사례를 `ReportTemplate.render()`에 전달.
2. Gap Analysis(요구 스펙 vs 현재 능력 격차) 또는 OCAP(원인→조치→검증) 포맷으로 렌더.
3. LLM은 근거 목록을 받아 서술을 생성하되, 수치는 Evidence에서 그대로 인용(환각 방지: "제공된 근거 외 수치 생성 금지" 프롬프트 제약).
4. 각 주장에 Evidence ID를 바인딩 → UI에서 클릭 시 원본 표시(추적성).
5. Markdown 내보내기.

### 6.5 피드백 & RAG (5, US-E1~E2)
1. 사용자가 리포트 항목 승인/수정/반려 → `Feedback` 저장(SQLite).
2. 피드백·확정 리포트를 임베딩(Bedrock Titan) → FAISS/sqlite-vec 인덱스에 추가.
3. 다음 이슈에서 유사 사례를 검색해 Triage/리포트 프롬프트에 주입, 리포트에 "참고 사례"로 표기.

---

## 7. LLM (Bedrock) 설계
- `bedrock_client.py`: `boto3.client("bedrock-runtime")` 래퍼. 모델 ID·리전 설정 주입, 재시도/타임아웃, JSON 응답 파싱, 실패 시 규칙 기반 폴백 훅.
- `prompts.py`: Triage/추출/리포트 프롬프트를 모델 독립 템플릿으로. 시스템 프롬프트에 "근거 밖 수치 생성 금지, 불확실하면 불확실하다고 답할 것" 명시.
- 모델: 기본 Claude 3.5 Sonnet, 비용/속도용 Haiku 폴백. 임베딩: Titan Text Embeddings.
- 자격증명: `.env`(AWS_REGION, 모델 IDs) + 표준 AWS 자격증명 체인. 키 커밋 금지.

## 8. API 설계 (FastAPI)
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/diagnose` | 이슈 제출 → TriageResult + (자동/선택) 경로 분석 시작 |
| GET | `/diagnosis/{id}` | 진단 상태·결과·리포트 조회 |
| POST | `/diagnosis/{id}/override` | 경로 수동 지정 |
| POST | `/feedback` | 리포트 피드백 저장 |
| GET | `/materials/search` | (내부) MP 조회 프록시 |
| GET | `/health` | 헬스체크 |

## 9. 테스트 전략
- 코어 단위테스트: Triage 결합 로직, ReportEngine 근거 바인딩, 폴백 경로(외부 mock).
- 플러그인: MP 커넥터는 캐시 fixture로, SECOM 분석은 실제 데이터 샘플로 검증.
- 회귀: 저장된 예시 이슈 → 기대 category/리포트 섹션 존재 확인.
- (요청 없으면 테스트는 최소로. 위는 권장 범위.)

## 10. 배포 & 실행
- 로컬: `uv sync` → `uvicorn matcause.api.main:app` + `streamlit run src/matcause/ui/app.py`.
- 데이터: `scripts/download_secom.py`, `scripts/warm_mp_cache.py` 선실행.
- 데모 안전장치: 네트워크/키 없이도 캐시로 소재 경로 시연 가능.

## 11. 확장 시나리오(다른 산업)
- 새 플러그인 디렉토리 `plugins/<industry>/` 추가 → `DomainPlugin` 구현 → `plugin_registry`에 등록.
- 코어·UI·리포트 엔진 수정 없이 새 도메인 분석기/KB/템플릿만 교체.
