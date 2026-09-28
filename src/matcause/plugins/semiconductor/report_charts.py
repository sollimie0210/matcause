"""리포트용 차트 생성 (고객사/상세 리포트 보강).

matplotlib(Agg, 헤드리스)로 Finding에 이미 들어있는 수치만 시각화한다. 차트가
새 숫자를 만들어내지는 않는다 — 전부 risk_scorer/secom_stats 가 이미 계산한
값을 막대 그래프로 그릴 뿐이다. PNG를 base64 data URI로 반환해 report markdown
에 표준 이미지 문법(`![alt](data:...)`)으로 그대로 삽입할 수 있게 한다
(report_pdf.py 의 markdown→HTML 변환과 Streamlit의 st.markdown 양쪽에서 동일하게
렌더된다).
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from matcause.core.models import MaterialFinding, ProcessFinding  # noqa: E402

_KOREAN_FONT_FILE = "NotoSansKR-Regular.ttf"


def _font_dir() -> Path:
    """폰트 디렉토리. core/report_pdf.py 와 동일한 규칙(env override, 리포지토리
    루트의 assets/fonts). 이 파일: src/matcause/plugins/semiconductor/report_charts.py
    → 리포지토리 루트는 parents[4].
    """
    env = os.environ.get("MATCAUSE_FONT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "assets" / "fonts"


def _register_korean_font() -> None:
    """matplotlib 기본 폰트(DejaVu Sans)는 한글을 지원하지 않아 차트 라벨이 깨진
    네모(tofu)로 나온다. 리포지토리에 이미 포함된 Noto Sans KR(OFL 라이선스,
    report_pdf.py 의 PDF 한글 폰트와 동일 자산)을 등록해 재사용한다. 폰트 파일이
    없는 환경에서는 조용히 기본 폰트로 폴백한다(차트 자체는 계속 생성됨).
    """
    font_path = _font_dir() / _KOREAN_FONT_FILE
    if not font_path.exists():
        return
    try:
        font_manager.fontManager.addfont(str(font_path))
        family = font_manager.FontProperties(fname=str(font_path)).get_name()
        matplotlib.rcParams["font.family"] = family
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception:  # noqa: BLE001 - 폰트 등록 실패는 치명적이지 않음(기본 폰트로 폴백)
        pass


_register_korean_font()

NAVY = "#1B2A4A"
ACCENT = "#4C6FBF"
WARN = "#C77B30"
GRID = "#E4E9F2"
TEXT = "#333333"

_BREAKDOWN_LABELS = {
    "energy_above_hull": "구조 안정성\n(energy above hull)",
    "formation_energy_per_atom": "형성 에너지\n(formation energy)",
    "is_stable": "열역학적 안정성\n(is_stable)",
    "application_suitability": "응용 적합성\n(band gap)",
}


def _fig_to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _strip_axes(ax) -> None:
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def material_risk_breakdown_chart(finding: MaterialFinding) -> str | None:
    """가로 막대: 지표별 리스크 기여도(0~100). 단일 계열(크기)이라 단일 색조."""
    if not finding.breakdown:
        return None
    keys = list(finding.breakdown.keys())
    labels = [_BREAKDOWN_LABELS.get(k, k) for k in keys]
    values = [finding.breakdown[k] for k in keys]

    fig, ax = plt.subplots(figsize=(6.4, 0.62 * len(values) + 1.0))
    y = range(len(values))
    ax.barh(y, values, color=NAVY, height=0.55, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlim(0, 108)
    ax.set_xlabel("리스크 기여도 (0~100, 높을수록 리스크 큼)", fontsize=9)
    _strip_axes(ax)
    for yi, v in zip(y, values):
        ax.text(v + 2, yi, f"{v:.0f}", va="center", fontsize=9, color=TEXT, zorder=4)
    ax.invert_yaxis()
    ax.set_title("소재 리스크 — 지표별 기여도", fontsize=10, color=NAVY, loc="left", pad=8)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def material_candidates_chart(finding: MaterialFinding) -> str | None:
    """가로 막대: 대체 후보별 리스크 점수. 적합/적합도 낮음을 2색 상태로 구분."""
    cands = finding.ranked_candidates
    if not cands:
        return None
    names = [c.name for c in cands]
    scores = [c.score for c in cands]
    unfit = [(c.metrics or {}).get("suitability") == "적합도 낮음" for c in cands]
    colors = [WARN if u else ACCENT for u in unfit]
    max_score = max(scores) if scores else 100.0

    fig, ax = plt.subplots(figsize=(6.4, 0.62 * len(cands) + 1.0))
    y = range(len(cands))
    ax.barh(y, scores, color=colors, height=0.55, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlim(0, max(100.0, max_score * 1.2))
    ax.set_xlabel("리스크 점수 (낮을수록 안정적)", fontsize=9)
    _strip_axes(ax)
    for yi, v, u in zip(y, scores, unfit):
        label = f"{v:.0f}" + ("  ⚠ 적합도 낮음" if u else "  적합")
        ax.text(v + max_score * 0.02 + 1, yi, label, va="center", fontsize=8.5, color=TEXT, zorder=4)
    ax.invert_yaxis()
    ax.set_title("대체 소재 후보 — 리스크 비교", fontsize=10, color=NAVY, loc="left", pad=8)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def process_anomaly_chart(finding: ProcessFinding) -> str | None:
    """가로 막대: 상위 이상 변수 효과크기(Cohen's d). 방향(위/아래)을 2색으로 구분."""
    top_vars = (finding.stats or {}).get("top_vars", [])
    if not top_vars:
        return None
    top_vars = top_vars[:15]
    names = [tv["feature"] for tv in top_vars]
    d_vals = [tv["cohens_d"] for tv in top_vars]
    colors = [ACCENT if d >= 0 else WARN for d in d_vals]

    fig, ax = plt.subplots(figsize=(6.4, 0.5 * len(top_vars) + 1.0))
    y = range(len(top_vars))
    ax.barh(y, d_vals, color=colors, height=0.55, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=9)
    ax.axvline(0, color="#9AA5B8", linewidth=0.9, zorder=2)
    ax.set_xlabel("효과크기 Cohen's d (+ = 불량군에서 높음, − = 불량군에서 낮음)", fontsize=9)
    _strip_axes(ax)
    # 값 레이블이 y축 눈금 라벨과 겹치지 않도록 데이터 범위에 비례한 여백을 둔다
    # (막대가 왼쪽/음수 방향으로 갈수록 라벨이 축 라벨과 붙어 보이는 문제 보정).
    span = max(abs(v) for v in d_vals) or 1.0
    ax.margins(x=0.22)
    offset = span * 0.04
    for yi, v in zip(y, d_vals):
        ax.text(
            v + (offset if v >= 0 else -offset),
            yi,
            f"{v:.2f}",
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=8.5,
            color=TEXT,
            zorder=4,
        )
    ax.invert_yaxis()
    ax.set_title("공정 이상 변수 — 효과크기 상위", fontsize=10, color=NAVY, loc="left", pad=8)
    fig.tight_layout()
    return _fig_to_data_uri(fig)
