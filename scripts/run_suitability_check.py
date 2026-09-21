"""응용 적합성 스코어링 검증 — SiC / GaN / GaAs (power 프로파일).

수정된 _application_suitability_score (range-width-relative + smooth margin)와
조정된 power 프로파일 범위(2.0~6.5)가 물리적으로 상식적인 판정을 내는지 확인.

기대:
  SiC  (bg≈3.26): power WBG 적합 → 응용 리스크 0, 종합 리스크 낮음
  GaN  (bg≈3.4):  power WBG 적합 → 응용 리스크 0, 종합 리스크 낮음
  GaAs (bg≈1.42): 협밴드갭, power 부적합 → 응용 리스크 높음, 종합 높음
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

from matcause.plugins.semiconductor.application_profile import PROFILES
from matcause.plugins.semiconductor.risk_scorer import score_material, _application_suitability_score

power = PROFILES["power"]

# 실제 MP 데이터 기반 mock (캐시/라이브 값과 동일한 구조)
SCENARIOS = {
    "SiC": {
        "material_id": "mp-7140",
        "formula_pretty": "SiC",
        "energy_above_hull": 0.0,
        "formation_energy_per_atom": -0.321,
        "is_stable": True,
        "band_gap": 3.26,  # 4H-SiC 실측 ~3.26 eV (MP 계산값 유사)
    },
    "GaN": {
        "material_id": "mp-804",
        "formula_pretty": "GaN",
        "energy_above_hull": 0.0,
        "formation_energy_per_atom": -0.587,
        "is_stable": True,
        "band_gap": 3.40,  # 실측 ~3.4 eV
    },
    "GaAs": {
        "material_id": "mp-2534",
        "formula_pretty": "GaAs",
        "energy_above_hull": 0.0,
        "formation_energy_per_atom": -0.377,
        "is_stable": True,
        "band_gap": 1.42,  # 실측 ~1.42 eV
    },
}

# 경계 근처 케이스도 추가 (이전 버그 재현 방지)
EDGE_CASES = {
    "Edge_1.9eV": {"material_id": "edge1", "formula_pretty": "X",
                   "energy_above_hull": 0.0, "formation_energy_per_atom": -0.3,
                   "is_stable": True, "band_gap": 1.9},
    "Edge_2.0eV": {"material_id": "edge2", "formula_pretty": "X",
                   "energy_above_hull": 0.0, "formation_energy_per_atom": -0.3,
                   "is_stable": True, "band_gap": 2.0},
    "Edge_6.5eV": {"material_id": "edge3", "formula_pretty": "X",
                   "energy_above_hull": 0.0, "formation_energy_per_atom": -0.3,
                   "is_stable": True, "band_gap": 6.5},
    "Edge_6.6eV": {"material_id": "edge4", "formula_pretty": "X",
                   "energy_above_hull": 0.0, "formation_energy_per_atom": -0.3,
                   "is_stable": True, "band_gap": 6.6},
}


def main() -> int:
    print("=" * 72)
    print(f"power 프로파일: band_gap [{power.band_gap_min} ~ {power.band_gap_max}] eV")
    print(f"  critical={power.band_gap_critical}, margin=30% of range width")
    print("=" * 72)

    # ── 주요 시나리오 ──
    print("\n▶ 주요 시나리오 (SiC / GaN / GaAs)")
    print(f"{'소재':<8} {'bg(eV)':>8} {'범위내':>6} {'응용리스크':>10} {'종합리스크':>10}  설명")
    print("-" * 72)
    for name, mat in SCENARIOS.items():
        bg = mat["band_gap"]
        in_range = power.band_gap_in_range(bg)
        app_score, app_note = _application_suitability_score(bg, power)
        risk = score_material(mat, profile=power)
        print(f"{name:<8} {bg:>8.2f} {'✅':>6} {app_score:>10.1f} {risk.score:>10.1f}  {app_note}" if in_range
              else f"{name:<8} {bg:>8.2f} {'❌':>6} {app_score:>10.1f} {risk.score:>10.1f}  {app_note}")
        print(f"         breakdown: {risk.breakdown}")

    # ── 경계 케이스 ──
    print(f"\n▶ 경계 케이스 (이전 버그: 경계 근처에서 과도한 리스크)")
    print(f"{'케이스':<14} {'bg(eV)':>8} {'범위내':>6} {'응용리스크':>10} {'종합리스크':>10}")
    print("-" * 72)
    for name, mat in EDGE_CASES.items():
        bg = mat["band_gap"]
        in_range = power.band_gap_in_range(bg)
        app_score, _ = _application_suitability_score(bg, power)
        risk = score_material(mat, profile=power)
        marker = "✅" if in_range else "❌"
        print(f"{name:<14} {bg:>8.2f} {marker:>6} {app_score:>10.1f} {risk.score:>10.1f}")

    # ── 이전 버그 재현 방지 확인 ──
    print("\n▶ 이전 버그 검증")
    # bg=2.2: 이전 로직에서 midpoint(4.25) 대비 ~48% 편차 → 96점이었음
    bg_test = 2.2  # 하한 2.0에서 겨우 0.2 아래
    # 이전 하한 2.3 기준이면 밖이지만, 현재 2.0 기준이면 밖이 아님 (2.2 > 2.0)
    # → 하한을 2.0으로 낮췄으므로 2.2는 범위 안
    # 대신 bg=1.8 (power에 확실히 부적합)을 테스트
    for test_bg in [2.2, 1.9, 1.5, 1.0, 0.5]:
        in_r = power.band_gap_in_range(test_bg)
        sc, note = _application_suitability_score(test_bg, power)
        print(f"  bg={test_bg:.1f} eV → {'범위내' if in_r else '범위밖'}, 응용리스크={sc:.1f}  {note}")

    # ── 물리 상식 검증 ──
    print("\n▶ 상식 검증")
    sic = score_material(SCENARIOS["SiC"], profile=power)
    gan = score_material(SCENARIOS["GaN"], profile=power)
    gaas = score_material(SCENARIOS["GaAs"], profile=power)
    ok = True
    checks = [
        ("SiC 종합 < 20", sic.score < 20),
        ("GaN 종합 < 20", gan.score < 20),
        ("GaAs 종합 > SiC", gaas.score > sic.score),
        ("GaAs 종합 > GaN", gaas.score > gan.score),
        ("GaAs 응용리스크 > 0", gaas.breakdown.get("application_suitability", 0) > 0),
        ("SiC 응용리스크 == 0", sic.breakdown.get("application_suitability", 0) == 0),
        ("GaN 응용리스크 == 0", gan.breakdown.get("application_suitability", 0) == 0),
    ]
    for desc, result in checks:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {desc}")
        if not result:
            ok = False

    print(f"\n{'=' * 72}")
    print(f"종합 판정: {'ALL PASS ✅' if ok else 'SOME FAILED ❌'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
