"""Orchestrator — 이슈 → 분기 → 도메인 분석 → 리포트 조율 (T-102).

코어의 진입점. 도메인 Protocol(DomainPlugin)과 LLMClient 에만 의존한다.
전체 흐름:
  1. IssueRequest 접수 → Diagnosis(PENDING)
  2. TriageEngine 분류 → TRIAGED (MATERIAL / PROCESS / AMBIGUOUS)
  3. 분기별 도메인 분석기 호출 → ANALYZING → finding
     - AMBIGUOUS: 소재 경로를 우선 실행(팀 핵심 강점 3-A). 필요 시 확장.
  4. ReportEngine 으로 리포트 생성 → REPORTED
  5. (선택) store 에 저장

사용자 override(경로 수동 지정)는 diagnose(..., override=...) 로 지원한다(US-A2.5).
"""

from __future__ import annotations

from typing import Callable

from .interfaces import DomainPlugin
from .models import (
    Diagnosis,
    DiagnosisStatus,
    IssueRequest,
    MaterialFinding,
    ProcessFinding,
    Report,
    TriageCategory,
    TriageResult,
)

# diagnose() 의 on_step 콜백에 전달되는 단계 이름. UI(app.py)는 이를 사용자용
# 문구("🔎 1/3 이슈 분석 중…" 등)로 매핑한다. 콜백은 실제 각 단계 시작 직전에
# 호출되므로, 오래 걸리는 실제 작업(Triage LLM 호출, MP/SECOM 조회, 리포트
# LLM 서술)과 동기화된 진행 상황을 보여준다(가짜 딜레이가 아님).
class DiagnoseStep:
    TRIAGE = "triage"
    ANALYZE = "analyze"
    REPORT = "report"


OnStepCallback = Callable[[str], None]


class Orchestrator:
    def __init__(
        self,
        plugin: DomainPlugin,
        triage=None,
        report_engine=None,
        store=None,
        report_kind: str = "OCAP",
    ) -> None:
        self._plugin = plugin
        self._triage = triage
        self._report_engine = report_engine
        self._store = store
        self._report_kind = report_kind

    def diagnose(
        self,
        issue: IssueRequest,
        override: TriageCategory | None = None,
        on_step: OnStepCallback | None = None,
    ) -> Diagnosis:
        def notify(step: str) -> None:
            if on_step is not None:
                try:
                    on_step(step)
                except Exception:  # noqa: BLE001 - UI 콜백 오류가 진단을 막지 않음
                    pass

        dx = Diagnosis(issue=issue)

        # 1) Triage (override 우선)
        notify(DiagnoseStep.TRIAGE)
        if override is not None:
            dx.triage = TriageResult(
                category=override, confidence=1.0, rationale="사용자 수동 지정"
            )
        else:
            dx.triage = self._triage.classify(issue)
        dx.touch(DiagnosisStatus.TRIAGED)

        # 2) 경로 분석
        notify(DiagnoseStep.ANALYZE)
        dx.touch(DiagnosisStatus.ANALYZING)
        try:
            finding = self._run_path(issue, dx.triage.category)
        except Exception as exc:  # noqa: BLE001
            dx.error = f"분석 실패: {exc}"
            dx.touch(DiagnosisStatus.FAILED)
            self._persist(dx)
            return dx

        if isinstance(finding, MaterialFinding):
            dx.material_finding = finding
        elif isinstance(finding, ProcessFinding):
            dx.process_finding = finding

        # 3) 리포트
        notify(DiagnoseStep.REPORT)
        try:
            dx.report = self._build_report(issue, finding, dx.triage)
            dx.touch(DiagnosisStatus.REPORTED)
        except Exception as exc:  # noqa: BLE001
            dx.error = f"리포트 생성 실패: {exc}"
            dx.touch(DiagnosisStatus.FAILED)

        self._persist(dx)
        return dx

    # ── 내부 ──

    def _run_path(self, issue: IssueRequest, category: TriageCategory):
        if category is TriageCategory.PROCESS:
            return self._plugin.process_analyzer().analyze(issue)
        # MATERIAL 또는 AMBIGUOUS → 소재 경로 우선(3-A 핵심 강점)
        return self._plugin.material_analyzer().analyze(issue)

    def _build_report(self, issue: IssueRequest, finding, triage: TriageResult | None = None) -> Report:
        template = self._plugin.report_template(self._report_kind)
        refs = list(getattr(finding, "evidences", []))
        # 대체 후보 근거도 추적성에 포함
        for c in getattr(finding, "ranked_candidates", []) or []:
            refs += c.evidences
        return self._report_engine.build(template, finding, issue, refs, triage=triage)

    def _persist(self, dx: Diagnosis) -> None:
        if self._store is not None:
            try:
                self._store.save_diagnosis(dx)
            except Exception:  # noqa: BLE001 - 저장 실패가 진단을 막지 않음
                pass
