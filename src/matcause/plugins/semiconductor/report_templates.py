"""리포트 템플릿 — Gap Analysis / OCAP (반도체) (T-200 초기 구현, US-D1/D2).

ReportTemplate Protocol 구현. finding(MaterialFinding/ProcessFinding)과 근거(refs)를
받아 구조화된 Report 를 생성한다. 모든 수치 주장은 Evidence ID 로 원본과 연결한다
(추적성). 서술 문구는 근거 기반으로 작성하며, 근거 밖 수치는 만들지 않는다.

여기서는 템플릿이 구조(원인/조치/검증/출처 + markdown)를 만든다. LLM 서술 보강은
core.report_engine.ReportEngine 에서 이 구조를 입력으로 수행한다.
"""

from __future__ import annotations

import re

from matcause.core.models import (
    Evidence,
    IssueRequest,
    MaterialFinding,
    ProcessFinding,
    Report,
    ReportFormat,
    TriageResult,
)

from . import report_charts

_CATEGORY_LABELS = {
    "MATERIAL": "소재 요인",
    "PROCESS": "공정 요인",
    "AMBIGUOUS": "모호(양경로 검토)",
}

# risk_scorer.py 가 이미 만들어 둔 사람이 읽을 수 있는 Evidence.note 문장을
# breakdown 지표 키와 매칭하기 위한 힌트. 새 설명을 지어내지 않고, 근거로
# 이미 기록된 문장을 그대로 재사용한다(데이터 정직성).
_KEY_NOTE_HINTS = {
    "energy_above_hull": "energy_above_hull=",
    "formation_energy_per_atom": "formation_energy_per_atom=",
    "is_stable": "is_stable=",
    "application_suitability": "응용(",
}
_KEY_PLAIN_LABELS = {
    "energy_above_hull": "구조 안정성(energy above hull)",
    "formation_energy_per_atom": "형성 에너지(formation energy)",
    "is_stable": "열역학적 안정성(is_stable)",
    "application_suitability": "응용 적합성(band gap)",
}

# 고객사 리포트 전용: 근거 문장(Evidence.note)에 남아 있는 영어 변수명을
# "한글 설명(원문)" 형태로 풀어준다. 상세/OCAP 리포트는 근거 추적성을 위해
# 원문 필드명을 그대로 유지하지만(엔지니어 대상), 고객사 리포트는 비전문가도
# 읽을 수 있어야 하므로 이 치환은 _render_customer_markdown 에서만 적용한다.
_ENG_TERM_KOR = {
    "energy_above_hull": "구조 안정성(energy_above_hull)",
    "formation_energy_per_atom": "형성 에너지(formation_energy_per_atom)",
    "is_stable": "열역학적 안정성(is_stable)",
    "band_gap": "밴드갭(band_gap)",
}
_TERM_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_ENG_TERM_KOR, key=len, reverse=True)) + r")\b"
)


def _kor_explain(text: str) -> str:
    """영어 변수명을 한글 설명으로 치환(고객사 리포트 전용). 그 외 내용/수치는 그대로 둔다."""
    return _TERM_PATTERN.sub(lambda m: _ENG_TERM_KOR[m.group(0)], text)


# 고객사 리포트의 지표 라벨은 순한글만 쓴다(영어 원문은 근거 note 안에서
# _kor_explain 이 "한글(원문)" 형태로 별도 노출하므로, 라벨까지 영어를 겹쳐
# 쓰면 "안정성(안정성(is_stable))" 처럼 이중 치환되어 보이는 문제가 있었음).
_CUSTOMER_METRIC_LABEL = {
    "energy_above_hull": "구조 안정성",
    "formation_energy_per_atom": "형성 에너지",
    "is_stable": "열역학적 안정성",
    "application_suitability": "응용 적합성",
}


def _evidence_lines(refs: list[Evidence]) -> list[str]:
    lines = []
    for e in refs:
        val = "없음" if e.value is None else f"{e.value}{(' ' + e.unit) if e.unit else ''}"
        ref = f" [{e.source_type.value}:{e.source_ref}]" if e.source_ref else f" [{e.source_type.value}]"
        note = f" — {e.note}" if e.note else ""
        lines.append(f"- ({e.id}) {val}{ref}{note}")
    return lines


def _situation_lines(issue: IssueRequest, triage: TriageResult | None) -> list[str]:
    """'어떤 상황인지' 를 요약하는 도입부. Triage 가 있으면 분류/확신도도 포함."""
    lines = [issue.combined_text().strip(), ""]
    if triage is not None:
        cat_label = _CATEGORY_LABELS.get(triage.category.value, triage.category.value)
        lines.append(
            f"이 이슈는 **{cat_label}**(확신도 {triage.confidence:.2f}/1.00)로 분류되어 "
            "아래 경로로 분석되었습니다."
        )
    return lines


