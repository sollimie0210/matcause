"""MockLLM 요약 합성 + 응용 적합성(리스크/랭킹) 테스트."""

from __future__ import annotations

from matcause.core.llm.base import system, user
from matcause.core.llm.mock_client import MockLLMClient
from matcause.plugins.semiconductor.application_profile import (
    PROFILES,
    detect_application,
)
from matcause.plugins.semiconductor.alternatives_ranker import rank_alternatives
from matcause.plugins.semiconductor.risk_scorer import score_material


# ── 1. MockLLM 요약 합성 ──


def test_mock_summary_is_real_sentences_not_prompt_echo():
    llm = MockLLMClient()
    prompt = (
        "아래는 리포트 구조화 데이터다.\n"
        "[판정 원인]\nGaN 소재 리스크 0.0/100, 안정상 mp-804\n\n"
        "[권장 조치]\n공정 요인 우선 조사 권장; 로트 편차 측정\n\n"
        "[근거 요약]\nenergy_above_hull=0.0; formation_energy=-0.67\n\n"
        "요약(2~3문장):"
    )
    out = llm.complete([system("s"), user(prompt)]).text
    # 프롬프트를 그대로 반환하지 않음
    assert "[판정 원인]" not in out
    assert "요약(2~3문장)" not in out
    # 실제 문장처럼 마침표로 끝나는 2~3문장
    assert out.count(".") >= 1
    assert "분석 결과" in out
    assert "근거" in out  # 근거 기반 언급


def test_mock_summary_handles_missing_sections():
    llm = MockLLMClient()
    prompt = "[판정 원인]\n원인 미상\n\n[권장 조치]\n없음\n\n[근거 요약]\n정량 근거 없음\n"
    out = llm.complete([user(prompt)]).text
    assert out and "[판정 원인]" not in out


def test_non_summary_prompt_still_mock_echo():
    llm = MockLLMClient()
    out = llm.complete([user("그냥 일반 질문")]).text
    assert out.startswith("[MOCK]")


# ── 2. 응용 감지 ──


def test_detect_power_application():
    p = detect_application("파워 소자 고전압 인버터용 소재 이슈")
    assert p is not None and p.name == "power"


def test_detect_none_when_no_app_keyword():
    assert detect_application("일반 소재 물성 문의") is None


# ── 3. 리스크 산정에 응용 적합성 반영 ──


def test_narrow_bandgap_material_risky_for_power():
    # GaAs(band_gap 1.42)는 안정하지만 파워 응용엔 밴드갭이 좁다 → 리스크 상승
    gaas = {
        "material_id": "mp-2534", "formula_pretty": "GaAs",
        "formation_energy_per_atom": -0.45, "energy_above_hull": 0.0,
        "band_gap": 1.42, "is_stable": True,
    }
    base = score_material(gaas)
    power = score_material(gaas, profile=PROFILES["power"])
    assert base.score == 0.0                      # 안정성만 보면 0
    assert power.score > base.score               # 응용 적합성 반영 시 상승
    assert "application_suitability" in power.breakdown
    assert power.breakdown["application_suitability"] > 0


def test_widegap_material_fits_power():
    # SiC(2.2대) 급이면 파워 요구 범위 내 → 응용 적합성 리스크 0
    sic = {
        "material_id": "mp-1204356", "formula_pretty": "SiC",
        "formation_energy_per_atom": -0.31, "energy_above_hull": 0.0,
        "band_gap": 2.4, "is_stable": True,
    }
    r = score_material(sic, profile=PROFILES["power"])
    assert r.breakdown.get("application_suitability") == 0.0


# ── 4. 대체 랭킹 적합성 필터/경고 ──

_SRC_GAN = {
    "material_id": "mp-804", "formula_pretty": "GaN",
    "formation_energy_per_atom": -0.67, "energy_above_hull": 0.0,
    "band_gap": 3.2, "is_stable": True,   # source band_gap 넓음
}
_CAND_GAAS = {
    "material_id": "mp-2534", "formula_pretty": "GaAs",
    "formation_energy_per_atom": -0.45, "energy_above_hull": 0.0,
    "band_gap": 1.42, "is_stable": True,  # 파워 범위[2.0~6.5] 이탈
}
_CAND_ALN = {
    "material_id": "mp-661", "formula_pretty": "AlN",
    "formation_energy_per_atom": -1.6, "energy_above_hull": 0.0,
    "band_gap": 4.0, "is_stable": True,
}


