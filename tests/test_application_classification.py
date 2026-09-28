"""응용 분류(LLM 우선 + 키워드 폴백) & 폴백 적합성 경로 회귀 테스트.

이 파일이 고정하는 것:

1. **LLM 기반 응용 분류** — 실제 LLM 모드에서는 고정 키워드에 없는 문맥 표현
   ('항복전압', '고전압 스위칭', '에피 성장')도 응용을 잡는다. MockLLMClient
   (model_id에 'mock' 포함)이면 기존 키워드 감지로 폴백한다.

2. **폴백 적합성 경로(profile=None)의 무-계단(no-cliff)** — 응용이 아예 감지되지
   않아도, 대체 후보 적합성이 원본 band_gap 주변 허용밴드 경계에서 완만하게
   증가한다(0→100 급변 없음). SiC 픽스와 동일한 수학 원칙(범위폭 대비 + 완만)이
   폴백에도 적용됐는지 검증한다.
"""

from __future__ import annotations

import pytest

from matcause.core.llm.mock_client import MockLLMClient
from matcause.plugins.semiconductor.application_profile import (
    PROFILES,
    classify_application,
    detect_application,
)
from matcause.plugins.semiconductor.risk_scorer import (
    FALLBACK_TOLERANCE_FRAC,
    _source_relative_suitability_score,
)


class FakeGatewayLLM:
    """실제 LLM(비-Mock) 흉내. model_id에 'mock'이 없어 LLM 분류 경로를 탄다.

    complete_json 은 주어진 매핑에서 '텍스트에 포함된 키'로 응답을 고른다.
    네트워크 없이 결정론적으로 LLM 분류 경로를 검증하기 위한 테스트 더블.
    """

    def __init__(self, responses: dict[str, dict], model_id: str = "bedrock-haiku"):
        self.model_id = model_id
        self._responses = responses
        self.calls = 0

    def complete_json(self, messages, **kwargs):
        self.calls += 1
        text = messages[-1].content
        for key, resp in self._responses.items():
            if key in text:
                return resp
        return {"application": "unknown", "confidence": 0.0, "rationale": "no match"}

    def complete(self, messages, **kwargs):  # 미사용(분류엔 complete_json만)
        raise NotImplementedError


# ─────────────────── 1. LLM 기반 응용 분류 (문맥 표현) ───────────────────


@pytest.mark.parametrize(
    "text",
    [
        "GaN HEMT 웨이퍼에서 항복전압이 규격 미달로 떨어졌습니다.",
        "고전압 스위칭 소자에서 누설전류 급증.",
        "에피 성장 후 전력 변환 소자의 손실이 증가.",
    ],
)
def test_llm_classifies_power_from_context(text):
    """키워드 리스트에 없는 문맥 표현도 실제 LLM이 power로 분류."""
    llm = FakeGatewayLLM(
        {
            "항복전압": {"application": "power", "confidence": 0.9, "rationale": "항복전압=고전압"},
            "고전압 스위칭": {"application": "power", "confidence": 0.88, "rationale": "스위칭"},
            "전력 변환": {"application": "power", "confidence": 0.85, "rationale": "전력변환"},
        }
    )
    profile = classify_application(text, llm)
    assert profile is not None
    assert profile.name == "power"
    assert llm.calls == 1  # LLM이 실제로 호출됨


def test_llm_low_confidence_falls_back_to_keyword():
    """LLM 신뢰도가 낮으면 LLM 결과를 안 믿고 키워드 폴백으로 내려간다."""
    text = "파워 소자 이슈"  # 키워드 '파워'는 잡힘
    llm = FakeGatewayLLM(
        {"파워": {"application": "power", "confidence": 0.2, "rationale": "저신뢰"}}
    )
    profile = classify_application(text, llm)
    # 저신뢰 → 키워드 폴백. '파워'가 키워드에 있으므로 power.
    assert profile is not None and profile.name == "power"


def test_llm_unknown_with_no_keyword_returns_none():
    """LLM이 unknown이고 키워드도 없으면 None(응용 미감지)."""
    text = "이 로트의 결함 재현성이 낮습니다."  # 응용 신호 없음
    llm = FakeGatewayLLM({})  # 항상 unknown
    profile = classify_application(text, llm)
    assert profile is None


def test_llm_failure_falls_back_to_keyword():
    """LLM 호출이 예외를 던져도 키워드 폴백으로 안전하게 내려간다."""

    class BoomLLM:
        model_id = "bedrock-haiku"

        def complete_json(self, messages, **kwargs):
            raise RuntimeError("gateway down")

    text = "고전압 인버터 파워 모듈"  # 키워드 '고전압/파워/인버터'
    profile = classify_application(text, BoomLLM())
    assert profile is not None and profile.name == "power"


# ─────────────────── 2. Mock 모드는 키워드 폴백 유지 ───────────────────


def test_mock_llm_uses_keyword_detection():
    """MockLLMClient(model_id='mock-llm')이면 LLM 분류를 건너뛰고 키워드만 쓴다."""
    mock = MockLLMClient()
    # 키워드에 없는 문맥 표현만 있는 텍스트 → 키워드로는 못 잡음 → None
    ctx_only = "항복전압이 규격 미달"  # '항복전압'은 키워드 리스트에 없음
    assert classify_application(ctx_only, mock) is None
    # 키워드가 있는 텍스트 → 키워드로 감지
    assert classify_application("파워 소자 불량", mock).name == "power"


def test_mock_matches_plain_keyword_detection():
    """Mock 경로 결과는 detect_application(키워드)과 동일해야 한다."""
    for text in ["led 발광 효율", "게이트 유전체 누설", "로직 트랜지스터 스위칭", "무관한 텍스트"]:
        mock = MockLLMClient()
        a = classify_application(text, mock)
        b = detect_application(text)
        assert (a.name if a else None) == (b.name if b else None)