def _material_findings_ranked(
    finding: MaterialFinding, top_k: int = 3
) -> list[tuple[str, float, str | None]]:
    """(지표 키, 리스크 기여 점수, 해당 근거 note) 를 점수 내림차순으로 top_k 반환.

    새 수치/문구를 만들지 않고 risk_scorer.py 가 각 판정 시 이미 기록해 둔
    사람이 읽을 수 있는 note 를 그대로 인용한다(데이터 정직성). 라벨/번역은
    호출부(상세용 vs 고객사용 포맷터)에서 각자 다르게 입힌다.
    """
    if not finding.breakdown:
        return []
    ranked_keys = sorted(finding.breakdown, key=lambda k: finding.breakdown[k], reverse=True)
    out: list[tuple[str, float, str | None]] = []
    for key in ranked_keys[:top_k]:
        hint = _KEY_NOTE_HINTS.get(key)
        note = None
        if hint:
            for e in finding.evidences:
                if e.note and hint in e.note:
                    note = e.note
                    break
        out.append((key, finding.breakdown[key], note))
    return out


def _material_findings_explained(finding: MaterialFinding, top_k: int = 3) -> list[str]:
    """상세/OCAP 리포트용: 필드명을 그대로 유지(엔지니어 대상, 추적성 우선)."""
    ranked = _material_findings_ranked(finding, top_k)
    if not ranked:
        return ["소재 물성을 확보하지 못해 리스크 산정 근거가 없습니다."]
    out: list[str] = []
    for key, score, note in ranked:
        label = _KEY_PLAIN_LABELS.get(key, key)
        if note:
            out.append(f"**{label}** (리스크 기여 {score:.0f}/100): {note}")
        else:
            out.append(f"**{label}**: 리스크 기여 {score:.0f}/100")
    return out


def _material_findings_explained_customer(finding: MaterialFinding, top_k: int = 3) -> list[str]:
    """고객사 리포트용: 순한글 라벨 + 근거 note 안의 영어 변수명만 한글로 치환."""
    ranked = _material_findings_ranked(finding, top_k)
    if not ranked:
        return ["소재 물성을 확보하지 못해 리스크 산정 근거가 없습니다."]
    out: list[str] = []
    for key, score, note in ranked:
        label = _CUSTOMER_METRIC_LABEL.get(key, key)
        if note:
            out.append(f"**{label}** (리스크 기여 {score:.0f}/100): {_kor_explain(note)}")
        else:
            out.append(f"**{label}**: 리스크 기여 {score:.0f}/100")
    return out


def _process_findings_ranked(finding: ProcessFinding, top_k: int = 5) -> list[tuple[str, str | None]]:
    """(변수명, 해당 근거 note) 목록 (효과크기 상위 top_k 순서 유지)."""
    top_vars = (finding.stats or {}).get("top_vars", [])
    names = [tv["feature"] for tv in top_vars[:top_k]]
    note_by_feature = {
        e.source_ref: e.note for e in finding.evidences if e.source_ref in names and e.note
    }
    return [(name, note_by_feature.get(name)) for name in names]


def _process_findings_explained(finding: ProcessFinding, top_k: int = 5) -> list[str]:
    """상세/OCAP 리포트용: process_analyzer.py 가 이미 기록한 note 를 그대로 인용한다."""
    ranked = _process_findings_ranked(finding, top_k)
    if not ranked:
        return ["통계적으로 유의한 이상 변수를 찾지 못했습니다."]
    out: list[str] = []
    for name, note in ranked:
        if note:
            out.append(f"**{name}**: {note}")
        else:
            out.append(f"**{name}**: 통계적으로 유의한 이상 변수로 규명됨")
    return out


def _process_findings_explained_customer(finding: ProcessFinding, top_k: int = 5) -> list[str]:
    """고객사 리포트용: note 안의 영어 변수명(있다면)을 한글로 치환."""
    ranked = _process_findings_ranked(finding, top_k)
    if not ranked:
        return ["통계적으로 유의한 이상 변수를 찾지 못했습니다."]
    out: list[str] = []
    for name, note in ranked:
        if note:
            out.append(f"**{name}**: {_kor_explain(note)}")
        else:
            out.append(f"**{name}**: 통계적으로 유의한 이상 변수로 규명됨")
    return out


