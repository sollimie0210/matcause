"""T-111: 물성 추출 테스트 (정규식 + MockLLM 보강)."""

from __future__ import annotations

from matcause.core.llm.mock_client import MockLLMClient
from matcause.plugins.semiconductor.material_extractor import (
    extract_by_regex,
    extract_materials,
)


def test_regex_extracts_clear_formula():
    r = extract_by_regex("GaN 에피층에서 누설전류가 상승했습니다.")
    assert "GaN" in r.formulas
    assert r.material_group == "III-V"
    assert r.method == "regex"
    assert r.confidence >= 0.8


def test_regex_extracts_oxide_and_nitride():
    assert extract_by_regex("Al2O3 기판").material_group == "oxide"
    assert "Al2O3" in extract_by_regex("Al2O3 기판").formulas
    r = extract_by_regex("Si3N4 박막의 결함")
    assert "Si3N4" in r.formulas
    assert r.material_group == "nitride"


def test_regex_multiple_formulas():
    r = extract_by_regex("GaN on Al2O3 (sapphire) substrate, HfO2 gate")
    for f in ("GaN", "Al2O3", "HfO2"):
        assert f in r.formulas


def test_material_name_lexicon_english():
    r = extract_by_regex("The sapphire substrate showed cracks")
    assert "Al2O3" in r.formulas
    assert "sapphire" in r.material_names


def test_material_name_lexicon_korean():
    r = extract_by_regex("탄화규소 웨이퍼에서 불량 발생")
    assert "SiC" in r.formulas
    assert r.material_group == "carbide"


def test_elemental_semiconductor():
    r = extract_by_regex("실리콘 웨이퍼 표면 결함")
    assert "Si" in r.formulas
    assert r.material_group == "elemental"


def test_no_material_returns_empty():
    r = extract_by_regex("공정 챔버 온도가 이상합니다")
    assert not r.has_result()
    assert r.method == "none"


def test_extract_materials_prefers_regex_over_llm():
    # 정규식이 잡으면 LLM 을 호출하지 않고 regex 결과 사용
    llm = MockLLMClient()
    r = extract_materials("GaN 소자", llm=llm)
    assert r.method == "regex"
    assert "GaN" in r.formulas


def test_extract_materials_llm_fallback():
    # 정규식이 못 잡는 서술형 → LLM(Mock) 보강. 스크립트로 응답 고정.
    llm = MockLLMClient(
        scripted_responses={
            "특수소재": {"formulas": ["InP"], "material_group": "III-V", "confidence": 0.7}
        }
    )
    r = extract_materials("특수소재 관련 물성 이슈", llm=llm)
    assert "InP" in r.formulas
    assert r.method == "regex+llm"
    assert r.material_group == "III-V"


def test_extract_materials_empty_input():
    r = extract_materials("   ", llm=MockLLMClient())
    assert not r.has_result()


def test_primary_formula_helper():
    r = extract_by_regex("GaN and SiC devices")
    assert r.primary_formula() == r.formulas[0]
