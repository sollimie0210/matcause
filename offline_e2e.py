import os, io, sys
os.environ["OFFLINE_MODE"] = "true"
os.environ["MP_API_KEY"] = ""          # 네트워크 절대 불가 강제
sys.stdout.reconfigure(encoding="utf-8")

from matcause.core.llm.mock_client import MockLLMClient
from matcause.core.models import IssueRequest, DiagnosisStatus
from matcause.core.pipeline import build_orchestrator
from matcause.plugins.semiconductor import SemiconductorPlugin

llm = MockLLMClient()
plugin = SemiconductorPlugin(llm=llm)
orch = build_orchestrator(plugin, llm, report_kind="OCAP")

scenarios = {
    "GaN": "GaN 기반 파워 소자 로트에서 누설전류 규격 초과, 소재 물성 편차 의심.",
    "GaAs": "GaAs 기반 파워 소자(고전압 인버터) 누설전류 규격 초과, 소재 물성 적합성 의심.",
}
results = {}
for name, text in scenarios.items():
    dx = orch.diagnose(IssueRequest(raw_text=text))
    mf = dx.material_finding
    top = mf.ranked_candidates[0] if mf and mf.ranked_candidates else None
    results[name] = dict(
        status=dx.status.value,
        category=dx.triage.category.value,
        risk=mf.risk_score if mf else None,
        n_alts=len(mf.ranked_candidates) if mf else 0,
        top=top.name if top else None,
        top_suit=(top.metrics.get("suitability") if top else None),
        has_report=dx.report is not None,
        n_evidence=len(dx.all_evidences()),
    )

print("OFFLINE_E2E_RESULTS")
for k, v in results.items():
    print(k, v)

ok = all(
    r["status"] == "REPORTED" and r["has_report"] and r["risk"] is not None
    for r in results.values()
)
print("ALL_REPORTED_OFFLINE:", ok)