def _material_actions(finding: MaterialFinding) -> tuple[list[str], list[str]]:
    """리스크 수준에 따른 권장 조치/검증 실험."""
    actions: list[str] = []
    experiments: list[str] = []
    if finding.risk_score >= 60:
        actions.append("소재 물성이 주요 리스크로 판정됨: 대체 소재 검토를 우선한다.")
        if finding.ranked_candidates:
            top = finding.ranked_candidates[0]
            actions.append(f"1순위 대체 후보 '{top.name}' 적용 타당성 검토.")
        experiments.append("현재 소재와 상위 대체 후보의 전기적 특성 비교 실험.")
    elif finding.risk_score >= 20:
        actions.append("소재 리스크가 중간 수준: 공정 요인과 병행 검토 권장.")
        experiments.append("동일 소재 로트 간 물성 편차 측정으로 소재/공정 요인 분리.")
    else:
        actions.append("소재 리스크 낮음: 공정 요인(3-B) 경로를 우선 조사 권장.")
        experiments.append("공정 조건 재현 실험으로 불량 재현성 확인.")
    if finding.ranked_candidates:
        experiments.append(
            "대체 후보의 결함/안정성 지표(energy_above_hull)를 실측/문헌으로 교차 검증."
        )
    return actions, experiments


def _process_actions(finding: ProcessFinding) -> tuple[list[str], list[str]]:
    """이상 변수 규명 결과에 따른 권장 조치/검증 실험 (US-C1/C2)."""
    actions: list[str] = []
    experiments: list[str] = []
    n = len(finding.anomalous_vars)
    top = [v for v in finding.anomalous_vars[:5]]

    # 매핑된 원인이 있는지 확인
    mapped = {
        k: v for k, v in finding.cause_mappings.items()
        if v and not v.startswith("미매핑")
    }
    if n == 0:
        actions.append("유의한 이상 변수가 없어 공정 파라미터 단독 원인은 낮음: 소재 경로 병행 검토.")
        experiments.append("불량 재현 실험으로 산발/재현성 여부 확인.")
        return actions, experiments

    actions.append(
        f"통계적으로 유의한 이상 변수 {n}개(효과크기 상위: {', '.join(top)})의 "
        "해당 공정 파라미터·센서를 우선 점검한다."
    )
    if mapped:
        for feat, cause in list(mapped.items())[:3]:
            actions.append(f"{feat} → {cause}: 관련 설비/레시피 조건 교정 검토.")
    else:
        actions.append(
            "SECOM 변수는 익명이라 물리 원인 미매핑: 상위 이상 변수를 실제 센서/"
            "파라미터에 매핑(secom_mapping.yaml)한 뒤 원인 규명을 이어간다."
        )
    experiments.append("상위 이상 변수 구간에서 Pass/Fail 로트의 공정 조건을 재현·비교한다.")
    experiments.append("이상 변수와 실제 계측값의 상관을 확인해 매핑 가설을 검증한다.")
    return actions, experiments


class GapAnalysisTemplate:
    """요구 스펙 대비 현재 소재 능력의 격차를 정리하는 포맷."""

    def render(
        self,
        finding,
        issue: IssueRequest,
        refs: list[Evidence],
        triage: TriageResult | None = None,
    ) -> Report:
        cause, actions, experiments, sources = _build_common(finding)
        md = _render_markdown("Gap Analysis", issue, finding, cause, actions, experiments, refs, triage)
        return Report(
            cause=cause,
            evidences=refs,
            recommended_actions=actions,
            recommended_experiments=experiments,
            sources=sources,
            format=ReportFormat.GAP,
            markdown=md,
        )


class OcapTemplate:
    """원인 → 조치 → 검증(Out of Control Action Plan) 포맷."""

    def render(
        self,
        finding,
        issue: IssueRequest,
        refs: list[Evidence],
        triage: TriageResult | None = None,
    ) -> Report:
        cause, actions, experiments, sources = _build_common(finding)
        md = _render_markdown("OCAP", issue, finding, cause, actions, experiments, refs, triage)
        return Report(
            cause=cause,
            evidences=refs,
            recommended_actions=actions,
            recommended_experiments=experiments,
            sources=sources,
            format=ReportFormat.OCAP,
            markdown=md,
        )


def _build_common(finding):
    sources: list[str] = []
    if isinstance(finding, MaterialFinding):
        cause = finding.summary or f"소재 리스크 {finding.risk_score}/100"
        actions, experiments = _material_actions(finding)
        for e in finding.evidences:
            if e.url:
                sources.append(e.url)
            elif e.source_ref:
                sources.append(f"{e.source_type.value}:{e.source_ref}")
    elif isinstance(finding, ProcessFinding):
        actions, experiments = _process_actions(finding)
        cause = finding.summary or f"이상 변수 {len(finding.anomalous_vars)}건"
        for e in finding.evidences:
            if e.url:
                sources.append(e.url)
            elif e.source_ref:
                sources.append(f"{e.source_type.value}:{e.source_ref}")
    else:
        cause = "판정 근거 부족"
        actions = []
        experiments = []
    # 중복 제거, 순서 유지
    sources = list(dict.fromkeys(sources))
    return cause, actions, experiments, sources


