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


# 범위 폭의 이 비율만큼 벗어나면 리스크 100. 두 경로(감지/폴백)가 공유하는 단일 원칙.
MARGIN_FRAC = 0.3


def _range_relative_risk(
    bg: float, lo: float | None, hi: float | None
) -> tuple[float, float, float, float | None]:
    """범위 [lo, hi] 기준 band_gap 편차를 0~100 리스크로 환산하는 **공통 커널**.

    감지 경로(응용 프로파일 범위)와 폴백 경로(원본 소재 주변 허용밴드)가 **동일한**
    수학 원칙을 쓰도록 하는 단일 함수다:
      - 범위 안이면 0.
      - 범위 밖이면 **가장 가까운 경계로부터의 거리**를 **범위 폭** 대비로 재고,
        경계에서 0 → 완만한 선형 증가(범위 폭의 MARGIN_FRAC 밖에서 100).
      - 경계에서 계단식(0→100)으로 튀지 않는다. midpoint 대비 방식(옛 버그) 미사용.

    반환: (score, distance, span, boundary)  — boundary 는 범위 안이면 None.
    """
    # 범위 폭(스케일). 양측이면 hi-lo, 한쪽만이면 그 값 자체를 스케일로.
    if lo is not None and hi is not None:
        span = hi - lo
    elif lo is not None:
        span = lo
    elif hi is not None:
        span = hi
    else:
        span = 1.0
    if span <= 0:
        span = 1.0

    # 범위 안이면 적합(리스크 0)
    in_range = True
    if lo is not None and bg < lo:
        in_range = False
    if hi is not None and bg > hi:
        in_range = False
    if in_range:
        return 0.0, 0.0, span, None

    # 가장 가까운 경계로부터의 거리
    if lo is not None and bg < lo:
        distance = lo - bg
        boundary = lo
    elif hi is not None and bg > hi:
        distance = bg - hi
        boundary = hi
    else:
        distance = 0.0
        boundary = bg

    margin = span * MARGIN_FRAC
    if margin <= 0:
        margin = 1.0

    score = _clamp(distance / margin * 100.0)
    return score, distance, span, boundary


def _application_suitability_score(
    bg: float | None, profile: ApplicationProfile
) -> tuple[float, str]:
    """band_gap 이 응용 요구 범위를 벗어난 정도를 0~100 리스크로 환산 (감지 경로).

    실제 계산은 공통 커널 `_range_relative_risk` 에 위임한다. 폴백 경로도 같은 커널을
    쓰므로 두 경로가 동일한 원칙(경계 대비 + 완만한 증가)을 공유한다.
    """
    if bg is None:
        return 0.0, "band_gap 없음 → 응용 적합성 평가 불가"

    lo = profile.band_gap_min
    hi = profile.band_gap_max

    score, distance, span, boundary = _range_relative_risk(bg, lo, hi)
    if boundary is None:
        return 0.0, f"band_gap {bg:.2f} eV, 응용({profile.name}) 요구 범위 내 → 적합"

    pct = distance / span * 100.0
    return score, (
        f"band_gap {bg:.2f} eV, 응용({profile.name}) 요구 band_gap "
        f"[{lo}~{hi}] 경계({boundary})에서 {distance:.2f} eV 벗어남 "
        f"(범위 폭 {span:.1f} 대비 {pct:.1f}%) → 적합성 리스크 {score:.0f}/100"
    )


# 폴백(응용 미감지) 시 원본 band_gap 주변에 두는 허용밴드의 반폭 비율.
# 원본의 ±(이 비율)을 '요구 범위'로 간주해 공통 커널로 완만하게 판정한다.
FALLBACK_TOLERANCE_FRAC = 0.25  # 원본 대비 ±25% 를 적합 범위로


def _source_relative_suitability_score(
    cand_bg: float | None, source_bg: float | None
) -> tuple[float, str]:
    """[폴백 경로] 응용 프로파일이 없을 때, 원본 소재 대비 후보 band_gap 적합성.

    감지 경로와 **같은 원칙**을 쓴다: 원본 band_gap 주변에 ±FALLBACK_TOLERANCE_FRAC
    허용밴드를 두고, 그 범위를 공통 커널 `_range_relative_risk` 에 넘긴다. 따라서
    - 허용밴드 안이면 0,
    - 밖이면 경계에서 완만하게 증가(계단식 아님),
    - 편차는 '밴드 폭 대비' 상대값(옛 원본 대비 50% 하드컷 방식 폐기).
    극단적으로 응용이 모호한 케이스에서도 0→100 으로 튀지 않는다.
    """
    if cand_bg is None or source_bg is None or source_bg <= 0:
        return 0.0, "band_gap 정보 부족 → 적합성 평가 불가(폴백)"

    tol = abs(source_bg) * FALLBACK_TOLERANCE_FRAC
    lo = source_bg - tol
    hi = source_bg + tol

    score, distance, span, boundary = _range_relative_risk(cand_bg, lo, hi)
    if boundary is None:
        return 0.0, (
            f"band_gap {cand_bg:.2f} eV, 원본 {source_bg:.2f} eV 대비 "
            f"허용밴드[{lo:.2f}~{hi:.2f}] 내 → 적합"
        )
    pct = distance / span * 100.0
    return score, (
        f"band_gap {cand_bg:.2f} eV, 원본 {source_bg:.2f} eV 대비 "
        f"허용밴드[{lo:.2f}~{hi:.2f}] 경계({boundary:.2f})에서 {distance:.2f} eV 벗어남 "
        f"(밴드 폭 {span:.2f} 대비 {pct:.1f}%) → 적합성 리스크 {score:.0f}/100"
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