def test_ranking_flags_unfit_candidate():
    res = rank_alternatives(_SRC_GAN, [_CAND_GAAS, _CAND_ALN], k=5)
    by_name = {c.name: c for c in res.candidates}
    assert by_name["GaAs"].metrics["suitability"] == "적합도 낮음"
    assert "적합도 낮음" in (by_name["GaAs"].tradeoffs or "")
    # 적합 후보가 부적합 후보보다 앞 순위
    names = [c.name for c in res.candidates]
    assert names.index("AlN") < names.index("GaAs")
    assert any("적합도 낮음" in n for n in res.notes)


def test_ranking_excludes_unfit_when_requested():
    res = rank_alternatives(
        _SRC_GAN, [_CAND_GAAS, _CAND_ALN], k=5, exclude_unfit=True
    )
    names = [c.name for c in res.candidates]
    assert "GaAs" not in names
    assert "AlN" in names
    assert any("제외" in n for n in res.notes)


def test_profile_range_is_priority_over_source_deviation():
    # source = GaAs(1.42). 프로파일(power)이 있으면 '요구 범위' 기준으로 판정:
    #  - AlN(4.05)은 power 범위[2.0~6.5] 내 → 적합 (source 대비 편차는 크지만 무시)
    #  - InN(0.0)은 범위 이탈 → 적합도 낮음
    src_gaas = {
        "material_id": "mp-2534", "formula_pretty": "GaAs",
        "formation_energy_per_atom": -0.45, "energy_above_hull": 0.0,
        "band_gap": 1.42, "is_stable": True,
    }
    inn = {
        "material_id": "mp-22205", "formula_pretty": "InN",
        "formation_energy_per_atom": -0.15, "energy_above_hull": 0.0,
        "band_gap": 0.0, "is_stable": True,
    }
    res = rank_alternatives(
        src_gaas, [_CAND_ALN, inn], k=5, profile=PROFILES["power"]
    )
    by = {c.name: c for c in res.candidates}
    assert by["AlN"].metrics["suitability"] == "적합"       # 범위 내 → 적합
    assert by["InN"].metrics["suitability"] == "적합도 낮음"  # 범위 이탈
    assert "요구 band_gap" in (by["InN"].tradeoffs or "")
    # 적합 후보(AlN)가 앞 순위
    names = [c.name for c in res.candidates]
    assert names.index("AlN") < names.index("InN")


def test_ranking_dedups_by_formula_and_excludes_source():
    # 같은 화학식(GaAs)이 다른 material_id 로 여러 번 들어와도 1개만 남고,
    # source 와 같은 화학식은 제외된다 (Ga3As 오기/중복 방지).
    src_gan = {
        "material_id": "mp-804", "formula_pretty": "GaN",
        "energy_above_hull": 0.0, "band_gap": 3.2, "is_stable": True,
    }
    cands = [
        {"material_id": "mp-2534", "formula_pretty": "GaAs", "energy_above_hull": 0.0, "band_gap": 0.19, "is_stable": True},
        {"material_id": "mp-99999", "formula_pretty": "GaAs", "energy_above_hull": 0.02, "band_gap": 0.2, "is_stable": True},  # 중복 화학식
        {"material_id": "mp-804", "formula_pretty": "GaN", "energy_above_hull": 0.0, "band_gap": 3.2, "is_stable": True},  # source 자신
        {"material_id": "mp-661", "formula_pretty": "AlN", "energy_above_hull": 0.0, "band_gap": 4.0, "is_stable": True},
    ]
    res = rank_alternatives(src_gan, cands, k=10)
    names = [c.name for c in res.candidates]
    assert names.count("GaAs") == 1     # 화학식 중복 제거
    assert "GaN" not in names           # source 제외
    assert "AlN" in names