def _render_markdown(kind, issue, finding, cause, actions, experiments, refs, triage=None) -> str:
    lines = [f"# MatCause 리포트 ({kind})", ""]
    lines.append("## 이슈 상황")
    lines += _situation_lines(issue, triage)
    lines.append("")
    lines.append("## 판정 원인")
    lines.append(cause + "\n")

    if isinstance(finding, MaterialFinding):
        lines.append("## 리스크 스코어")
        lines.append(f"- 종합: **{finding.risk_score}/100**")
        for k, v in finding.breakdown.items():
            lines.append(f"  - {k}: {v}")
        lines.append("")
        chart = report_charts.material_risk_breakdown_chart(finding)
        if chart:
            lines.append(f"![소재 리스크 지표별 기여도]({chart})")
            lines.append("")
        lines.append("### 무엇이 문제인가")
        for x in _material_findings_explained(finding):
            lines.append(f"- {x}")
        lines.append("")
        if finding.ranked_candidates:
            lines.append("## 대체 소재 후보 (랭킹)")
            for i, c in enumerate(finding.ranked_candidates, 1):
                suit = (c.metrics or {}).get("suitability")
                suit_badge = " ⚠️적합도 낮음" if suit == "적합도 낮음" else ""
                lines.append(
                    f"{i}. **{c.name}**{suit_badge} (리스크 {c.score}) — {c.improvement or ''}"
                    + (f" / 트레이드오프: {c.tradeoffs}" if c.tradeoffs else "")
                )
            lines.append("")
            cand_chart = report_charts.material_candidates_chart(finding)
            if cand_chart:
                lines.append(f"![대체 소재 후보 리스크 비교]({cand_chart})")
                lines.append("")

    if isinstance(finding, ProcessFinding):
        st = finding.stats or {}
        lines.append("## 이상 변수 규명 (통계)")
        lines.append(
            f"- 검정: {st.get('test', '그룹 검정')} + "
            f"{st.get('fdr_method', 'FDR')}(q={st.get('fdr_q', '?')})"
        )
        lines.append(
            f"- Pass/Fail: {st.get('n_pass', '?')} / {st.get('n_fail', '?')} "
            f"(약 1:{st.get('imbalance_ratio', '?')} 불균형)"
        )
        lines.append(f"- 유의 이상 변수: **{len(finding.anomalous_vars)}개**")
        top_vars = st.get("top_vars", [])
        if top_vars:
            lines.append("\n| 변수 | p_adj | Cohen d | 방향 | 원인 매핑 |")
            lines.append("|---|---|---|---|---|")
            dir_kr = {"higher_in_fail": "불량군↑", "lower_in_fail": "불량군↓"}
            for tv in top_vars:
                feat = tv["feature"]
                cause = finding.cause_mappings.get(feat, "미매핑")
                cause_short = "미매핑" if cause.startswith("미매핑") else cause
                lines.append(
                    f"| {feat} | {tv['p_adj']:.2e} | {tv['cohens_d']:.3f} | "
                    f"{dir_kr.get(tv['direction'], tv['direction'])} | {cause_short} |"
                )
        lines.append("")
        chart = report_charts.process_anomaly_chart(finding)
        if chart:
            lines.append(f"![공정 이상 변수 효과크기]({chart})")
            lines.append("")
        lines.append("### 무엇이 문제인가")
        for x in _process_findings_explained(finding):
            lines.append(f"- {x}")
        lines.append("")

    lines.append("## 무엇을 고쳐야 하는가 (권장 조치)")
    lines += [f"- {a}" for a in actions] or ["- (없음)"]
    lines.append("\n## 권장 검증 실험")
    lines += [f"- {e}" for e in experiments] or ["- (없음)"]
    lines.append("\n## 근거 (Evidence)")
    lines += _evidence_lines(refs) or ["- (없음)"]
    return "\n".join(lines)


