"""리스크 산정 — 소재 물성 → 0~100 리스크 스코어 (T-112, US-B2).

'리스크'의 의미: 이 소재가 불량의 원인일 가능성. 값이 높을수록 소재 요인 의심 ↑.

데이터 정직성 (design.md 6.2): MP 본 DB는 결함 형성 에너지 직접값을 제공하지 않으므로,
energy_above_hull(안정성 프록시)을 결함/불안정성의 대리 지표로 사용한다. 각 지표의
판정에는 사용된 수치와 판정 기준(threshold)을 근거(Evidence)로 첨부한다.

산정 방식:
- 지표별로 0~100 하위 점수 계산(투명한 임계값 기반, piecewise-linear).
- 가중합으로 종합 점수 산출. breakdown(지표별 기여) 함께 반환.
- 확보 못한 지표는 점수에서 제외하고 '없음'으로 표기(가중치 재정규화).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from matcause.core.models import Evidence, EvidenceSource

from .application_profile import ApplicationProfile


def _is_elemental(material: dict[str, Any]) -> bool:
    """순수 원소(단일 원소) 여부. 원소는 정의상 formation_energy=0 이므로
    formation_energy 를 리스크 지표로 쓰면 안 된다."""
    formula = material.get("formula_pretty")
    if isinstance(formula, str) and formula.strip():
        elems = set(re.findall(r"[A-Z][a-z]?", formula))
        if len(elems) == 1:
            return True
    return False

# 지표별 가중치 (합이 1이 되도록 사용 가능한 지표만으로 재정규화)
# application_suitability 는 응용 프로파일이 주어질 때만 활성화된다.
WEIGHTS = {
    "energy_above_hull": 0.5,   # 안정성 프록시(결함 대리) — 주 신호
    "formation_energy_per_atom": 0.3,
    "is_stable": 0.2,
}
# 응용 적합성 가중치(프로파일이 있을 때만). band_gap_critical 이면 더 높게.
APP_WEIGHT = 0.4
APP_WEIGHT_CRITICAL = 0.8

# 판정 임계값 (문헌/관례 기반의 보수적 기준. 리포트에 근거로 표기)
# energy_above_hull [eV/atom]: 0 = 안정(hull 위). 커질수록 준안정/불안정.
EHULL_LOW = 0.0     # 0 이하 → 리스크 0
EHULL_HIGH = 0.1    # 0.1 eV/atom 이상 → 리스크 100 (통상 준안정 경계)

# formation_energy_per_atom [eV/atom]: 음수면 형성에 유리(안정).
# 안정한 반도체 화합물은 보통 -0.1 eV/atom 보다 더 음수이므로, 그 이하는 리스크 0.
# 0 근처/양수(형성 비유리)일 때만 리스크로 본다.
FE_STABLE = -0.1    # -0.1 이하 → 리스크 0
FE_UNSTABLE = 0.0   # 0 이상(형성 비유리) → 리스크 100


@dataclass
class RiskResult:
    score: float                       # 0~100 종합
    breakdown: dict[str, float]        # 지표별 하위 점수(0~100)
    evidences: list[Evidence]          # 각 판정 근거(값+임계값)
    notes: list[str] = field(default_factory=list)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _lerp_score(value: float, low: float, high: float) -> float:
    """value 가 low→high 로 갈수록 0→100 으로 선형 증가."""
    if high == low:
        return 0.0
    return _clamp((value - low) / (high - low) * 100.0)


def _ev(source_ref: str, value: Any, unit: str | None, note: str) -> Evidence:
    return Evidence(
        source_type=EvidenceSource.MP,
        source_ref=source_ref,
        value=value,
        unit=unit,
        note=note,
    )


def _application_suitability_score(
    bg: float | None, profile: ApplicationProfile
) -> tuple[float, str]:
    """band_gap 이 응용 요구 범위를 벗어난 정도를 0~100 리스크로 환산.

    범위 안이면 0. 벗어나면 대표 목표값 대비 상대 편차에 비례(50% 편차 ≈ 100).
    """
    if bg is None:
        return 0.0, "band_gap 없음 → 응용 적합성 평가 불가"
    if profile.band_gap_in_range(bg):
        return 0.0, f"band_gap {bg:.2f} eV, 응용({profile.name}) 요구 범위 내 → 적합"
    target = profile.band_gap_target()
    if target and target > 0:
        rel_dev = abs(bg - target) / target
        score = _clamp(rel_dev / 0.5 * 100.0)  # 목표 대비 50% 편차면 100
    else:
        score = 100.0
        rel_dev = 1.0
    return score, (
        f"band_gap {bg:.2f} eV, 응용({profile.name}) 요구 "
        f"[{profile.band_gap_min}~{profile.band_gap_max}] 벗어남 "
        f"(목표 대비 편차 {rel_dev*100:.0f}%) → 응용 적합성 리스크"
    )


def score_material(
    material: dict[str, Any], profile: ApplicationProfile | None = None
) -> RiskResult:
    """단일 소재(MP summary dict)에 대한 리스크 산정.

    material 예: mp_connector.query_summary(...)["best"] 또는 materials[i]
    profile: 응용 프로파일(주어지면 band_gap 기반 응용 적합성 리스크를 추가).
    """
    mpid = str(material.get("material_id", "unknown"))
    sub: dict[str, float] = {}
    evidences: list[Evidence] = []
    notes: list[str] = []
    dyn_weights: dict[str, float] = dict(WEIGHTS)

    # 1) energy_above_hull (안정성 프록시 = 결함/불안정성 대리)
    ehull = material.get("energy_above_hull")
    if ehull is not None:
        s = _lerp_score(float(ehull), EHULL_LOW, EHULL_HIGH)
        sub["energy_above_hull"] = round(s, 1)
        evidences.append(
            _ev(
                mpid,
                ehull,
                "eV/atom",
                f"energy_above_hull={ehull} (기준 {EHULL_LOW}~{EHULL_HIGH}). "
                "결함 형성 에너지 직접값 부재로 안정성 프록시 사용.",
            )
        )
    else:
        notes.append("energy_above_hull 없음 → 점수 제외")
        evidences.append(Evidence.missing(EvidenceSource.MP, mpid, "energy_above_hull 미확보"))

    # 2) formation_energy_per_atom
    #    순수 원소는 정의상 formation_energy=0 이므로 리스크 지표에서 제외한다
    #    (0 을 '형성 비유리'로 오판하면 안 됨. 예: Si mp-149).
    fe = material.get("formation_energy_per_atom")
    if _is_elemental(material):
        notes.append("순수 원소 → formation_energy(정의상 0)는 리스크 지표에서 제외")
        evidences.append(
            _ev(
                mpid,
                fe,
                "eV/atom",
                f"formation_energy_per_atom={fe}: 순수 원소는 정의상 0이므로 "
                "리스크 산정에서 제외(안정성은 energy_above_hull/is_stable 로 판단).",
            )
        )
    elif fe is not None:
        s = _lerp_score(float(fe), FE_STABLE, FE_UNSTABLE)
        sub["formation_energy_per_atom"] = round(s, 1)
        evidences.append(
            _ev(
                mpid,
                fe,
                "eV/atom",
                f"formation_energy_per_atom={fe} (기준 {FE_STABLE}~{FE_UNSTABLE}). "
                "음수일수록 형성에 유리(리스크 낮음).",
            )
        )
    else:
        notes.append("formation_energy_per_atom 없음 → 점수 제외")
        evidences.append(
            Evidence.missing(EvidenceSource.MP, mpid, "formation_energy_per_atom 미확보")
        )

    # 3) is_stable 플래그
    is_stable = material.get("is_stable")
    if is_stable is not None:
        s = 0.0 if is_stable else 100.0
        sub["is_stable"] = s
        evidences.append(
            _ev(mpid, is_stable, None, f"is_stable={is_stable} (불안정 시 리스크 가산).")
        )
    else:
        notes.append("is_stable 없음 → 점수 제외")
        evidences.append(Evidence.missing(EvidenceSource.MP, mpid, "is_stable 미확보"))

    # 4) application_suitability (응용 프로파일이 주어질 때만)
    if profile is not None:
        bg = material.get("band_gap")
        app_score, app_note = _application_suitability_score(bg, profile)
        if bg is not None:
            sub["application_suitability"] = round(app_score, 1)
            dyn_weights["application_suitability"] = (
                APP_WEIGHT_CRITICAL if profile.band_gap_critical else APP_WEIGHT
            )
            evidences.append(_ev(mpid, bg, "eV", app_note))
        else:
            notes.append("band_gap 없음 → 응용 적합성 평가 제외")
            evidences.append(
                Evidence.missing(EvidenceSource.MP, mpid, "band_gap 미확보(응용 적합성)")
            )

    # 가중합 (사용 가능한 지표만으로 가중치 재정규화)
    used = {k: dyn_weights[k] for k in sub if k in dyn_weights}
    total_w = sum(used.values())
    if total_w > 0:
        score = sum(sub[k] * (used[k] / total_w) for k in used)
    else:
        score = 0.0
        notes.append("산정 가능한 지표 없음 → 리스크 0 (데이터 부족)")

    return RiskResult(
        score=round(_clamp(score), 1),
        breakdown=sub,
        evidences=evidences,
        notes=notes,
    )
