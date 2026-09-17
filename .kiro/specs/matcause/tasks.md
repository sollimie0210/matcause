# MatCause — 구현 태스크 리스트 (우선순위 · 병렬 작업 단위)

> 문서 버전 0.1 · 2주 예선 일정 기준
> 우선순위: **P0 = 데모 필수**, **P1 = 중요**, **P2 = 여유 시**
> 각 태스크에 담당 트랙(Track)과 선행조건(Depends)을 표기. 같은 스프린트 내 다른 Track은 병렬 진행 가능.

## 역할 트랙 (병렬 분담 제안)
- **Track-CORE**: 코어 엔진(인터페이스, Triage, Orchestrator, 리포트 엔진, LLM, RAG)
- **Track-MAT**: 소재 경로(MP 커넥터, 리스크 산정, 대체 랭킹) ← 팀 핵심 강점, 인력 우선 배치
- **Track-PROC**: 공정 경로(SECOM 로더, 이상 변수 규명, 매핑)
- **Track-UI**: Streamlit 대시보드 + FastAPI 연결
- **Track-INFRA**: 저장소/설정/데이터 스크립트/AWS 셋업

---

## 스프린트 0 — 착수 (Day 1~2, 전원)

| ID | P | Track | 태스크 | Depends | 산출물 |
|---|---|---|---|---|---|
| T-000 | P0 | INFRA | ✅ 레포 초기화(pyproject, 디렉토리 스캐폴드, .env.example, README) | — | 빌드되는 빈 프로젝트 |
| T-001 | P0 | INFRA | **AWS Bedrock 접근 셋업**: 계정/리전, 모델 활성화, 자격증명 확인 | — | Bedrock 호출 성공 스모크 |
| T-002 | P0 | INFRA | Materials Project API 키 발급 + mp-api 연결 스모크 | — | MP 1건 조회 성공 |
| T-003 | P0 | INFRA | `scripts/download_secom.py` — UCI SECOM 실데이터 확보(1567×590) | — | `data/secom/*.csv` |
| T-004 | P0 | CORE | ✅ **공통 데이터 모델 확정**(models.py): Issue/Triage/Evidence/Report/Feedback/Diagnosis | — | 타입 고정 |
| T-005 | P0 | CORE | ✅ **코어 인터페이스 확정**(interfaces.py Protocol) + **LLMClient Protocol(SDK 비종속) + MockLLMClient** | T-004 | 계약 고정 → 팀 병렬 착수 신호 |

> ⛳ **게이트**: T-004/T-005 완료 = 각 트랙이 mock으로 병렬 개발 시작 가능. **(달성됨)**
> LLM은 `core.llm.base.LLMClient` Protocol 에만 의존. 개발은 `MockLLMClient`,
> 실제 Bedrock 연동은 `BedrockLLMClient`(T-100)로 교체.

---

## 스프린트 1 — 핵심 경로 (Day 3~7)

### Track-CORE
| ID | P | 태스크 | Depends | 비고 |
|---|---|---|---|---|
| T-100 | P0 | Bedrock 클라이언트 래퍼 + 프롬프트 템플릿 + JSON 파싱/폴백 | T-001,T-005 | 모델ID 설정화 |
| T-101 | P0 | ✅ TriageEngine: 규칙 신호 + LLM 결합, confidence, AMBIGUOUS 처리 | T-100 | US-A2 (MockLLM) |
| T-102 | P0 | ✅ Orchestrator: 분기 → 도메인 분석기 호출 → 리포트 → 저장 | T-005 | 전체 파이프라인 연결 |
| T-103 | P0 | ✅ ReportEngine: 템플릿 렌더 + Evidence 바인딩(추적성) + LLM 서술 | T-005 | US-D1/D2, OCAP/Gap 템플릿 포함 |
| T-104 | P0 | plugin_registry + config(pydantic-settings) | T-005 | US-G1 |

### Track-MAT (최우선 인력)
| ID | P | 태스크 | Depends | 비고 |
|---|---|---|---|---|
| T-110 | P0 | ✅ mp_connector: MPRester 조회(summary/thermo), 캐시 폴백 | T-002,T-005 | US-B1, 폴백 필수 |
| T-111 | P0 | ✅ 물성 추출: 이슈→화학식/조성/물질군 파싱 | T-100 | 정규식 우선 + MockLLM 보강 |
| T-112 | P0 | ✅ 리스크 산정: 지표 정규화·가중합(0~100)+breakdown | T-110 | US-B2, 결함E 프록시 명시 |
| T-113 | P0 | ✅ 대체 소재 랭킹: 유사공간 조회 + 정렬·트레이드오프 | T-112 | US-B3 |
| T-114 | P0 | ✅ MaterialAnalyzer로 인터페이스 구현 + Evidence 래핑 (소재 경로 3-A E2E 완성) | T-110~113 | 코어 연동 |

### Track-PROC
| ID | P | 태스크 | Depends | 비고 |
|---|---|---|---|---|
| T-120 | P1 | secom_loader: CSV 로드·결측처리·라벨정렬·불균형 처리 | T-003,T-005 | US-C1 |
| T-121 | P1 | 이상 변수 규명(통계): 그룹검정 + FDR 보정, 상위 N | T-120 | 축소 시 여기까지 |
| T-122 | P1 | ProcessAnalyzer 인터페이스 구현 + Evidence 래핑 | T-120,T-121 | 코어 연동 |