# ─────────────────── 3. 폴백 적합성 경로: 무-계단 완만 증가 ───────────────────

SRC_BG = 2.0  # 원본 소재 band_gap 가정


def test_fallback_within_tolerance_is_zero():
    """원본 대비 허용밴드(±FALLBACK_TOLERANCE_FRAC) 안이면 리스크 0."""
    tol = SRC_BG * FALLBACK_TOLERANCE_FRAC
    inside = SRC_BG + tol * 0.5
    score, _ = _source_relative_suitability_score(inside, SRC_BG)
    assert score == 0.0


def test_fallback_boundary_is_zero():
    """허용밴드 경계값 자체는 리스크 0(범위 '내')."""
    tol = SRC_BG * FALLBACK_TOLERANCE_FRAC
    lo_score, _ = _source_relative_suitability_score(SRC_BG - tol, SRC_BG)
    hi_score, _ = _source_relative_suitability_score(SRC_BG + tol, SRC_BG)
    assert lo_score == 0.0
    assert hi_score == 0.0


def test_fallback_just_outside_is_small_not_extreme():
    """★핵심★ 허용밴드 바로 밖이 극단적으로 튀지 않는다(옛 50% 하드컷 버그 방지)."""
    tol = SRC_BG * FALLBACK_TOLERANCE_FRAC
    just_out = SRC_BG - tol - 0.05
    score, _ = _source_relative_suitability_score(just_out, SRC_BG)
    assert 0.0 < score < 40.0, f"경계 바로 밖 리스크 과도: {score}"


def test_fallback_no_cliff_monotonic_increase():
    """허용밴드 밖으로 갈수록 단조 증가하며 인접 스텝 급변(cliff)이 없다."""
    tol = SRC_BG * FALLBACK_TOLERANCE_FRAC
    lo = SRC_BG - tol
    xs = [lo - d for d in [0.0, 0.05, 0.15, 0.3, 0.5, 0.8, 1.2]]
    scores = [_source_relative_suitability_score(x, SRC_BG)[0] for x in xs]
    for a, b in zip(scores, scores[1:]):
        assert b >= a, f"단조 증가 위반: {scores}"
        assert (b - a) < 60.0, f"경계 근처 급변(cliff): {scores}"
    assert scores[0] == 0.0


def test_fallback_far_outside_saturates_at_100():
    """허용밴드에서 충분히 멀면 100에 도달."""
    tol = SRC_BG * FALLBACK_TOLERANCE_FRAC
    span = 2 * tol
    far = (SRC_BG - tol) - span  # 밴드 폭만큼 더 밖 → margin(30%) 초과
    score, _ = _source_relative_suitability_score(far, SRC_BG)
    assert score == 100.0


def test_fallback_symmetric():
    """원본 위/아래 같은 거리면 같은 리스크."""
    tol = SRC_BG * FALLBACK_TOLERANCE_FRAC
    d = 0.3
    below, _ = _source_relative_suitability_score(SRC_BG - tol - d, SRC_BG)
    above, _ = _source_relative_suitability_score(SRC_BG + tol + d, SRC_BG)
    assert below == pytest.approx(above, abs=0.01)


def test_fallback_missing_bg_is_zero():
    """band_gap 정보가 없으면 평가 불가 → 리스크 0."""
    assert _source_relative_suitability_score(None, SRC_BG)[0] == 0.0
    assert _source_relative_suitability_score(2.0, None)[0] == 0.0


# ─────────────────── 4. 폴백 경로 랭킹: 연속 판정(계단식 아님) ───────────────────


def test_fallback_ranking_graded_not_binary():
    """profile 없이 rank_alternatives 를 돌리면, 후보들의 suitability_risk 가
    원본 band_gap 근접도에 따라 연속적으로 매겨진다(적합/부적합 이진 아님).

    원본 SiC(3.26eV) 대비:
      - 근접 후보 GaN(3.40) → 허용밴드 안 → 적합, 낮은 suitability_risk
      - 원거리 후보 GaAs(1.42) → 밴드 밖 크게 → 적합도 낮음, 높은 risk
      - 중간 후보 → 중간 risk
    """
    from matcause.plugins.semiconductor.alternatives_ranker import rank_alternatives

    src_sic = {
        "material_id": "mp-7140", "formula_pretty": "SiC",
        "energy_above_hull": 0.0, "formation_energy_per_atom": -0.32,
        "is_stable": True, "band_gap": 3.26,
    }
    gan = {
        "material_id": "mp-804", "formula_pretty": "GaN",
        "energy_above_hull": 0.0, "formation_energy_per_atom": -0.59,
        "is_stable": True, "band_gap": 3.40,
    }
    gaas = {
        "material_id": "mp-2534", "formula_pretty": "GaAs",
        "energy_above_hull": 0.0, "formation_energy_per_atom": -0.45,
        "is_stable": True, "band_gap": 1.42,
    }
    res = rank_alternatives(src_sic, [gan, gaas], k=5, profile=None)
    by = {c.name: c for c in res.candidates}

    gan_risk = by["GaN"].metrics["suitability_risk"]
    gaas_risk = by["GaAs"].metrics["suitability_risk"]

    # 근접 후보가 원거리 후보보다 적합성 리스크가 낮다(연속적 서열).
    assert gan_risk < gaas_risk
    # GaN 은 허용밴드 근처(적합), GaAs 는 크게 벗어남(적합도 낮음).
    assert by["GaN"].metrics["suitability"] == "적합"
    assert by["GaAs"].metrics["suitability"] == "적합도 낮음"
    # 적합 후보가 앞 순위.
    names = [c.name for c in res.candidates]
    assert names.index("GaN") < names.index("GaAs")
