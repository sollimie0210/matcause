"""공정 경로(3-B) E2E 데모 — T-122 검증.

공정 관련 이슈 텍스트를 넣어:
  1. TriageEngine 이 PROCESS 로 분류하는지
  2. SecomProcessAnalyzer 가 SECOM 실데이터로 이상 변수를 규명하는지
  3. ReportEngine 이 ProcessFinding 으로 리포트를 생성하는지
를 실제 Orchestrator 로 한 번에 확인한다.

LLM 은 오프라인 결정론 MockLLMClient 사용(네트워크/키 불필요).

사용: python scripts/run_process_e2e.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matcause.core.config import Settings
from matcause.core.llm.mock_client import MockLLMClient
from matcause.core.orchestrator import Orchestrator
from matcause.core.report_engine import ReportEngine
from matcause.core.triage import TriageEngine
from matcause.core.models import IssueRequest
from matcause.plugins.semiconductor import SemiconductorPlugin

ISSUE_TEXT = (
    "반도체 팹 공정 이슈입니다. 최근 특정 장비 챔버에서 식각(etch) 공정 후 "
    "수율(yield)이 급락했습니다. 온도·압력 센서 값이 평소와 다르게 흔들리고 "
    "설비 레시피(recipe) 변경 이력도 의심됩니다. 어떤 공정 파라미터가 불량과 "
    "관련 있는지 규명해 주세요."
)


def main() -> int:
    settings = Settings(secom_data_dir=str(ROOT / "data" / "secom"))
    llm = MockLLMClient()

    plugin = SemiconductorPlugin(settings=settings, llm=llm)
    triage = TriageEngine(plugin, llm, threshold=settings.triage_confidence_threshold)
    report_engine = ReportEngine(llm)
    orch = Orchestrator(
        plugin, triage=triage, report_engine=report_engine, report_kind="OCAP"
    )

    issue = IssueRequest(raw_text=ISSUE_TEXT)
    dx = orch.diagnose(issue)

    print("=" * 70)
    print("[E2E] 공정 경로 데모 (Triage → ProcessAnalyzer → Report)")
    print("=" * 70)
    print(f"이슈: {ISSUE_TEXT[:60]}...\n")

    t = dx.triage
    print("── 1) Triage ──")
    print(f"  category   : {t.category.value}")
    print(f"  confidence : {t.confidence}")
    print(f"  rationale  : {t.rationale}")
    print(f"  signals    : proc_kw={t.signals.get('process_keyword_count')} "
          f"mat_kw={t.signals.get('material_keyword_count')} "
          f"formula={t.signals.get('has_chemical_formula')}\n")

    print("── 2) Diagnosis 상태 ──")
    print(f"  status     : {dx.status.value}")
    if dx.error:
        print(f"  error      : {dx.error}")

    pf = dx.process_finding
    print("\n── 3) ProcessFinding ──")
    if pf is None:
        print("  (없음: 공정 경로가 실행되지 않음)")
    else:
        print(f"  유의 이상 변수 수 : {len(pf.anomalous_vars)}")
        print(f"  요약             : {pf.summary}")
        print(f"  Evidence 개수     : {len(pf.evidences)}")
        print(f"  cause_mappings    : {len(pf.cause_mappings)}개 "
              f"(미매핑 {sum(1 for v in pf.cause_mappings.values() if v.startswith('미매핑'))}개)")

    print("\n── 4) Report (OCAP) ──")
    if dx.report is None:
        print("  (리포트 생성 실패)")
    else:
        print(f"  format   : {dx.report.format.value}")
        print(f"  evidences: {len(dx.report.evidences)}")
        print("  ─ markdown ─")
        print(dx.report.markdown)

    # 검증 판정
    ok = (
        t.category.value == "PROCESS"
        and pf is not None
        and len(pf.anomalous_vars) > 0
        and dx.report is not None
        and dx.status.value == "REPORTED"
    )
    print("\n" + "=" * 70)
    print(f"E2E 판정: {'PASS ✅' if ok else 'FAIL ❌'} "
          f"(Triage=PROCESS, 이상변수>0, Report 생성, status=REPORTED)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
