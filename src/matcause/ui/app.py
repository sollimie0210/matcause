"""Streamlit 데모 대시보드 (T-211, US-F1).

한 화면 흐름: 이슈 입력 → 분기 판단(확신도) → 근거 데이터(리스크/대체후보) → 최종 리포트.
파이프라인(Orchestrator)을 app_service 를 통해 직접 호출한다(인프로세스).

실행: streamlit run src/matcause/ui/app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from matcause.app_service import get_service
from matcause.core.models import DiagnosisStatus, TriageCategory

_CATEGORY_COLOR = {
    "MATERIAL": "🟦 소재 요인",
    "PROCESS": "🟧 공정 요인",
    "AMBIGUOUS": "🟨 모호(양경로 검토)",
}

_EXAMPLE = (
    "고객사에서 GaN 기반 파워 소자의 특정 로트에서 누설전류가 규격 상한을 초과했다는 "
    "클레임이 접수됨. 동일 공정 조건에서 생산됐으나 소재 물성 편차가 의심됨."
)


def _render_triage(triage) -> None:
    st.subheader("2. 분기 판단 (Triage)")
    label = _CATEGORY_COLOR.get(triage.category.value, triage.category.value)
    c1, c2 = st.columns([1, 2])
    with c1:
        st.metric("분류", label)
        st.metric("확신도", f"{triage.confidence:.2f}")
        st.progress(min(1.0, max(0.0, triage.confidence)))
    with c2:
        st.markdown("**판단 근거**")
        st.write(triage.rationale)
        sig = triage.signals or {}
        st.caption(
            f"추출 화학식: {sig.get('extracted_formulas', [])} · "
            f"소재 키워드 {sig.get('material_keyword_count', 0)} · "
            f"공정 키워드 {sig.get('process_keyword_count', 0)}"
        )


def _render_material(finding) -> None:
    st.subheader("3. 소재 분석 근거")
    c1, c2 = st.columns([1, 2])
    with c1:
        st.metric("소재 리스크", f"{finding.risk_score:.1f} / 100")
        st.progress(min(1.0, finding.risk_score / 100.0))
        if finding.risk_score >= 60:
            st.error("소재 물성이 주요 리스크로 판정")
        elif finding.risk_score >= 20:
            st.warning("소재 리스크 중간 — 공정 요인 병행 검토")
        else:
            st.success("소재 리스크 낮음 — 공정 요인 우선 조사 권장")
    with c2:
        if finding.breakdown:
            st.markdown("**지표별 리스크 기여**")
            bd = pd.DataFrame(
                {"지표": list(finding.breakdown.keys()),
                 "리스크(0~100)": list(finding.breakdown.values())}
            ).set_index("지표")
            st.bar_chart(bd)
        st.caption(finding.summary)

    if finding.ranked_candidates:
        st.markdown("**대체 소재 후보 (리스크 오름차순)**")
        rows = []
        for i, c in enumerate(finding.ranked_candidates, 1):
            m = c.metrics or {}
            rows.append({
                "순위": i,
                "후보": c.name,
                "적합성": m.get("suitability", "-"),
                "리스크": c.score,
                "E_hull(eV/atom)": m.get("energy_above_hull"),
                "band_gap(eV)": m.get("band_gap"),
                "mp-id": m.get("material_id"),
                "트레이드오프": c.tradeoffs or "",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _render_report(report, diagnosis_id: str) -> None:
    st.subheader("4. 최종 리포트")
    tab_detail, tab_customer = st.tabs(["상세 리포트 (근거 포함)", "고객사 제출용"])

    with tab_detail:
        st.caption(f"포맷: {report.format.value} · 근거 ID 포함(추적성)")
        st.markdown(report.markdown)
        st.download_button(
            "상세 리포트 내보내기 (.md)",
            data=report.markdown,
            file_name=f"matcause_detail_{report.id}.md",
            mime="text/markdown",
        )

    with tab_customer:
        st.caption("근거 ID 없이 요약/원인/리스크/대체후보/조치 중심")
        try:
            cust = get_service().build_customer_report(diagnosis_id)
        except Exception as exc:  # noqa: BLE001
            st.exception(exc)
            cust = None
        if cust is None:
            st.info("고객사 리포트를 생성할 수 없습니다.")
            return
        st.markdown(cust.markdown)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "고객사 리포트 (.md)",
                data=cust.markdown,
                file_name=f"matcause_customer_{cust.id}.md",
                mime="text/markdown",
            )
        with c2:
            try:
                pdf_bytes = get_service().customer_report_pdf(diagnosis_id)
                if pdf_bytes:
                    st.download_button(
                        "고객사 리포트 (PDF)",
                        data=pdf_bytes,
                        file_name=f"matcause_customer_{cust.id}.pdf",
                        mime="application/pdf",
                    )
            except Exception as exc:  # noqa: BLE001
                st.warning(f"PDF 생성 불가: {exc}")


def main() -> None:
    st.set_page_config(page_title="MatCause", layout="wide")
    st.title("MatCause — 소재·공정 결함 원인 판별 에이전트")
    st.caption("이슈 입력 → 분기 판단 → 근거 데이터 → 리포트")

    # 1) 입력
    st.subheader("1. 이슈 입력")
    text = st.text_area(
        "RFQ 또는 불량 현상",
        value=st.session_state.get("issue_text", _EXAMPLE),
        height=120,
        placeholder="예: 특정 로트에서 누설전류 상승…",
    )
    col_a, col_b = st.columns([1, 1])
    with col_a:
        override = st.selectbox(
            "경로 수동 지정 (선택)",
            options=["자동(Triage)", "MATERIAL", "PROCESS"],
            index=0,
            help="Triage 결과를 무시하고 특정 경로로 강제하려면 선택",
        )
    with col_b:
        st.write("")
        st.write("")
        run = st.button("진단 시작", type="primary", use_container_width=True)

    if run:
        if not text.strip():
            st.error("이슈 텍스트를 입력하세요.")
            return
        st.session_state["issue_text"] = text
        ov = None if override == "자동(Triage)" else override
        with st.spinner("진단 중… (소재 물성 조회 포함)"):
            try:
                dx = get_service().diagnose(text, override=ov)
                st.session_state["diagnosis_id"] = dx.id
            except Exception as exc:  # noqa: BLE001
                st.exception(exc)
                return

    # 결과 표시
    dx_id = st.session_state.get("diagnosis_id")
    if not dx_id:
        st.info("이슈를 입력하고 '진단 시작'을 누르면 전체 파이프라인이 실행됩니다.")
        return

    dx = get_service().get(dx_id)
    if dx is None:
        st.warning("진단 결과를 찾을 수 없습니다.")
        return

    if dx.error:
        st.error(f"진단 오류: {dx.error}")

    if dx.triage:
        _render_triage(dx.triage)
    if dx.material_finding:
        _render_material(dx.material_finding)
    elif dx.process_finding:
        st.subheader("3. 공정 분석 근거")
        st.write(dx.process_finding.summary or "공정 분석 결과")
        st.json({"anomalous_vars": dx.process_finding.anomalous_vars})
    if dx.report:
        _render_report(dx.report, dx.id)

    st.caption(f"진단 ID: {dx.id} · 상태: {dx.status.value if isinstance(dx.status, DiagnosisStatus) else dx.status}")


if __name__ == "__main__":
    main()
