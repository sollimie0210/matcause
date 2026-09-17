"""전체 파이프라인 데모 (T-101/102/103 연동 확인).

이슈 텍스트 입력 → Triage → 소재 분석(실 MP 조회) → 리포트 생성까지 전체 흐름을 실행한다.
LLM 은 MockLLMClient(실 Bedrock 연동 전). MP 는 .env 의 실제 키로 라이브 조회.

사용법:
  python scripts/run_pipeline_demo.py
  python scripts/run_pipeline_demo.py "임의의 이슈 텍스트"
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# .env 로드 후 mp-api 가 읽는 OS 환경변수에 키를 넣어준다
try:
    from dotenv import load_dotenv

    load_dotenv()
    # mp-api 는 MP_API_KEY OS 환경변수를 직접 참조하므로 확실히 반영
    from matcause.core.config import get_settings

    if get_settings().mp_api_key and not os.environ.get("MP_API_KEY"):
        os.environ["MP_API_KEY"] = get_settings().mp_api_key
except Exception:  # noqa: BLE001
    pass

from matcause.core.llm.mock_client import MockLLMClient
from matcause.core.models import IssueRequest
from matcause.core.pipeline import build_orchestrator
from matcause.plugins.semiconductor import SemiconductorPlugin

DEFAULT_ISSUE = (
    "고객사에서 GaN 기반 파워 소자의 특정 로트에서 누설전류가 규격 상한을 초과했다는 "
    "클레임이 접수됨. 동일 공정 조건에서 생산됐으나 소재 물성 편차가 의심됨."
)


def main() -> int:
    issue_text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ISSUE

    llm = MockLLMClient()
    plugin = SemiconductorPlugin(llm=llm)   # 실제 설정에서 MP 커넥터 빌드
    orch = build_orchestrator(plugin, llm, report_kind="OCAP")

    print("=" * 70)
    print("이슈 입력:")
    print(f"  {issue_text}")
    print("=" * 70)

    dx = orch.diagnose(IssueRequest(raw_text=issue_text))

    print(f"\n[1] Triage 분기 판단")
    print(f"    분류    : {dx.triage.category.value}")
    print(f"    확신도  : {dx.triage.confidence}")
    print(f"    근거    : {dx.triage.rationale}")
    print(f"    신호    : formulas={dx.triage.signals.get('extracted_formulas')}, "
          f"mat_kw={dx.triage.signals.get('material_keyword_count')}, "
          f"proc_kw={dx.triage.signals.get('process_keyword_count')}")

    print(f"\n[2] 분석 상태: {dx.status.value}")
    if dx.error:
        print(f"    오류: {dx.error}")

    if dx.material_finding:
        mf = dx.material_finding
        print(f"\n[3] 소재 분석 결과")
        print(f"    리스크 스코어: {mf.risk_score}/100")
        print(f"    breakdown    : {mf.breakdown}")
        print(f"    요약         : {mf.summary}")
        if mf.ranked_candidates:
            print(f"    대체 후보 랭킹:")
            for i, c in enumerate(mf.ranked_candidates, 1):
                print(f"      {i}. {c.name} (리스크 {c.score}) — {c.improvement}"
                      + (f" / {c.tradeoffs}" if c.tradeoffs else ""))

    if dx.report:
        print(f"\n[4] 최종 리포트 ({dx.report.format.value})")
        print("-" * 70)
        print(dx.report.markdown)
        print("-" * 70)

    print(f"\n총 근거(Evidence) 수: {len(dx.all_evidences())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
