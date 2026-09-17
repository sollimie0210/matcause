"""T-101 / T-102 / T-103: Triage, ReportEngine, Orchestrator 통합 (mock, 네트워크 없음)."""

from __future__ import annotations

from matcause.core.llm.mock_client import MockLLMClient
from matcause.core.models import (
    DiagnosisStatus,
    IssueRequest,
    MaterialFinding,
    TriageCategory,
)
from matcause.core.orchestrator import Orchestrator
from matcause.core.report_engine import ReportEngine
from matcause.core.triage import TriageEngine
from matcause.plugins.semiconductor import SemiconductorPlugin
from matcause.plugins.semiconductor.material_analyzer import (
    SemiconductorMaterialAnalyzer,
)

from tests.test_material_path import FakeConnector


# ── 테스트용 플러그인: 가짜 커넥터를 쓰는 소재 분석기 주입 ──


class FakePlugin(SemiconductorPlugin):
    def __init__(self, llm):
        super().__init__(llm=llm)
        self._fake_conn = FakeConnector()

    def material_analyzer(self):
        return SemiconductorMaterialAnalyzer(connector=self._fake_conn, llm=self._llm)


# ── T-101: Triage ──


def test_triage_material_from_formula_and_keywords():
    llm = MockLLMClient()
    plugin = FakePlugin(llm)
    engine = TriageEngine(plugin, llm, threshold=0.6)
    result = engine.classify(
        IssueRequest(raw_text="GaN 에피층 소재 물성 이상으로 누설전류 상승")
    )
    assert result.category is TriageCategory.MATERIAL
    assert result.confidence >= 0.6
    assert "extracted_formulas" in result.signals


def test_triage_process_from_keywords():
    llm = MockLLMClient()
    plugin = FakePlugin(llm)
    engine = TriageEngine(plugin, llm, threshold=0.6)
    result = engine.classify(
        IssueRequest(raw_text="식각 공정 챔버 압력과 온도 이상으로 수율 저하")
    )
    assert result.category is TriageCategory.PROCESS


def test_triage_low_confidence_becomes_ambiguous():
    llm = MockLLMClient()
    plugin = FakePlugin(llm)
    engine = TriageEngine(plugin, llm, threshold=0.95)  # 임계값 높임
    result = engine.classify(IssueRequest(raw_text="원인을 잘 모르겠는 애매한 현상"))
    assert result.category is TriageCategory.AMBIGUOUS


# ── T-103: ReportEngine ──


def test_report_engine_builds_ocap_with_evidence():
    llm = MockLLMClient()
    plugin = FakePlugin(llm)
    finding = plugin.material_analyzer().analyze(
        IssueRequest(raw_text="GaN 소재 물성 이슈")
    )
    engine = ReportEngine(llm)
    template = plugin.report_template("OCAP")
    report = engine.build(template, finding, IssueRequest(raw_text="GaN 소재 물성 이슈"), finding.evidences)
    assert report.cause
    assert report.markdown
    assert "요약" in report.markdown  # LLM 서술 보강
    assert "근거" in report.markdown  # 추적성 섹션


# ── T-102: Orchestrator end-to-end ──


def test_orchestrator_full_pipeline_material():
    llm = MockLLMClient()
    plugin = FakePlugin(llm)
    orch = Orchestrator(
        plugin,
        triage=TriageEngine(plugin, llm),
        report_engine=ReportEngine(llm),
    )
    dx = orch.diagnose(IssueRequest(raw_text="GaN 에피층 소재 물성 이상, 누설전류 상승"))

    assert dx.status is DiagnosisStatus.REPORTED
    assert dx.triage.category is TriageCategory.MATERIAL
    assert isinstance(dx.material_finding, MaterialFinding)
    assert dx.report is not None
    assert dx.report.markdown
    # 근거 추적성: 진단 전체 근거가 모임
    assert dx.all_evidences()


def test_orchestrator_override_forces_path():
    llm = MockLLMClient()
    plugin = FakePlugin(llm)
    orch = Orchestrator(
        plugin,
        triage=TriageEngine(plugin, llm),
        report_engine=ReportEngine(llm),
    )
    # 텍스트는 공정처럼 보여도 override 로 소재 경로 강제
    dx = orch.diagnose(
        IssueRequest(raw_text="공정 챔버 이상"), override=TriageCategory.MATERIAL
    )
    assert dx.triage.category is TriageCategory.MATERIAL
    assert dx.triage.confidence == 1.0
    assert "수동 지정" in dx.triage.rationale