### Track-INFRA
| ID | P | 태스크 | Depends | 비고 |
|---|---|---|---|---|
| T-130 | P0 | `warm_mp_cache.py`: 데모용 MP 조회 캐시 스냅샷 생성 | T-110 | 오프라인 데모 보증 |
| T-131 | P1 | SQLite 저장소: 진단/피드백 스키마 + DAO | T-004 | US-E1 기반 |

---

## 스프린트 2 — 리포트·UI·피드백 (Day 8~11)

### Track-MAT / Track-PROC 도메인 KB & 템플릿
| ID | P | 태스크 | Depends | 비고 |
|---|---|---|---|---|
| T-200 | P0 | ✅ 리포트 템플릿(Gap Analysis / OCAP) 반도체 버전 (T-103과 함께 구현) | T-103 | US-D1 |
| T-201 | P0 | 소재-결함 KB seed(공개 문헌 인용, 출처 URL) | T-114 | 데이터 정직성 |
| T-202 | P2 | SECOM 변수→원인 매핑 테이블(YAML, 편집가능) | T-122 | US-C2, 없으면 "미매핑" 표기 |

### Track-UI
| ID | P | 태스크 | Depends | 비고 |
|---|---|---|---|---|
| T-210 | P0 | ✅ FastAPI 라우트(/diagnose,/diagnosis,/health) | T-102 | API 계층 (feedback은 T-220) |
| T-211 | P0 | ✅ Streamlit 대시보드: 입력→분기(확신도)→근거→리포트 | T-210 | US-F1 (피드백은 T-220) |
| T-212 | P0 | 근거 시각화: 리스크 바, 지표 breakdown, 대체후보 표 | T-211,T-114 | 데모 임팩트 |
| T-213 | P1 | 경로 override UI + AMBIGUOUS 양경로 표시 | T-211,T-101 | US-A2 |

### Track-CORE
| ID | P | 태스크 | Depends | 비고 |
|---|---|---|---|---|
| T-220 | P1 | 피드백 로거: 저장 + 리포트 항목 승인/수정/반려 | T-131,T-103 | US-E1 |
| T-221 | P1 | RAG: 임베딩(Titan)+FAISS/sqlite-vec 인덱스, 프롬프트 주입 | T-220,T-100 | US-E2 |

---

## 스프린트 3 — 통합·검증·데모 (Day 12~14)

| ID | P | Track | 태스크 | Depends | 비고 |
|---|---|---|---|---|---|
| T-300 | P0 | ALL | E2E 통합: 소재 경로 풀 플로우(입력→리포트→피드백) | 스프린트1~2 | 데모 시나리오 A |
| T-301 | P1 | ALL | E2E 통합: 공정 경로 플로우 | T-122,T-211 | 데모 시나리오 B |
| T-302 | P0 | MAT | 실 데이터 검증: MP 인용값 = 리포트 표기값 일치 확인 | T-300 | 정직성 검증 |
| T-303 | P0 | INFRA | 오프라인 데모 리허설(캐시·키 없이 소재 경로 동작) | T-130,T-300 | 데모 안전장치 |
| T-304 | P0 | ALL | 데모 시나리오 스크립트 + 발표용 리포트 예시 3건 | T-300 | 예선 제출물 |
| T-305 | P1 | CORE | 핵심 단위테스트(Triage/Report/폴백) | 스프린트1 | 회귀 방지 |
| T-306 | P2 | UI | UX 다듬기, 로딩/에러 상태, 문구 | T-211 | 여유 시 |

---

## 우선순위 요약 (한눈에)

**반드시(P0) — 이게 안 되면 데모 불가**
- 착수: T-000~005
- 소재 경로 전체: T-110~114, 캐시 T-130
- 코어: T-100~104, 리포트 T-200/T-201/T-103
- UI 풀플로우: T-210~212
- 통합·검증·데모: T-300, T-302~304

**중요(P1) — 완성도/설득력**
- 공정 경로(통계): T-120~122
- 피드백/RAG: T-131, T-220, T-221
- override UI: T-213, 공정 E2E: T-301, 테스트: T-305

**여유 시(P2) — 축소 가능**
- SECOM 원인 매핑: T-202
- UX 다듬기: T-306

---

## 스코프 축소 규칙 (일정 압박 시)
1. **3-B(공정)를 통계까지만** 남기고 ML·매핑(T-202) 드롭 → 인터페이스는 유지되어 UI/리포트 정상 동작.
2. **RAG(T-221) 드롭**, 피드백 저장(T-220)만 유지 → "기록됨" 데모는 성립.
3. React 미착수(예선은 Streamlit 확정).
4. **절대 사수**: 소재 경로(3-A) 완성도 + 근거 추적성 + 오프라인 데모.

## 병렬화 체크리스트
- Day2 게이트(T-004/005) 후 CORE·MAT·PROC·UI 4트랙 동시 진행.
- UI는 초기엔 mock 응답으로 화면 구성 → API 준비되면 교체.
- MAT는 T-130 캐시 확보 후 네트워크 독립적으로 개발.
