"""응용 적합성 스코어링 회귀 테스트.

이 파일은 두 가지 버그가 재발하지 않도록 고정한다:

1. **편차율 계산 버그** — 이전에는 밴드갭이 범위 경계에 아주 가까워도
   (예: 하한 바로 밖) 중앙값(midpoint) 대비로 편차를 재서 리스크가 극단적으로
   튀었다(예: 경계 0.1eV 밖인데 ~96/100). 수정 후에는 '가장 가까운 경계로부터의
   거리'를 '범위 폭' 대비 비율로 계산하고, 경계에서 완만하게 증가한다.

2. **계단식(cliff) 판정** — 경계에서 리스크가 0 → 100 으로 급변하지 않고,
   범위 폭의 30% 밖에서 100 에 도달하도록 선형으로 완만하게 증가한다.

물리 상식 고정값(회귀 기준):
  SiC(3.26eV)  → 응용 리스크 0,   종합 0.0
  GaN(3.40eV)  → 응용 리스크 0,   종합 0.0
  GaAs(1.42eV) → 응용 리스크 43,  종합 19.1
"""

from __future__ import annotations

import pytest

from matcause.plugins.semiconductor.application_profile import PROFILES
from matcause.plugins.semiconductor.risk_scorer import (
    _application_suitability_score,
    score_material,
)

POWER = PROFILES["power"]

# 실제 MP/문헌 밴드갭에 기반한 대표 소재 (안정상, E_hull=0)
SIC = {
    "material_id": "mp-7140", "formula_pretty": "SiC",
    "energy_above_hull": 0.0, "formation_energy_per_atom": -0.321,
    "is_stable": True, "band_gap": 3.26,
}
GAN = {
    "material_id": "mp-804", "formula_pretty": "GaN",
    "energy_above_hull": 0.0, "formation_energy_per_atom": -0.587,
    "is_stable": True, "band_gap": 3.40,
}
GAAS = {
    "material_id": "mp-2534", "formula_pretty": "GaAs",
    "energy_above_hull": 0.0, "formation_energy_per_atom": -0.377,
    "is_stable": True, "band_gap": 1.42,
}


# ─────────────────────────── 1. 대표 소재 물리 상식 고정 ───────────────────────────


def test_sic_fits_power_zero_app_risk():
    """SiC(3.26eV)는 파워 WBG 적합 → 응용 리스크 0, 종합 낮음."""
    app_score, _ = _application_suitability_score(SIC["band_gap"], POWER)
    assert app_score == 0.0
    r = score_material(SIC, profile=POWER)
    assert r.breakdown.get("application_suitability") == 0.0
    assert r.score < 5.0


def test_gan_fits_power_zero_app_risk():
    """GaN(3.40eV)도 파워 WBG 적합 → 응용 리스크 0, 종합 낮음."""
    app_score, _ = _application_suitability_score(GAN["band_gap"], POWER)
    assert app_score == 0.0
    r = score_material(GAN, profile=POWER)
    assert r.breakdown.get("application_suitability") == 0.0
    assert r.score < 5.0


def test_gaas_unfit_for_power_moderate_risk():
    """GaAs(1.42eV)는 협밴드갭 → 파워 부적합, 응용 리스크 상승(극단 아님)."""
    app_score, note = _application_suitability_score(GAAS["band_gap"], POWER)
    assert app_score > 0.0
    # 하한 2.0에서 0.58eV 밖 / 범위폭 4.5 → 완만한 중간 수준(30~55 대역)
    assert 30.0 <= app_score <= 55.0
    assert "band_gap" in note
    r = score_material(GAAS, profile=POWER)
    # breakdown 은 round(app_score, 1) 로 저장되므로 근사 비교
    assert r.breakdown.get("application_suitability") == pytest.approx(app_score, abs=0.1)


def test_ordering_gaas_riskier_than_wbg():
    """물리 상식: 파워 응용에서 GaAs > SiC, GaN 리스크."""
    sic = score_material(SIC, profile=POWER).score
    gan = score_material(GAN, profile=POWER).score
    gaas = score_material(GAAS, profile=POWER).score
    assert gaas > sic
    assert gaas > gan


def test_regression_fixed_values():
    """회귀 기준값 고정 (로직 변경 시 여기가 깨지면 의도 확인 필요)."""
    assert score_material(SIC, profile=POWER).score == pytest.approx(0.0, abs=0.05)
    assert score_material(GAN, profile=POWER).score == pytest.approx(0.0, abs=0.05)
    # GaAs 종합 19.1 (app 43 × 가중치 재정규화). 계산 방식 유지 시 고정.
    assert score_material(GAAS, profile=POWER).score == pytest.approx(19.1, abs=0.5)
    assert _application_suitability_score(GAAS["band_gap"], POWER)[0] == pytest.approx(43.0, abs=0.5)


# ─────────────────────────── 2. 경계 근처 완만화 (핵심 회귀 방지) ───────────────────────────


def test_boundary_values_are_zero_risk():
    """범위 경계값 자체(하한 2.0, 상한 6.5)는 리스크 0 (범위 '내' 포함)."""
    lo, _ = _application_suitability_score(POWER.band_gap_min, POWER)
    hi, _ = _application_suitability_score(POWER.band_gap_max, POWER)
    assert lo == 0.0
    assert hi == 0.0


