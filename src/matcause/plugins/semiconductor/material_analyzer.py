"""소재 분석기 — 소재 경로(3-A) end-to-end 조립 (T-114, US-B1/B2/B3).

MaterialAnalyzer Protocol 구현. 파이프라인:
  1. 물성 추출(T-111): 이슈 텍스트 → 화학식/물질군
  2. MP 조회(T-110): 화학식 → best 상 물성
  3. 리스크 산정(T-112): best 물성 → 0~100 리스크 + breakdown
  4. 대체 랭킹(T-113): 물질군 후보 + chemsys 계열 → 리스크 기반 랭킹

모든 수치는 Evidence(source_type=MP)로 래핑되어 추적성을 보장한다(US-D2).
데이터가 없거나 조회 실패 시에도 정직하게 빈/부분 결과를 반환한다(합성 금지).
"""

from __future__ import annotations

from matcause.core.llm.base import LLMClient
from matcause.core.models import (
    Evidence,
    EvidenceSource,
    IssueRequest,
    MaterialFinding,
)

from .alternatives_ranker import candidate_formulas_for_group, rank_alternatives
from .application_profile import detect_application
from .material_extractor import extract_materials
from .mp_connector import MpConnector, MpConnectorError
from .risk_scorer import score_material


class SemiconductorMaterialAnalyzer:
    def __init__(
        self,
        connector: MpConnector,
        knowledge_base=None,
        llm: LLMClient | None = None,
        max_alternatives: int = 5,
    ) -> None:
        self._connector = connector
        self._kb = knowledge_base
        self._llm = llm
        self._max_alt = max_alternatives

    def analyze(self, issue: IssueRequest) -> MaterialFinding:
        text = issue.combined_text()

        # 1) 물성 추출
        extraction = extract_materials(text, llm=self._llm)
        if not extraction.has_result():
            return MaterialFinding(
                risk_score=0.0,
                evidences=[
                    Evidence(
                        source_type=EvidenceSource.MP,
                        note="이슈에서 소재 화학식을 추출하지 못함(소재 경로 근거 부족)",
                    )
                ],
                summary="소재를 식별하지 못해 리스크를 산정할 수 없습니다.",
            )

        formula = extraction.primary_formula()
        group = extraction.material_group
        # 응용 감지(파워/LED/로직/유전체 등) → 응용 적합성 반영
        profile = detect_application(text)

        # 2) MP 조회
        try:
            summary = self._connector.query_summary(formula)
        except MpConnectorError as exc:
            return MaterialFinding(
                risk_score=0.0,
                evidences=[
                    Evidence.missing(EvidenceSource.MP, formula, f"MP 조회 실패: {exc}")
                ],
                summary=f"'{formula}' 물성을 조회하지 못했습니다: {exc}",
            )

        best = summary.get("best")
        if not best:
            return MaterialFinding(
                risk_score=0.0,
                evidences=[Evidence.missing(EvidenceSource.MP, formula, "안정 상(best) 없음")],
                summary=f"'{formula}'에 대해 안정 상을 찾지 못했습니다.",
            )

        # 3) 리스크 산정 (응용 프로파일 반영)
        risk = score_material(best, profile=profile)
        evidences = list(risk.evidences)
        # 데이터 출처 메모(캐시/라이브)와 결함에너지 프록시 노트를 근거에 포함
        for note in summary.get("notes", []):
            evidences.append(
                Evidence(source_type=EvidenceSource.MP, source_ref=formula, note=note)
            )
        source_tag = summary.get("source", "?")

        # 4) 대체 후보 랭킹
        ranked = []
        alt_note = ""
        try:
            cand_formulas = candidate_formulas_for_group(group, exclude=formula)
            candidate_materials = (
                self._connector.query_candidates(cand_formulas) if cand_formulas else []
            )
            # chemsys 계열 후보도 합침
            try:
                candidate_materials += self._connector.find_alternatives(
                    formula, k=self._max_alt
                )
            except MpConnectorError:
                pass
            alt_result = rank_alternatives(
                best, candidate_materials, k=self._max_alt, profile=profile
            )
            ranked = alt_result.candidates
            alt_note = alt_result.basis
            # 응용 적합성 관련 노트를 근거에 포함
            for n in alt_result.notes:
                evidences.append(
                    Evidence(source_type=EvidenceSource.MP, source_ref=formula, note=n)
                )
        except MpConnectorError as exc:
            alt_note = f"대체 후보 조회 실패: {exc}"

        # 요약 문구
        best_id = best.get("material_id")
        app_txt = f", 응용={profile.name}" if profile else ""
        summary_text = (
            f"[{source_tag}] {formula}({group or '물질군 미상'}{app_txt}) 대표상 {best_id} 기준 "
            f"소재 리스크 {risk.score}/100. "
            f"대체 후보 {len(ranked)}건 랭킹."
        )
        if risk.notes:
            summary_text += " / " + "; ".join(risk.notes)

        return MaterialFinding(
            risk_score=risk.score,
            breakdown=risk.breakdown,
            evidences=evidences,
            ranked_candidates=ranked,
            summary=summary_text,
        )
