"""Streamlit 데모 대시보드 (T-211, US-F1).

레이아웃:
  - 상단 바: 왼쪽 MATCAUSE 로고, 오른쪽 네비게이션(진단·요약·보관함) + 로그인
  - 진단: 히어로 슬라이드(소자/공정 이미지 순환) + 에이전트 소개 + 이슈 입력/분석
  - 요약: 진단 집계 대시보드
  - 보관함: 리포트 열람/내보내기

디자인: 메인 컬러 남색(#1B2A4A). 사이드바 없음, 상단 바 1개만.

실행: streamlit run src/matcause/ui/app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from matcause.app_service import get_service
from matcause.core.models import DiagnosisStatus

# ─────────────────────────── 컬러 ───────────────────────────

NAVY = "#1B2A4A"
NAVY_DEEP = "#12203C"
NAVY_SOFT = "#2E4370"
ACCENT = "#4C6FBF"
BG = "#F4F6FA"

_CATEGORY_META = {
    "MATERIAL": {"label": "소재 요인", "color": NAVY, "emoji": "🔷"},
    "PROCESS": {"label": "공정 요인", "color": ACCENT, "emoji": "🔶"},
    "AMBIGUOUS": {"label": "모호 (양경로 검토)", "color": NAVY_SOFT, "emoji": "🔸"},
}

_EXAMPLE = (
    "고객사에서 GaN 기반 파워 소자의 특정 로트에서 누설전류가 규격 상한을 초과했다는 "
    "클레임이 접수됨. 동일 공정 조건에서 생산됐으나 소재 물성 편차가 의심됨."
)

_HERO_IMAGES = [
    "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=1400&q=80",
    "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1400&q=80",
    "https://images.unsplash.com/photo-1562408590-e32931084e23?w=1400&q=80",
    "https://images.unsplash.com/photo-1630752708714-2418cee3e7e4?w=1400&q=80",
]


# ─────────────────────────── CSS ───────────────────────────

def _inject_styles() -> None:
    hero_kf = "\n".join(
        f"{int(i * 100 / len(_HERO_IMAGES))}% {{ background-image: url('{u}'); }}"
        for i, u in enumerate(_HERO_IMAGES)
    ) + f"\n100% {{ background-image: url('{_HERO_IMAGES[0]}'); }}"

    st.markdown(f"""
    <style>
    /* ── 글로벌 ── */
    .stApp {{ background: {BG}; }}
    header[data-testid="stHeader"] {{ display:none !important; }}
    section[data-testid="stSidebar"] {{ display:none !important; }}
    .block-container {{ padding-top: 0 !important; max-width: 1260px; }}

    /* ── 히어로 슬라이드쇼 ── */
    @keyframes mc-hero-slide {{ {hero_kf} }}
    .mc-hero-banner {{
        position: relative; width: 100%; height: 380px; overflow: hidden;
        border-radius: 0 0 20px 20px;
        animation: mc-hero-slide {len(_HERO_IMAGES)*5}s ease-in-out infinite;
        background-size: cover; background-position: center;
    }}
    .mc-hero-overlay {{
        position:absolute; inset:0;
        background: linear-gradient(180deg, rgba(18,32,60,0.62) 0%, rgba(27,42,74,0.88) 100%);
        display:flex; flex-direction:column; justify-content:center;
        padding: 2.8rem 3.5rem;
    }}
    .mc-hero-overlay h1 {{
        color:#fff; font-size:2.6rem; font-weight:900; letter-spacing:0.06em;
        margin:0 0 0.5rem 0;
    }}
    .mc-hero-overlay p {{
        color:#cdd6ea; font-size:1.05rem; max-width:600px; line-height:1.7; margin:0;
    }}

    /* ── CSS-only 등장 애니메이션 (JS 불필요) ── */
    @keyframes mc-fadein {{
        from {{ opacity:0; transform:translateY(30px); }}
        to   {{ opacity:1; transform:translateY(0); }}
    }}
    .mc-ani {{ animation: mc-fadein 0.65s ease both; }}
    .mc-ani-d1 {{ animation-delay: 0.15s; }}
    .mc-ani-d2 {{ animation-delay: 0.30s; }}
    .mc-ani-d3 {{ animation-delay: 0.45s; }}

    /* ── 소개 섹션 ── */
    .mc-about {{ padding:1.6rem 0 0.4rem 0; }}
    .mc-about .mc-ey {{
        color:{ACCENT}; font-weight:700; font-size:0.78rem;
        letter-spacing:0.16em; text-transform:uppercase;
        border-top:2px solid {NAVY}; display:inline-block;
        padding-top:0.4rem; margin-bottom:0.2rem;
    }}
    .mc-about h2 {{ color:{NAVY}; font-size:1.55rem; font-weight:800; margin:0.2rem 0 1rem 0; }}
    .mc-about-row {{
        display:grid; grid-template-columns:1fr 1fr; gap:2rem; margin-top:0.6rem;
    }}
    .mc-about-col h4 {{ color:{ACCENT}; font-size:0.88rem; margin:0 0 0.3rem 0; }}
    .mc-about-col p {{ color:#5A6B8A; font-size:0.92rem; line-height:1.7; }}
    .mc-about-divider {{ height:1px; background:#DDE3EF; margin:1.2rem 0; }}

    /* ── 피쳐 카드 ── */
    .mc-features {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1.4rem; margin:1.2rem 0 1.8rem 0; }}
    .mc-feat-card {{
        background:#fff; border-radius:16px; padding:1.8rem 1.4rem;
        box-shadow:0 6px 24px rgba(27,42,74,0.07); border-top:4px solid {ACCENT};
    }}
    .mc-feat-card .ic {{ font-size:1.8rem; margin-bottom:0.5rem; }}
    .mc-feat-card h3 {{ color:{NAVY}; font-size:1.05rem; margin:0 0 0.3rem 0; }}
    .mc-feat-card p {{ color:#5A6B8A; font-size:0.88rem; line-height:1.6; }}

    /* ── 공용 ── */
    .mc-card {{
        background:#fff; border:1px solid #E4E9F2; border-radius:14px;
        padding:1.2rem 1.4rem; box-shadow:0 4px 14px rgba(27,42,74,0.06);
        margin-bottom:1rem;
    }}
    .mc-stat {{ text-align:center; }}
    .mc-stat .v {{ font-size:2rem; font-weight:800; color:{NAVY}; line-height:1.1; }}
    .mc-stat .l {{ color:{NAVY_SOFT}; font-size:0.85rem; margin-top:0.2rem; }}
    .mc-badge {{
        display:inline-block; padding:0.25rem 0.7rem; border-radius:999px;
        color:#fff; font-weight:700; font-size:0.85rem;
    }}
    .mc-eyebrow {{
        color:{ACCENT}; font-weight:800; font-size:1.0rem;
        letter-spacing:0.16em; text-transform:uppercase;
        border-top:3px solid {NAVY}; display:inline-block;
        padding-top:0.5rem; margin-bottom:0.25rem;
    }}
    .mc-section-title {{ color:{NAVY}; font-weight:800; font-size:1.7rem; margin:0.15rem 0 0.9rem 0; scroll-margin-top:80px; }}
    .mc-anchor {{ scroll-margin-top: 80px; }}
    .mc-page-hero {{
        background: linear-gradient(135deg,{NAVY_DEEP} 0%,{NAVY} 55%,{NAVY_SOFT} 100%);
        color:#fff; border-radius:16px; padding:2rem 2.4rem; margin-bottom:1.6rem;
        box-shadow:0 10px 30px rgba(27,42,74,0.18);
    }}
    .mc-page-hero h2 {{ color:#fff; font-size:1.7rem; font-weight:800; margin:0 0 .35rem 0; }}
    .mc-page-hero p {{ color:#cdd6ea; margin:0; font-size:0.95rem; }}

    /* ── 버튼 ── */
    .stButton > button[kind="primary"] {{ background:{NAVY}; border:0; border-radius:10px; font-weight:700; }}
    .stButton > button[kind="primary"]:hover {{ background:{NAVY_DEEP}; }}
    .stDownloadButton > button {{ background:#fff; color:{NAVY}; border:1.5px solid {NAVY}; border-radius:10px; font-weight:700; }}
    .stDownloadButton > button:hover {{ background:{NAVY}; color:#fff; }}

    /* ── 다운로드 버튼: 크고 또렷하게 ── */
    .stDownloadButton > button {{
        min-height: 3.4rem !important;
        font-size: 1.18rem !important;
        padding: 0.7rem 1.4rem !important;
    }}
    .stDownloadButton > button p {{ font-size: 1.18rem !important; font-weight: 800 !important; }}

    /* 선택 안 된 세그먼트(secondary) 버튼 = 리포트 전환 버튼: 남색 테두리 또렷 */
    .stButton > button[kind="secondary"] {{
        border: 2px solid {NAVY} !important; color: {NAVY} !important;
        background: #fff !important; border-radius: 10px;
    }}
    .stButton > button[kind="secondary"]:hover {{ background: #EEF2F9 !important; }}

    /* 리포트 전환 버튼(상세/고객사): .mc-report-seg 바로 다음 가로블록의 버튼을 크게 */
    .mc-report-seg + div[data-testid="stHorizontalBlock"] .stButton > button {{
        min-height: 3.8rem !important;
        font-size: 1.3rem !important;
        border-radius: 12px;
    }}
    .mc-report-seg + div[data-testid="stHorizontalBlock"] .stButton > button p {{
        font-size: 1.3rem !important; font-weight: 800 !important;
    }}
    .stProgress > div > div > div > div {{ background-color:{ACCENT}; }}
    .stTabs [aria-selected="true"] {{ color:{NAVY} !important; }}
    .stTabs [data-baseweb="tab-highlight"] {{ background-color:{NAVY}; }}

    /* ── 탭 라벨 크기 키움 (여러 Streamlit 버전 대응) ── */
    .stTabs [data-baseweb="tab"] p,
    .stTabs button[role="tab"] p,
    .stTabs [data-baseweb="tab"] {{
        font-size: 1.25rem !important; font-weight: 800 !important;
    }}
    .stTabs [data-baseweb="tab"], .stTabs button[role="tab"] {{
        padding-top: 0.9rem !important; padding-bottom: 0.9rem !important;
        padding-left: 1.4rem !important; padding-right: 1.4rem !important;
    }}
    /* 리포트 탭: 두 탭을 같은 너비로 크게 (탭 리스트를 균등 분할) */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 0.6rem; background: #EEF2F9; padding: 0.35rem; border-radius: 12px;
    }}
    .stTabs [data-baseweb="tab-list"] [data-baseweb="tab"] {{
        flex: 1 1 0; justify-content: center; border-radius: 9px;
    }}
    .stTabs [data-baseweb="tab-list"] [aria-selected="true"] {{
        background: #fff; box-shadow: 0 2px 8px rgba(27,42,74,0.10);
    }}

    /* ── 사이드 스텝 플로우(우측 고정 레일) — 크게 ── */
    .mc-rail {{
        position: fixed; top: 110px; right: 22px; z-index: 900;
        background: #fff; border: 1px solid #E4E9F2; border-radius: 18px;
        padding: 1.1rem 1rem; box-shadow: 0 10px 30px rgba(27,42,74,0.16);
        width: 220px;
    }}
    .mc-rail .rt {{ font-size:0.9rem; font-weight:800; letter-spacing:0.14em;
        color:{NAVY_SOFT}; text-transform:uppercase; text-align:center;
        margin-bottom:0.8rem; padding-bottom:0.6rem; border-bottom:2px solid #EEF2F9; }}
    .mc-rail a {{
        display:flex; align-items:center; text-decoration:none; color:{NAVY};
        font-size:1.05rem; font-weight:700; padding:0.8rem 0.9rem;
        border-radius:12px; margin-bottom:0.55rem; border:1.5px solid #E4E9F2;
        transition: all .12s;
    }}
    .mc-rail a:hover {{ background:{NAVY}; color:#fff; border-color:{NAVY};
        transform: translateX(-3px); box-shadow:0 4px 12px rgba(27,42,74,0.18); }}
    .mc-rail a .n {{
        display:inline-flex; align-items:center; justify-content:center;
        width:2rem; height:2rem; flex:0 0 2rem;
        background:{ACCENT}; color:#fff; border-radius:50%;
        font-size:1rem; font-weight:800; margin-right:0.7rem;
    }}
    @media (max-width: 1500px) {{ .mc-rail {{ display:none; }} }}

    /* ── 다운로드 버튼 키움 ── */
    .stDownloadButton > button {{
        padding: 0.7rem 1.6rem !important;
        font-size: 0.98rem !important;
        min-height: 3rem;
    }}
    .stDownloadButton > button p {{ font-size: 0.98rem !important; font-weight: 700 !important; }}
    </style>
    """, unsafe_allow_html=True)


# ─────────────────────────── 상단 바 (하나만) ───────────────────────────

def _navbar() -> None:
    """MATCAUSE 로고(왼쪽) + 네비 버튼(오른쪽). Streamlit 위젯이라 클릭 가능."""
    cols = st.columns([2.5, 1, 1, 1, 1.2])
    with cols[0]:
        st.markdown(
            f'<div style="background:{NAVY_DEEP}; padding:0.5rem 1.2rem; '
            f'border-radius:10px; display:inline-block;">'
            f'<span style="color:#fff; font-size:1.25rem; font-weight:900; '
            f'letter-spacing:0.32em; padding-left:0.32em;">MATCAUSE</span></div>',
            unsafe_allow_html=True,
        )
    active = st.session_state.get("page", "진단")
    for i, (label, icon) in enumerate(
        [("진단", "🔍"), ("요약", "📊"), ("보관함", "🗄️")], start=1
    ):
        with cols[i]:
            btn_type = "primary" if label == active else "secondary"
            if st.button(f"{icon} {label}", use_container_width=True, type=btn_type,
                         key=f"nav_{label}"):
                st.session_state["page"] = label
                st.rerun()
    with cols[4]:
        logged = st.session_state.get("mc_user", "")
        lbl = f"👤 {logged}" if logged else "👤 로그인"
        if st.button(lbl, use_container_width=True, key="nav_login"):
            st.session_state["page"] = "로그인"
            st.rerun()


# ─────────────────────────── 히어로 + 소개 ───────────────────────────

def _hero_section() -> None:
    st.markdown(f"""
    <div class="mc-hero-banner" style="background-image:url('{_HERO_IMAGES[0]}');">
        <div class="mc-hero-overlay">
            <h1>결함 원인, 근거로 판별합니다</h1>
            <p>소재 물성부터 공정 센서 이상까지 — 이슈를 입력하면 AI가 경로를 분류하고,
            데이터 근거와 함께 리포트를 생성합니다.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _about_section() -> None:
    """에이전트 소개. CSS-only 등장 애니메이션 (JS IntersectionObserver 제거)."""
    st.markdown("""
    <div class="mc-about mc-ani">
        <div class="mc-ey">서비스 소개</div>
        <h2>반도체 결함 원인 판별, MATCAUSE가 함께합니다</h2>
    </div>

    <div class="mc-about-row mc-ani mc-ani-d1">
        <div class="mc-about-col">
            <h4>소재 경로 (Materials)</h4>
            <p>Materials Project 물성 데이터로 소재 리스크를 산정하고,
            대체 소재 후보를 자동 랭킹합니다. 모든 수치에는 출처가 붙어
            추적성이 보장됩니다.</p>
        </div>
        <div class="mc-about-col">
            <h4>공정 경로 (Process)</h4>
            <p>SECOM 공정 데이터(590개 센서 변수)에서 통계 검정으로
            불량군과 유의하게 다른 이상 변수를 규명합니다.
            클래스 불균형(1:14)도 처리합니다.</p>
        </div>
    </div>
    <div class="mc-about-divider mc-ani mc-ani-d2"></div>

    <div class="mc-features mc-ani mc-ani-d3">
        <div class="mc-feat-card">
            <div class="ic">🎯</div>
            <h3>AI 기반 자동 분류</h3>
            <p>이슈 텍스트에서 소재/공정 신호를 추출하고 LLM과 결합해
            경로를 자동 판정합니다. 모호한 경우도 정직하게 표기합니다.</p>
        </div>
        <div class="mc-feat-card">
            <div class="ic">📊</div>
            <h3>데이터 기반 근거</h3>
            <p>Materials Project API, SECOM 센서 통계 등 실제 데이터에서
            근거를 수집합니다. 합성 수치는 사용하지 않습니다.</p>
        </div>
        <div class="mc-feat-card">
            <div class="ic">📋</div>
            <h3>구조화 리포트 생성</h3>
            <p>OCAP / Gap Analysis 포맷으로 원인 · 조치 · 검증 · 출처를
            포함한 리포트를 생성하고 PDF 내보내기를 지원합니다.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────── 유틸 ───────────────────────────

def _step_rail(path_label: str = "분석") -> None:
    """우측 고정 스텝 플로우. 앵커(#step1~#step4)로 각 단계로 스크롤 이동."""
    links = [
        ("1", "이슈 입력", "step1"),
        ("2", "분기 판단", "step2"),
        ("3", f"{path_label} 근거", "step3"),
        ("4", "최종 리포트", "step4"),
    ]
    items = "".join(
        f'<a href="#{sid}"><span class="n">{n}</span>{label}</a>'
        for n, label, sid in links
    )
    st.markdown(
        f'<div class="mc-rail"><div class="rt">STEP FLOW</div>{items}</div>',
        unsafe_allow_html=True,
    )


def _eyebrow(tag: str, title: str, anchor: str | None = None) -> None:
    aid = f' id="{anchor}"' if anchor else ""
    st.markdown(
        f'<div class="mc-anchor"{aid}></div>'
        f'<div class="mc-eyebrow">{tag}</div><div class="mc-section-title">{title}</div>',
        unsafe_allow_html=True,
    )


def _category_badge(category: str) -> str:
    meta = _CATEGORY_META.get(category, {"label": category, "color": NAVY_SOFT, "emoji": "•"})
    return (
        f'<span class="mc-badge" style="background:{meta["color"]}">'
        f'{meta["emoji"]} {meta["label"]}</span>'
    )


def _clean_rationale(text: str | None) -> str:
    """Triage 근거 텍스트에서 내부 표시([MOCK])를 숨기고 자연스러운 문구로 정리.

    T-100(Bedrock 실연동) 전까지 MockLLM 이 남기는 '[MOCK] ...' 표식을 사용자
    화면에서 제거한다. 규칙·LLM 결합 상태(일치/우세/상충)를 자연스러운 한국어로
    바꿔 노출한다. 실제 LLM 연동 후에는 [MOCK] 이 없으므로 원문이 그대로 유지된다.
    """
    if not text:
        return "규칙 기반 신호를 바탕으로 분류했습니다."

    import re

    s = text
    # 1) '[MOCK] 소재 신호 N건 / 공정 신호 M건' → 자연 문구
    s = re.sub(
        r"\[MOCK\]\s*소재\s*신호\s*(\d+)\s*건\s*/\s*공정\s*신호\s*(\d+)\s*건",
        r"소재 신호 \1건, 공정 신호 \2건을 종합해 판단했습니다",
        s,
    )
    # 2) '[MOCK] 소재/공정 신호가 뚜렷하지 않음' → 자연 문구
    s = s.replace("[MOCK] 소재/공정 신호가 뚜렷하지 않음",
                  "소재·공정 신호가 뚜렷하지 않아 양쪽 경로를 함께 검토합니다")
    # 3) 남은 '[MOCK]' 표식 일반 제거
    s = s.replace("[MOCK]", "").strip()

    # 4) 결합 상태 문구를 사용자 친화적으로 다듬기
    s = s.replace("규칙·LLM 일치", "규칙 기반 신호와 AI 판단이 일치하여 확정")
    s = s.replace("규칙 신호 우세", "규칙 기반 신호가 우세")
    s = s.replace("LLM 우세", "AI 판단이 우세")
    s = s.replace("규칙·LLM 상충/모호", "규칙 기반 신호와 AI 판단이 엇갈려 신중히 검토")

    # 공백/구두점 정리
    s = re.sub(r"\s{2,}", " ", s).strip(" .")
    return (s + ".") if s and not s.endswith(".") else (s or "규칙 기반 신호를 바탕으로 분류했습니다.")


# ─────────────────────────── 렌더러 ───────────────────────────

def _render_triage(triage) -> None:
    _eyebrow("Step 02", "분기 판단 (Triage)", anchor="step2")
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown(
            f'<div class="mc-card">{_category_badge(triage.category.value)}'
            f'<div style="margin-top:0.8rem" class="mc-stat">'
            f'<div class="v">{triage.confidence:.2f}</div>'
            f'<div class="l">확신도 (0~1)</div></div></div>',
            unsafe_allow_html=True,
        )
        st.progress(min(1.0, max(0.0, triage.confidence)))
    with c2:
        st.markdown('<div class="mc-card">', unsafe_allow_html=True)
        st.markdown("**판단 근거**")
        st.write(_clean_rationale(triage.rationale))
        sig = triage.signals or {}
        st.caption(
            f"추출 화학식: {sig.get('extracted_formulas', [])} · "
            f"소재 키워드 {sig.get('material_keyword_count', 0)} · "
            f"공정 키워드 {sig.get('process_keyword_count', 0)}"
        )
        st.markdown("</div>", unsafe_allow_html=True)


def _render_material(finding) -> None:
    _eyebrow("Step 03", "소재 분석 근거", anchor="step3")
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
            st.bar_chart(bd, color=NAVY)
        st.caption(finding.summary)

    if finding.ranked_candidates:
        st.markdown("**대체 소재 후보 (리스크 오름차순)**")
        rows = []
        for i, c in enumerate(finding.ranked_candidates, 1):
            m = c.metrics or {}
            rows.append({
                "순위": i, "후보": c.name,
                "적합성": m.get("suitability", "-"), "리스크": c.score,
                "E_hull": m.get("energy_above_hull"),
                "band_gap": m.get("band_gap"),
                "mp-id": m.get("material_id"),
                "트레이드오프": c.tradeoffs or "",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _render_process(finding) -> None:
    _eyebrow("Step 03", "공정 분석 근거", anchor="step3")
    st_ = finding.stats or {}
    c1, c2, c3 = st.columns(3)
    for col, val, lab in (
        (c1, len(finding.anomalous_vars), "유의 이상 변수"),
        (c2, st_.get("n_features_tested", "-"), "검정 피처 수"),
        (c3, f"1:{st_.get('imbalance_ratio', '-')}", "클래스 불균형"),
    ):
        with col:
            st.markdown(
                f'<div class="mc-card mc-stat"><div class="v">{val}</div>'
                f'<div class="l">{lab}</div></div>', unsafe_allow_html=True)
    st.caption(finding.summary)

    top_vars = st_.get("top_vars", [])
    if top_vars:
        st.markdown("**효과크기 상위 이상 변수 (FDR 유의)**")
        dir_kr = {"higher_in_fail": "불량군 ↑", "lower_in_fail": "불량군 ↓"}
        rows = [
            {"변수": tv["feature"],
             "p_adj": f"{tv['p_adj']:.2e}",
             "Cohen d": round(tv["cohens_d"], 3),
             "방향": dir_kr.get(tv["direction"], tv["direction"]),
             "원인": "미매핑" if str(finding.cause_mappings.get(tv["feature"], "")).startswith("미매핑") else finding.cause_mappings.get(tv["feature"], "미매핑")}
            for tv in top_vars
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.info("SECOM 변수는 익명화되어 물리 원인 직접 매핑이 불가합니다.")
    elif finding.anomalous_vars:
        st.json({"anomalous_vars": finding.anomalous_vars})


def _demote_headings(md: str) -> str:
    """리포트 헤더 레벨을 낮춰 화면에서 너무 커 보이지 않게 한다.

    Streamlit 마크다운 헤더는 CSS 셀렉터로 안정적으로 잡기 어려워, 소스
    레벨을 직접 낮춘다. '# '(h1)→'#### ', '## '(h2)→'##### '.
    (테이블 구분선 '|---|' 등은 영향 없음: 줄 시작이 '# '/'## ' 인 경우만.)
    """
    out = []
    for line in md.split("\n"):
        if line.startswith("## "):
            out.append("##### " + line[3:])
        elif line.startswith("# "):
            out.append("#### " + line[2:])
        else:
            out.append(line)
    return "\n".join(out)


def _reorder_report_md(md: str) -> str:
    """'## 요약' 섹션을 맨 끝으로 이동 + 헤더 레벨 낮춤."""
    if "## 요약" in md:
        parts = md.split("## 요약", 1)
        before = parts[0]
        after = parts[1]
        next_h2 = after.find("\n## ")
        if next_h2 == -1:
            summary_body, rest = after, ""
        else:
            summary_body, rest = after[:next_h2], after[next_h2:]
        body = before.strip() + "\n" + rest.strip()
        md = body.strip() + "\n\n---\n\n## 요약" + summary_body
    return _demote_headings(md)


def _render_report(report, diagnosis_id: str) -> None:
    _eyebrow("Step 04", "최종 리포트", anchor="step4")

    # st.tabs 는 버전마다 DOM 이 달라 크기 제어가 불안정 → 큰 커스텀 버튼(세그먼트)으로 대체.
    view = st.session_state.get("report_view", "detail")
    st.markdown('<div class="mc-report-seg">', unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("📄  상세 리포트 (근거 포함)", use_container_width=True,
                     key="rv_detail", type=("primary" if view == "detail" else "secondary")):
            st.session_state["report_view"] = "detail"
            st.rerun()
    with b2:
        if st.button("📋  고객사 제출용", use_container_width=True,
                     key="rv_customer", type=("primary" if view == "customer" else "secondary")):
            st.session_state["report_view"] = "customer"
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    if view == "detail":
        st.caption(f"포맷: {report.format.value} · 근거 ID 포함(추적성)")
        st.markdown(_reorder_report_md(report.markdown))
        st.markdown("")
        st.download_button("📥  상세 리포트 내보내기 (.md)", data=report.markdown,
                           file_name=f"matcause_detail_{report.id}.md", mime="text/markdown",
                           use_container_width=True)
    else:
        st.caption("근거 ID 없이 요약 중심")
        try:
            cust = get_service().build_customer_report(diagnosis_id)
        except Exception:  # noqa: BLE001
            cust = None
        if cust is None:
            st.info("고객사 리포트를 생성할 수 없습니다.")
            return
        st.markdown(_reorder_report_md(cust.markdown))
        st.markdown("")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("📥  고객사 리포트 (.md)", data=cust.markdown,
                               file_name=f"matcause_customer_{cust.id}.md", mime="text/markdown",
                               use_container_width=True)
        with c2:
            try:
                pdf = get_service().customer_report_pdf(diagnosis_id)
                if pdf:
                    st.download_button("📥  고객사 리포트 (PDF)", data=pdf,
                                       file_name=f"matcause_customer_{cust.id}.pdf",
                                       mime="application/pdf", use_container_width=True)
            except Exception:  # noqa: BLE001
                pass


# ─────────────────────────── 페이지: 진단 ───────────────────────────

def page_diagnose() -> None:
    _hero_section()
    _about_section()

    st.markdown("---")
    _eyebrow("Step 01", "이슈 입력", anchor="step1")
    text = st.text_area(
        "issue", value=st.session_state.get("issue_text", _EXAMPLE),
        height=120, placeholder="예: 특정 로트에서 누설전류 상승…",
        label_visibility="collapsed",
    )
    col_a, col_b = st.columns(2)
    with col_a:
        override = st.selectbox(
            "경로 수동 지정", options=["자동(Triage)", "MATERIAL", "PROCESS"], index=0,
            help="Triage를 무시하고 특정 경로 강제",
        )
    with col_b:
        st.write(""); st.write("")
        run = st.button("진단 시작", type="primary", use_container_width=True)

    if run:
        if not text.strip():
            st.error("이슈 텍스트를 입력하세요.")
            return
        st.session_state["issue_text"] = text
        ov = None if override == "자동(Triage)" else override
        with st.spinner("진단 중…"):
            try:
                dx = get_service().diagnose(text, override=ov)
                st.session_state["diagnosis_id"] = dx.id
            except Exception as exc:  # noqa: BLE001
                st.exception(exc)
                return

    dx_id = st.session_state.get("diagnosis_id")
    if not dx_id:
        return
    dx = get_service().get(dx_id)
    if dx is None:
        st.warning("진단 결과를 찾을 수 없습니다.")
        return
    if dx.error:
        st.error(f"진단 오류: {dx.error}")

    # 우측 스텝 플로우(클릭 시 해당 단계로 스크롤)
    _step_rail("소재 분석" if dx.material_finding else "공정 분석")

    if dx.triage:
        _render_triage(dx.triage)
    if dx.material_finding:
        _render_material(dx.material_finding)
    elif dx.process_finding:
        _render_process(dx.process_finding)
    if dx.report:
        _render_report(dx.report, dx.id)
    status = dx.status.value if isinstance(dx.status, DiagnosisStatus) else dx.status
    st.caption(f"진단 ID: {dx.id} · 상태: {status}")


# ─────────────────────────── 페이지: 요약 ───────────────────────────

def _diagnosis_row(dx) -> dict:
    cat = dx.triage.category.value if dx.triage else "-"
    conf = f"{dx.triage.confidence:.2f}" if dx.triage else "-"
    status = dx.status.value if isinstance(dx.status, DiagnosisStatus) else str(dx.status)
    txt = (dx.issue.raw_text or "").strip().replace("\n", " ")
    return {
        "ID": dx.id, "시각": dx.created_at.strftime("%Y-%m-%d %H:%M"),
        "이슈": txt[:48] + "…" if len(txt) > 48 else txt,
        "분류": _CATEGORY_META.get(cat, {}).get("label", cat),
        "확신도": conf, "상태": status,
        "리포트": "✅" if dx.report else "—",
    }


def page_summary() -> None:
    st.markdown(
        '<div class="mc-page-hero"><h2>📊 진단 요약</h2>'
        '<p>접수 · 처리된 문제를 한눈에 집계합니다.</p></div>',
        unsafe_allow_html=True)
    items = get_service().list_all()
    _eyebrow("Overview", "진단 현황")
    total = len(items)
    c1, c2, c3, c4 = st.columns(4)
    for col, val, lab in (
        (c1, total, "총 진단"),
        (c2, sum(1 for d in items if d.material_finding), "소재"),
        (c3, sum(1 for d in items if d.process_finding), "공정"),
        (c4, sum(1 for d in items if d.report), "리포트"),
    ):
        with col:
            st.markdown(f'<div class="mc-card mc-stat"><div class="v">{val}</div>'
                        f'<div class="l">{lab}</div></div>', unsafe_allow_html=True)
    if total == 0:
        st.info("아직 진단 이력이 없습니다. '진단' 탭에서 시작해 보세요.")
        return
    _eyebrow("Distribution", "분류 분포")
    dist: dict[str, int] = {}
    for d in items:
        cat = d.triage.category.value if d.triage else "미분류"
        lab = _CATEGORY_META.get(cat, {}).get("label", cat)
        dist[lab] = dist.get(lab, 0) + 1
    st.bar_chart(pd.DataFrame({"분류": list(dist.keys()), "건수": list(dist.values())}).set_index("분류"), color=NAVY)
    _eyebrow("Recent", "최근 진단")
    st.dataframe(pd.DataFrame([_diagnosis_row(d) for d in items]), hide_index=True, use_container_width=True)


# ─────────────────────────── 페이지: 보관함 ───────────────────────────

def page_archive() -> None:
    st.markdown(
        '<div class="mc-page-hero"><h2>🗄️ 리포트 보관함</h2>'
        '<p>생성된 리포트를 열람하고 내보냅니다.</p></div>',
        unsafe_allow_html=True)
    items = [d for d in get_service().list_all() if d.report]
    _eyebrow("Archive", "보관된 리포트")
    if not items:
        st.info("보관된 리포트가 없습니다. 진단을 완료하면 여기에 쌓입니다.")
        return
    labels = []
    for d in items:
        cat = d.triage.category.value if d.triage else "-"
        catlab = _CATEGORY_META.get(cat, {}).get("label", cat)
        ts = d.created_at.strftime("%m-%d %H:%M")
        txt = (d.issue.raw_text or "").strip().replace("\n", " ")[:36]
        labels.append(f"[{ts}] {catlab} · {txt}…")
    idx = st.selectbox("리포트 선택", list(range(len(items))), format_func=lambda i: labels[i])
    dx = items[idx]
    cat = dx.triage.category.value if dx.triage else "-"
    st.markdown(
        f'<div class="mc-card">{_category_badge(cat)} &nbsp;<b>ID</b> {dx.id} · '
        f'<b>생성</b> {dx.created_at.strftime("%Y-%m-%d %H:%M")}</div>',
        unsafe_allow_html=True)
    tab_d, tab_c = st.tabs(["상세 리포트", "고객사 제출용"])
    with tab_d:
        st.markdown(_reorder_report_md(dx.report.markdown))
        st.download_button("📥  내보내기 (.md)", data=dx.report.markdown,
                           file_name=f"matcause_{dx.report.id}.md", mime="text/markdown",
                           use_container_width=True)
    with tab_c:
        try:
            cust = get_service().build_customer_report(dx.id)
        except Exception:  # noqa: BLE001
            cust = None
        if not cust:
            st.info("고객사 리포트를 생성할 수 없습니다.")
        else:
            st.markdown(_reorder_report_md(cust.markdown))
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📥  고객사 (.md)", data=cust.markdown,
                                   file_name=f"mc_cust_{cust.id}.md", mime="text/markdown",
                                   use_container_width=True)
            with c2:
                try:
                    pdf = get_service().customer_report_pdf(dx.id)
                    if pdf:
                        st.download_button("📥  고객사 (PDF)", data=pdf,
                                           file_name=f"mc_cust_{cust.id}.pdf", mime="application/pdf",
                                           use_container_width=True)
                except Exception:  # noqa: BLE001
                    pass


# ─────────────────────────── 페이지: 로그인 (UI 전용) ───────────────────────────

def page_login() -> None:
    _, center, _ = st.columns([1, 1.4, 1])
    with center:
        st.markdown(
            f'<h2 style="text-align:center; color:{NAVY}; font-weight:800; '
            f'margin-bottom:1.4rem;">👤 계정</h2>',
            unsafe_allow_html=True,
        )
        tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

        # ── 로그인 ──
        with tab_login:
            uid = st.text_input("아이디", placeholder="아이디를 입력하세요", key="login_id")
            st.text_input("비밀번호", type="password",
                          placeholder="비밀번호를 입력하세요", key="login_pw")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("로그인", type="primary", use_container_width=True, key="btn_login"):
                    if uid.strip():
                        st.session_state["mc_user"] = uid.strip()
                        st.session_state["page"] = "진단"
                        st.rerun()
                    else:
                        st.error("아이디를 입력하세요.")
            with c2:
                if st.button("게스트 접속", use_container_width=True, key="btn_guest"):
                    st.session_state["mc_user"] = "게스트"
                    st.session_state["page"] = "진단"
                    st.rerun()

        # ── 회원가입 (UI 전용) ──
        with tab_signup:
            new_id = st.text_input("아이디", placeholder="사용할 아이디", key="signup_id")
            new_pw = st.text_input("비밀번호", type="password",
                                   placeholder="비밀번호", key="signup_pw")
            new_pw2 = st.text_input("비밀번호 확인", type="password",
                                    placeholder="비밀번호 재입력", key="signup_pw2")
            st.text_input("이메일 (선택)", placeholder="you@example.com", key="signup_email")
            if st.button("회원가입", type="primary", use_container_width=True, key="btn_signup"):
                if not new_id.strip():
                    st.error("아이디를 입력하세요.")
                elif not new_pw:
                    st.error("비밀번호를 입력하세요.")
                elif new_pw != new_pw2:
                    st.error("비밀번호가 일치하지 않습니다.")
                else:
                    st.success(f"'{new_id.strip()}' 계정이 생성되었습니다. (데모) 로그인 탭에서 접속하세요.")

        st.caption("현재 데모 모드입니다. 실제 인증·계정 저장은 추후 연동됩니다.")


# ─────────────────────────── 엔트리 ───────────────────────────

_PAGES = {
    "진단": page_diagnose,
    "요약": page_summary,
    "보관함": page_archive,
    "로그인": page_login,
}


def main() -> None:
    st.set_page_config(page_title="MATCAUSE", page_icon="🔷", layout="wide")
    _inject_styles()
    if "page" not in st.session_state:
        st.session_state["page"] = "진단"
    _navbar()
    _PAGES.get(st.session_state["page"], page_diagnose)()


if __name__ == "__main__":
    main()
