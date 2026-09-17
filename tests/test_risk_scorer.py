"""T-112: 리스크 산정 테스트."""

from __future__ import annotations

from matcause.plugins.semiconductor.risk_scorer import score_material


def test_stable_material_low_risk():
    # 실제 SiC 안정상(mp-1204356) 값 사용: 안정 → 리스크 낮음
    mat = {
        "material_id": "mp-1204356",
        "energy_above_hull": 0.0,
        "formation_energy_per_atom": -0.306,
        "is_stable": True,
    }
    r = score_material(mat)
    assert r.score < 10.0
    assert r.breakdown["energy_above_hull"] == 0.0
    assert r.breakdown["is_stable"] == 0.0


def test_unstable_material_high_risk():
    mat = {
        "material_id": "mp-xxxx",
        "energy_above_hull": 0.15,       # > 0.1 → 100
        "formation_energy_per_atom": 0.1,  # > 0 → 100
        "is_stable": False,
    }
    r = score_material(mat)
    assert r.score > 90.0
    assert r.breakdown["energy_above_hull"] == 100.0
    assert r.breakdown["is_stable"] == 100.0


def test_intermediate_ehull_scales_linearly():
    mat = {"material_id": "m", "energy_above_hull": 0.05}  # 중간값 → ~50
    r = score_material(mat)
    assert 45.0 <= r.breakdown["energy_above_hull"] <= 55.0


def test_evidence_carries_value_and_threshold():
    mat = {"material_id": "mp-1", "energy_above_hull": 0.05}
    r = score_material(mat)
    ev = [e for e in r.evidences if e.source_ref == "mp-1" and e.value == 0.05]
    assert ev
    assert "기준" in ev[0].note  # 판정 기준(threshold) 명시
    assert ev[0].unit == "eV/atom"


def test_missing_metrics_are_reweighted_and_noted():
    # energy_above_hull 만 있는 경우: 그 지표만으로 점수 산정
    mat = {"material_id": "m", "energy_above_hull": 0.1}
    r = score_material(mat)
    assert r.score == 100.0  # 유일 지표가 100 → 재정규화로 종합 100
    assert any("없음" in n for n in r.notes)
    # 미확보 지표는 missing evidence 로 기록
    assert any(e.value is None for e in r.evidences)


def test_no_metrics_yields_zero_with_note():
    r = score_material({"material_id": "m"})
    assert r.score == 0.0
    assert any("데이터 부족" in n for n in r.notes)


def test_pure_element_not_penalized_for_zero_formation_energy():
    # 실제 Si(mp-149): 순수 원소라 formation_energy=0 이지만 안정 → 리스크 0 이어야 함.
    # (다형 화합물 SiC 하나로는 못 잡히는 케이스. 실데이터 검증에서 발견.)
    si = {
        "material_id": "mp-149",
        "formula_pretty": "Si",
        "formation_energy_per_atom": 0.0,
        "energy_above_hull": 0.0,
        "is_stable": True,
    }
    r = score_material(si)
    assert r.score < 5.0
    # formation_energy 는 breakdown 에서 제외되어야 함
    assert "formation_energy_per_atom" not in r.breakdown
    assert any("순수 원소" in n for n in r.notes)


def test_real_al2o3_stable_low_risk():
    # 실제 Al2O3(mp-1143): E_f=-3.43, E_hull=0, stable → 리스크 0
    al2o3 = {
        "material_id": "mp-1143",
        "formula_pretty": "Al2O3",
        "formation_energy_per_atom": -3.4266,
        "energy_above_hull": 0.0,
        "is_stable": True,
    }
    assert score_material(al2o3).score == 0.0


def test_defect_energy_proxy_note_present():
    r = score_material({"material_id": "m", "energy_above_hull": 0.02})
    ehull_ev = [e for e in r.evidences if e.value == 0.02]
    assert ehull_ev
    assert "프록시" in ehull_ev[0].note