def test_just_outside_boundary_is_small_not_extreme():
    """★핵심★ 경계 바로 밖(0.1eV) 값이 극단적으로 튀지 않는다.

    이전 버그: bg가 경계 근처인데 중앙값 대비 편차로 계산돼 ~96/100 처럼 튐.
    수정 후: 경계에서 0.1eV 밖이면 작은 리스크(< 15)여야 한다.
    """
    below, _ = _application_suitability_score(POWER.band_gap_min - 0.1, POWER)  # 1.9eV
    above, _ = _application_suitability_score(POWER.band_gap_max + 0.1, POWER)  # 6.6eV
    assert 0.0 < below < 15.0, f"하한 바로 밖 리스크가 과도함: {below}"
    assert 0.0 < above < 15.0, f"상한 바로 밖 리스크가 과도함: {above}"


def test_no_cliff_monotonic_increase_below_lower_bound():
    """하한 아래로 갈수록 리스크가 '단조 증가'하고, 인접 스텝 간 급변이 없다.

    계단식(0→100)이면 이 테스트가 깨진다. 완만한 선형 증가여야 한다.
    """
    lo = POWER.band_gap_min  # 2.0
    # 경계에서 아래로 0.0, 0.1, ... 1.5 eV 까지 스캔
    xs = [lo - d for d in [0.0, 0.1, 0.3, 0.6, 0.9, 1.2, 1.5]]
    scores = [_application_suitability_score(x, POWER)[0] for x in xs]

    # (a) 단조 증가(비감소)
    for a, b in zip(scores, scores[1:]):
        assert b >= a, f"단조 증가 위반: {scores}"

    # (b) 경계값은 0
    assert scores[0] == 0.0

    # (c) 인접 스텝 간 급변(cliff) 없음: 한 스텝 증가폭이 60 미만
    #     (계단식이면 0→100 처럼 100 점프가 생긴다)
    for a, b in zip(scores, scores[1:]):
        assert (b - a) < 60.0, f"경계 근처 급변(cliff) 감지: {scores}"


def test_no_cliff_monotonic_increase_above_upper_bound():
    """상한 위로도 완만한 단조 증가 (대칭성)."""
    hi = POWER.band_gap_max  # 6.5
    xs = [hi + d for d in [0.0, 0.1, 0.3, 0.6, 0.9, 1.2, 1.5]]
    scores = [_application_suitability_score(x, POWER)[0] for x in xs]
    for a, b in zip(scores, scores[1:]):
        assert b >= a
        assert (b - a) < 60.0
    assert scores[0] == 0.0


def test_far_outside_saturates_at_100():
    """범위에서 충분히 멀면(범위폭 30% 이상 밖) 100 에 도달."""
    lo = POWER.band_gap_min
    span = POWER.band_gap_max - POWER.band_gap_min  # 4.5
    far = lo - span * 0.4   # 30% 마진보다 더 밖 → 100
    score, _ = _application_suitability_score(far, POWER)
    assert score == 100.0


def test_deviation_is_range_relative_not_midpoint_relative():
    """편차가 '범위 폭' 기준인지 검증 (midpoint 기준 버그 방지).

    범위 폭이 다른 두 프로파일에서, 경계로부터 같은 절대거리(0.1eV)면
    범위 폭이 넓은 쪽이 더 낮은 리스크여야 한다(폭 대비 비율이 작으므로).
    midpoint 기준이면 이 관계가 성립하지 않는다.
    """
    from matcause.plugins.semiconductor.application_profile import ApplicationProfile

    narrow = ApplicationProfile(name="n", band_gap_min=2.0, band_gap_max=3.0)   # 폭 1.0
    wide = ApplicationProfile(name="w", band_gap_min=2.0, band_gap_max=10.0)    # 폭 8.0
    d = 0.1
    s_narrow, _ = _application_suitability_score(narrow.band_gap_min - d, narrow)
    s_wide, _ = _application_suitability_score(wide.band_gap_min - d, wide)
    assert s_wide < s_narrow, (
        f"범위 폭 대비 편차가 아님: 넓은범위 {s_wide} vs 좁은범위 {s_narrow}"
    )


def test_symmetric_distance_gives_symmetric_score():
    """하한/상한에서 같은 거리면 같은 리스크 (경계 방향 무관)."""
    lo = POWER.band_gap_min
    hi = POWER.band_gap_max
    d = 0.5
    s_below, _ = _application_suitability_score(lo - d, POWER)
    s_above, _ = _application_suitability_score(hi + d, POWER)
    assert s_below == pytest.approx(s_above, abs=0.01)


# ─────────────────────────── 3. 엣지: band_gap 없음 ───────────────────────────


def test_missing_band_gap_no_app_risk():
    """band_gap 이 없으면 응용 적합성 평가 불가 → 리스크 0, breakdown 제외."""
    score, note = _application_suitability_score(None, POWER)
    assert score == 0.0
    assert "없음" in note
    mat = {"material_id": "m", "energy_above_hull": 0.0, "is_stable": True}
    r = score_material(mat, profile=POWER)
    assert "application_suitability" not in r.breakdown
