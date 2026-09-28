"""고객사 제출용 리포트 + PDF 내보내기 테스트."""

from __future__ import annotations

from matcause.core.models import (
    Evidence,
    EvidenceSource,
    IssueRequest,
    MaterialFinding,
    RankedCandidate,
    ReportFormat,
)
from matcause.core.report_pdf import markdown_to_html, report_to_pdf_bytes
from matcause.plugins.semiconductor.report_templates import get_template


def _finding():
    return MaterialFinding(
        risk_score=44.4,
        breakdown={"energy_above_hull": 0.0, "application_suitability": 100.0},
        evidences=[
            Evidence(source_type=EvidenceSource.MP, source_ref="mp-2534",
                     value=0.19, unit="eV", note="GaAs band_gap"),
        ],
        ranked_candidates=[
            RankedCandidate(
                name="AlN", score=0.0, metrics={"suitability": "적합", "band_gap": 4.05},
                improvement="리스크 44.4→0.0", tradeoffs="band_gap 증가",
                evidences=[Evidence(source_type=EvidenceSource.MP, source_ref="mp-661", value=4.05, unit="eV")],
            ),
        ],
        summary="GaAs 파워 응용 부적합, 리스크 44.4/100",
    )


def test_customer_template_hides_evidence_ids():
    tmpl = get_template("CUSTOMER")
    finding = _finding()
    issue = IssueRequest(raw_text="GaAs 파워 소자 누설전류 이상")
    report = tmpl.render(finding, issue, finding.evidences)

    assert report.format is ReportFormat.CUSTOMER
    # 본문에 Evidence ID(ev_...)가 노출되지 않아야 함
    assert "ev_" not in report.markdown
    # 부록 안내 문구 포함
    assert "상세 리포트" in report.markdown
    # 핵심 섹션 포함
    for section in ("현재 상황", "판정 원인", "소재 리스크", "대체 소재", "권장 조치"):
        assert section in report.markdown
    # 근거 데이터 자체는 보관됨(부록용)
    assert report.evidences


def test_detail_ocap_still_has_evidence_ids():
    tmpl = get_template("OCAP")
    finding = _finding()
    issue = IssueRequest(raw_text="GaAs 파워 소자")
    report = tmpl.render(finding, issue, finding.evidences)
    # 상세 리포트는 근거 ID 포함(추적성 유지)
    assert "ev_" in report.markdown
    assert "근거" in report.markdown


def test_markdown_to_html_basic():
    md = "# 제목\n\n## 소제목\n- 항목1\n- **굵은** 항목\n\n---\n*각주*"
    html = markdown_to_html(md, title="t")
    assert "<h1>제목</h1>" in html
    assert "<h2>소제목</h2>" in html
    assert "<li>항목1</li>" in html
    assert "<strong>굵은</strong>" in html
    assert "<hr/>" in html
    assert 'class="footnote"' in html


def test_html_registers_korean_font_when_available():
    from matcause.core.report_pdf import _font_available

    html = markdown_to_html("# 한글 제목", title="t")
    if _font_available():
        # 폰트가 있으면 @font-face 로 NotoSansKR 등록 + 전체 요소 적용
        assert "@font-face" in html
        assert "NotoSansKR" in html
        assert "NotoSansKR-Regular.ttf" in html
        assert "NotoSansKR-Bold.ttf" in html
        assert "* {" in html  # 전체 요소 font-family


def test_pdf_bytes_generated():
    tmpl = get_template("CUSTOMER")
    finding = _finding()
    report = tmpl.render(finding, IssueRequest(raw_text="GaAs 파워 소자"), finding.evidences)
    pdf = report_to_pdf_bytes(report.markdown, title="고객사 리포트")
    # 유효한 PDF 헤더
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000


def test_pdf_renders_korean_not_tofu():
    """PDF 에서 한글이 실제 텍스트로 추출되면 tofu(검은 네모)가 아님을 의미."""
    import io

    from matcause.core.report_pdf import _font_available

    if not _font_available():
        import pytest

        pytest.skip("한글 폰트 미포함 환경")

    md = "# 결함 원인 분석\n\n## 판정 원인\nGaAs 소재는 밴드갭이 좁습니다.\n"
    pdf = report_to_pdf_bytes(md, title="한글 테스트")
    # 폰트 임베드 흔적
    assert b"Noto" in pdf

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf))
    text = "".join(p.extract_text() or "" for p in reader.pages)
    has_hangul = any("\uac00" <= ch <= "\ud7a3" for ch in text)
    assert has_hangul, "PDF 에서 한글 텍스트를 추출하지 못함(폰트 렌더 실패 의심)"
