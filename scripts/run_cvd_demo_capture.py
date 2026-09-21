"""공정 경로(CVD 이슈) 데모 전체 캡처 — UI가 렌더하는 것과 동일한 내용을 텍스트로 출력.

UI(app.py)와 동일하게 DiagnosisService(get_service)를 통해 파이프라인을 돌리고,
UI 화면에 표시되는 순서대로:
  - Triage 판단 근거 (UI의 _clean_rationale 적용본)
  - 공정 분석 근거 (이상 변수)
  - 상세 리포트 markdown (UI의 _reorder_report_md 적용본: 요약 맨끝, 헤더 낮춤)
  - 권장 조치 / 권장 검증 실험
  - 고객사 리포트 markdown
그리고 고객사 리포트 PDF를 파일로 저장한다.

사용: python scripts/run_cvd_demo_capture.py
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

from matcause.app_service import get_service
# UI 표시 정리 함수 재사용 (사용자가 실제로 보는 텍스트와 동일하게)
import matcause.ui.app as ui

CVD_ISSUE = (
    "CVD 증착 공정 이후 박막 두께 편차가 규격을 초과함. 최근 설비 PM 이후 "
    "발생한 것으로 추정, 원인 조사 요청."
)


def _line(c="="):
    print(c * 74)


def main() -> int:
    svc = get_service()
    dx = svc.diagnose(CVD_ISSUE, override=None)

    _line()
    print("공정 경로 데모 — CVD 이슈")
    _line()
    print(f"이슈: {CVD_ISSUE}\n")

    # 1) Triage (UI가 보여주는 정리된 근거)
    print("[1] 분기 판단 (Triage)")
    print(f"  분류      : {dx.triage.category.value}")
    print(f"  확신도    : {dx.triage.confidence}")
    print(f"  판단 근거 : {ui._clean_rationale(dx.triage.rationale)}")
    print(f"  (원본 rationale: {dx.triage.rationale!r})")
    print()

    # 2) 공정 분석 근거
    pf = dx.process_finding
    print("[2] 공정 분석 근거")
    if pf:
        st = pf.stats or {}
        print(f"  유의 이상 변수 : {len(pf.anomalous_vars)}")
        print(f"  검정 피처 수    : {st.get('n_features_tested')}")
        print(f"  클래스 불균형   : 1:{st.get('imbalance_ratio')}")
        print(f"  요약            : {pf.summary}")
    print()

    # 3) 상세 리포트 (UI가 렌더하는 형태: 요약 맨끝 + 헤더 낮춤)
    print("[3] 상세 리포트 (UI 렌더 형태)")
    _line("-")
    print(ui._reorder_report_md(dx.report.markdown))
    _line("-")
    print()

    # 4) 권장 조치 / 권장 검증 실험 (구조화 필드에서 직접)
    print("[4] 권장 조치")
    for a in dx.report.recommended_actions:
        print(f"  - {a}")
    print("\n[5] 권장 검증 실험")
    for e in dx.report.recommended_experiments:
        print(f"  - {e}")
    print()

    # 6) 고객사 리포트
    cust = svc.build_customer_report(dx.id)
    print("[6] 고객사 제출용 리포트 (UI 렌더 형태)")
    _line("-")
    print(ui._reorder_report_md(cust.markdown))
    _line("-")
    print()

    # 7) 고객사 PDF 저장
    pdf = svc.customer_report_pdf(dx.id)
    out_pdf = ROOT / "cvd_customer_report.pdf"
    if pdf:
        out_pdf.write_bytes(pdf)
        print(f"[7] 고객사 PDF 저장: {out_pdf}  ({len(pdf):,} bytes)")
    else:
        print("[7] 고객사 PDF 생성 실패")

    # 8) 내부 표시 노출 검사 (렌더 결과 전체에서)
    print("\n[8] 내부 표시([MOCK] 등) 노출 검사")
    surfaces = {
        "triage_rationale(표시)": ui._clean_rationale(dx.triage.rationale),
        "process_summary": pf.summary if pf else "",
        "detail_report": ui._reorder_report_md(dx.report.markdown),
        "customer_report": ui._reorder_report_md(cust.markdown),
    }
    markers = ["[MOCK]", "mock-llm", "NotImplemented", "TODO", "FIXME"]
    leaked = False
    for name, txt in surfaces.items():
        hits = [m for m in markers if m in txt]
        status = f"❌ 노출: {hits}" if hits else "✅ 깨끗"
        print(f"  {name:<26}: {status}")
        if hits:
            leaked = True
    print(f"\n  => {'내부 표시 없음 (모든 표면 깨끗)' if not leaked else '내부 표시 노출 발견!'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
