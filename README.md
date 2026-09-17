# MatCause

소재·공정 결함 원인 판별 및 대응 피드백 에이전트.

불량/클레임이 **소재 물성 한계**인지 **공정 조건 문제**인지 자동 분기하고,
공개 데이터(Materials Project, UCI SECOM, 공개 문헌) 기반 근거와 대응안 초안을
리포트로 생성한다.

> 설계/요구/태스크 문서: `.kiro/specs/matcause/`
> (requirements.md · design.md · tasks.md)

## 아키텍처 개요

코어 엔진(도메인 무지)과 반도체 도메인 플러그인을 분리한다. 새 산업은 플러그인
추가만으로 확장 가능하다 (`plugins/<industry>/`).

```
src/matcause/
├─ core/        # Triage, Orchestrator, ReportEngine, Feedback, RAG, LLM(Bedrock), Registry
├─ plugins/
│  └─ semiconductor/  # MP 커넥터, SECOM 로더, KB, 리포트 템플릿
├─ api/         # FastAPI
└─ ui/          # Streamlit 대시보드
```

## 요구 환경

- **소재/공정/RAG 트랙: Python 3.12 필수.** pymatgen · faiss-cpu · scikit-learn ·
  scipy 등은 3.12 휠은 제공되지만 최신 3.14 휠은 아직 없다. 이 트랙 작업자는
  반드시 3.12 가상환경을 사용한다.
- 코어/UI 트랙만 다룬다면 3.12+ 어느 버전이든 무방하다(코어 의존성은 3.14 휠도 존재).
- AWS Bedrock 접근 권한 (Claude 계열 모델 활성화)
- Materials Project API 키

### 검증된 가상환경 (OneDrive 밖, 로컬 경로)

| 용도 | 경로 | Python | 설치 extras |
|---|---|---|---|
| 소재/공정/RAG 트랙 (권장 기본) | `C:\Users\<사용자>\matcause_venv312` | 3.12 | `materials,process,rag,dev` |
| 코어/UI 전용 | `C:\Users\<사용자>\matcause_venv` | 3.14 | `dev` |

두 venv 모두 `pytest` 통과를 확인했다. 소재/공정 패키지가 필요하면 3.12 venv를 쓴다.

## 설치

> ⚠️ **OneDrive 주의**: 이 폴더가 OneDrive 동기화 경로에 있으면 `.venv`를 폴더
> 안에 만들 때 동기화 프로세스가 파일을 잠가 `pip install`이 `WinError 32`로
> 실패할 수 있다. 가상환경은 **OneDrive 밖 경로**에 만들 것을 권장한다.
> 예: `python -m venv C:\Users\<사용자>\matcause_venv`

```powershell
# 소재/공정 트랙용 3.12 가상환경 (OneDrive 밖 경로)
py -3.12 -m venv C:\Users\$env:USERNAME\matcause_venv312
& "C:\Users\$env:USERNAME\matcause_venv312\Scripts\Activate.ps1"

# 코어만 설치
pip install -e .

# 트랙별 선택 설치
pip install -e ".[materials]"   # 소재 경로 (mp-api, pymatgen)
pip install -e ".[process]"     # 공정 경로 (scikit-learn, scipy)
pip install -e ".[rag]"         # RAG (faiss-cpu)
pip install -e ".[all,dev]"     # 전체 + 개발 도구
```

> uv 사용 시: `uv venv` → `uv pip install -e ".[all,dev]"`

## 환경변수

```powershell
Copy-Item .env.example .env
# .env 를 열어 AWS_REGION, BEDROCK_MODEL_ID, MP_API_KEY 등을 채운다.
```

`.env`, API 키는 절대 커밋하지 않는다 (`.gitignore`로 차단됨).

## 데이터 준비

```powershell
python scripts/download_secom.py   # UCI SECOM 실데이터 (T-003)
python scripts/warm_mp_cache.py    # 데모용 MP 캐시 (T-130, 오프라인 데모 대비)
```

## 실행

```powershell
# 데모 대시보드 (권장: 전체 파이프라인을 한 화면에서 확인)
C:\Users\<사용자>\matcause_venv312\Scripts\python.exe -m streamlit run src/matcause/ui/app.py
# → http://localhost:8501  (이슈 입력 → 분기 판단 → 근거 → 리포트)

# API (선택: 외부 연동/React 대비)
matcause-api                       # → http://127.0.0.1:8000  (/health, /docs, POST /diagnose)

# CLI 데모 (파이프라인 전 과정을 터미널에서 확인)
python scripts/run_pipeline_demo.py "GaN 소자 누설전류 이상, 소재 물성 의심"
```

> `.env` 에 `MP_API_KEY` 가 있으면 실제 Materials Project 데이터로 조회한다.
> 없으면 캐시/오프라인 모드로 폴백한다. LLM 은 현재 MockLLMClient(실 Bedrock 연동은 T-100).

## 테스트

```powershell
pytest
```

## 현재 상태 (스프린트 0 / T-000)

프로젝트 스캐폴드 완료. 코어 인터페이스와 도메인 플러그인 골격이 잡혀 있고
`/health`, Streamlit 화면 골격, 스캐폴드 테스트가 동작한다. 각 트랙(CORE/MAT/PROC/UI)은
`tasks.md` 기준으로 병렬 착수 가능하다.

## 데이터 정직성

실존 공개 데이터만 사용한다. Materials Project가 결함 형성 에너지 직접값을 제공하지
않는 경우 안정성 프록시(energy above hull 등)로 대체하고 리포트에 한계를 명시한다.
SECOM 변수는 익명화되어 있어 통계적 이상 규명까지만 하고, 물리 원인 매핑은 근거가
있을 때만 표기한다.

## 리포트 PDF & 한글 폰트

고객사 제출용 리포트는 순수 파이썬(xhtml2pdf, 외부 프로그램 불필요)으로 PDF 변환된다.
한글이 깨지지 않도록 **Noto Sans KR**(SIL Open Font License 1.1, 재배포 가능)을
`assets/fonts/` 에 포함해 `@font-face` 로 등록한다. 시스템 폰트 경로에 의존하지 않으므로
팀원/발표 노트북 어디서든 동일하게 렌더된다.

- 폰트 파일: `assets/fonts/NotoSansKR-Regular.ttf`, `NotoSansKR-Bold.ttf`
- 라이선스: `assets/fonts/OFL.txt`
- 폰트 경로 재정의: 환경변수 `MATCAUSE_FONT_DIR`
