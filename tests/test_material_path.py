"""T-113 / T-114: 대체 랭킹 + 소재 경로 end-to-end (mock connector, 네트워크 없음)."""

from __future__ import annotations

from matcause.core.llm.mock_client import MockLLMClient
from matcause.core.models import IssueRequest, MaterialFinding
from matcause.plugins.semiconductor.alternatives_ranker import (
    candidate_formulas_for_group,
    rank_alternatives,
)
from matcause.plugins.semiconductor.material_analyzer import (
    SemiconductorMaterialAnalyzer,
)


# ── 가짜 커넥터: 실제 MP 값과 유사한 dict 반환 ──

_MATERIALS = {
    "GaN": {
        "material_id": "mp-804", "formula_pretty": "GaN",
        "formation_energy_per_atom": -0.67, "energy_above_hull": 0.0,
        "band_gap": 1.74, "is_stable": True,
    },
    "AlN": {
        "material_id": "mp-661", "formula_pretty": "AlN",
        "formation_energy_per_atom": -1.6, "energy_above_hull": 0.0,
        "band_gap": 4.06, "is_stable": True,
    },
    "InN": {
        "material_id": "mp-22205", "formula_pretty": "InN",
        "formation_energy_per_atom": -0.15, "energy_above_hull": 0.05,
        "band_gap": 0.0, "is_stable": False,
    },
    "GaAs": {
        "material_id": "mp-2534", "formula_pretty": "GaAs",
        "formation_energy_per_atom": -0.45, "energy_above_hull": 0.0,
        "band_gap": 0.19, "is_stable": True,
    },
}


class FakeConnector:
    def __init__(self, materials=None):
        self._m = materials or _MATERIALS

    def query_summary(self, formula):
        best = self._m.get(formula)
        if best is None:
            from matcause.plugins.semiconductor.mp_connector import MpConnectorError

            raise MpConnectorError(f"no data for {formula}")
        return {
            "formula": formula, "source": "MP_API",
            "notes": ["defect-energy proxy note"],
            "materials": [best], "best": best,
        }

    def query_candidates(self, formulas):
        out = []
        for f in formulas:
            m = self._m.get(f)
            if m:
                out.append(dict(m))
        return out

    def find_alternatives(self, formula, k=5):
        return []


# ── T-113: 랭킹 ──


def test_group_shortlist_excludes_source():
    cands = candidate_formulas_for_group("III-V", exclude="GaN")
    assert "GaN" not in cands
    assert "AlN" in cands


def test_rank_alternatives_orders_by_risk():
    source = _MATERIALS["InN"]  # 불안정(E_hull 0.05, stable False) → 리스크 높음
    candidates = [_MATERIALS["GaN"], _MATERIALS["AlN"], _MATERIALS["GaAs"]]
    result = rank_alternatives(source, candidates, k=3)
    # 안정 후보들이 상위, 리스크 오름차순
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores)
    assert all(c.score == 0.0 for c in result.candidates)  # 모두 안정
    # 개선 문구/트레이드오프 존재
    top = result.candidates[0]
    assert "리스크" in top.improvement
    assert top.metrics["material_id"]


def test_rank_alternatives_computes_bandgap_tradeoff():
    source = _MATERIALS["GaN"]  # band_gap 1.74
    result = rank_alternatives(source, [_MATERIALS["AlN"]], k=1)  # AlN 4.06
    tr = result.candidates[0].tradeoffs
    assert tr and "band_gap" in tr and "증가" in tr


def test_rank_excludes_self():
    source = _MATERIALS["GaN"]
    result = rank_alternatives(source, [_MATERIALS["GaN"], _MATERIALS["AlN"]], k=5)
    names = [c.name for c in result.candidates]
    assert "GaN" not in names  # 자기 자신 제외
    assert "AlN" in names


# ── T-114: end-to-end ──


def test_analyze_end_to_end_material_path():
    analyzer = SemiconductorMaterialAnalyzer(
        connector=FakeConnector(), llm=MockLLMClient()
    )
    issue = IssueRequest(raw_text="GaN 에피층에서 누설전류 상승, 소재 물성 의심")
    finding = analyzer.analyze(issue)

    assert isinstance(finding, MaterialFinding)
    assert finding.risk_score == 0.0          # GaN 안정 → 리스크 0
    assert finding.breakdown                  # 지표 breakdown 존재
    assert finding.evidences                  # 근거 존재(추적성)
    assert finding.ranked_candidates          # 대체 후보 랭킹 존재
    # 대체 후보에 III-V 계열(AlN 등)이 포함
    alt_names = [c.name for c in finding.ranked_candidates]
    assert any(n in ("AlN", "InN", "GaAs", "InP", "AlAs", "GaP") for n in alt_names)
    assert "GaN" in finding.summary


def test_analyze_no_material_returns_empty_finding():
    analyzer = SemiconductorMaterialAnalyzer(
        connector=FakeConnector(), llm=MockLLMClient()
    )
    issue = IssueRequest(raw_text="공정 챔버 압력 이상")
    finding = analyzer.analyze(issue)
    assert finding.risk_score == 0.0
    assert not finding.ranked_candidates
    assert "식별" in finding.summary or "소재" in finding.summary


def test_analyze_mp_failure_is_honest():
    analyzer = SemiconductorMaterialAnalyzer(
        connector=FakeConnector(materials={}),  # 아무 데이터 없음
        llm=MockLLMClient(),
    )
    issue = IssueRequest(raw_text="GaN 소자 불량")
    finding = analyzer.analyze(issue)
    assert finding.risk_score == 0.0
    # 조회 실패를 정직하게 근거로 남김
    assert any(e.value is None for e in finding.evidences)