class CustomerReportTemplate:
    """고객사 제출용 — 근거 ID 없이 요약/원인/리스크/대체후보/조치 중심.

    본문에는 Evidence ID 를 노출하지 않고 '상세 근거는 부록(상세 리포트) 참고'로 안내한다.
    (근거 데이터 자체는 Report.evidences 에 그대로 보관 → 상세 리포트/부록에서 활용)
    """

    def render(
        self,
        finding,
        issue: IssueRequest,
        refs: list[Evidence],
        triage: TriageResult | None = None,
    ) -> Report:
        cause, actions, experiments, sources = _build_common(finding)
        md = _render_customer_markdown(issue, finding, cause, actions, experiments, triage)
        return Report(
            cause=cause,
            evidences=refs,  # 근거는 보관하되 본문에는 미노출
            recommended_actions=actions,
            recommended_experiments=experiments,
            sources=sources,
            format=ReportFormat.CUSTOMER,
            markdown=md,
        )


def _render_customer_markdown(issue, finding, cause, actions, experiments, triage=None) -> str:
    lines = ["# 결함 원인 분석 리포트 (고객사 제출용)", ""]
    lines.append("## 1. 현재 상황")
    lines += _situation_lines(issue, triage)
    lines.append("")

    lines.append("## 2. 판정 원인")
    lines.append(cause + "\n")

    section = 3
    if isinstance(finding, MaterialFinding):
        lines.append(f"## {section}. 소재 리스크 평가")
        section += 1
        level = (
            "높음" if finding.risk_score >= 60
            else "중간" if finding.risk_score >= 20
            else "낮음"
        )
        lines.append(f"- 소재 리스크: **{finding.risk_score}/100 ({level})**")
        # 지표는 순한글 이름으로 요약(수치 ID·영어 필드명 없이)
        for k, v in finding.breakdown.items():
            lines.append(f"  - {_CUSTOMER_METRIC_LABEL.get(k, k)}: {v}/100")
        lines.append("")
        chart = report_charts.material_risk_breakdown_chart(finding)
        if chart:
            lines.append(f"![소재 리스크 지표별 기여도]({chart})")
            lines.append("")
        lines.append("**무엇이 문제인가**")
        for x in _material_findings_explained_customer(finding):
            lines.append(f"- {x}")
        lines.append("")

        if finding.ranked_candidates:
            lines.append(f"## {section}. 대체 소재 제안")
            section += 1
            for i, c in enumerate(finding.ranked_candidates, 1):
                suit = (c.metrics or {}).get("suitability", "")
                badge = " (응용 적합도 낮음)" if suit == "적합도 낮음" else ""
                lines.append(f"{i}. **{c.name}**{badge} — {c.improvement or ''}")
                if c.tradeoffs:
                    lines.append(f"   - 참고: {_kor_explain(c.tradeoffs)}")
            lines.append("")
            cand_chart = report_charts.material_candidates_chart(finding)
            if cand_chart:
                lines.append(f"![대체 소재 후보 리스크 비교]({cand_chart})")
                lines.append("")

    elif isinstance(finding, ProcessFinding):
        st = finding.stats or {}
        lines.append(f"## {section}. 공정 이상 변수 평가")
        section += 1
        lines.append(
            f"- Pass/Fail: {st.get('n_pass', '?')} / {st.get('n_fail', '?')} "
            f"(약 1:{st.get('imbalance_ratio', '?')} 불균형)"
        )
        lines.append(f"- 통계적으로 유의한 이상 변수: **{len(finding.anomalous_vars)}개**")
        lines.append("")
        chart = report_charts.process_anomaly_chart(finding)
        if chart:
            lines.append(f"![공정 이상 변수 효과크기]({chart})")
            lines.append("")
        lines.append("**무엇이 문제인가**")
        for x in _process_findings_explained_customer(finding):
            lines.append(f"- {x}")
        lines.append(
            "- SECOM 센서 변수는 익명화되어 있어, 위 변수가 실제로 어떤 설비/공정 "
            "파라미터에 대응하는지는 현장 엔지니어의 확인이 필요합니다."
        )
        lines.append("")

    lines.append(f"## {section}. 무엇을 고쳐야 하는가 (권장 조치)")
    section += 1
    lines += [f"- {a}" for a in actions] or ["- (없음)"]
    lines.append(f"\n## {section}. 권장 검증 실험")
    lines += [f"- {e}" for e in experiments] or ["- (없음)"]

    lines.append("\n---")
    lines.append("*상세 정량 근거(Materials Project 물성값, 문헌 인용 등)는 별첨 '상세 리포트'를 참고하십시오.*")
    return "\n".join(lines)


def get_template(kind: str):
    kind = (kind or "").upper()
    if kind == "GAP":
        return GapAnalysisTemplate()
    if kind == "OCAP":
        return OcapTemplate()
    if kind == "CUSTOMER":
        return CustomerReportTemplate()
    raise ValueError(f"알 수 없는 리포트 종류: {kind}")
