"""대체 소재 후보 랭킹 (T-113, US-B3).

리스크 산정(T-112) 결과를 기준으로 대체 후보를 순위화한다. 각 후보는:
- 정량 지표(risk, energy_above_hull, band_gap 등)
- source 대비 개선폭(improvement: 리스크 감소량)
- 트레이드오프(예: band_gap 차이 → 소자 특성 변화)
를 포함한다. 정렬 기준/가중치는 리포트에 표기한다(US-B3.3).

후보 소스:
1. 같은 물질군(material_group)의 도메인 후보 shortlist (실제 MP 로 조회됨).
2. + connector.find_alternatives (chemsys 계열).
합쳐서 중복 제거 후 리스크 오름차순 랭킹.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from matcause.core.models import Evidence, EvidenceSource, RankedCandidate

from .application_profile import ApplicationProfile
from .risk_scorer import score_material

# 밴드갭 편차 한계(응용 적합성 필터). source 대비 이 비율 이상 벗어나면 부적합 취급.
DEFAULT_BG_DEVIATION_LIMIT = 0.5  # 50%

# 물질군별 대체 후보 shortlist (도메인 지식; 실제 MP 로 조회해 검증됨).
# 여기 값은 '후보 화학식'일 뿐, 물성 수치는 전부 MP 라이브/캐시에서 온다(합성 금지).
GROUP_ALTERNATIVES: dict[str, list[str]] = {
    "III-V": ["GaN", "AlN", "InN", "GaAs", "InP", "AlAs", "GaP"],
    "oxide": ["Al2O3", "HfO2", "ZrO2", "SiO2", "TiO2", "Ta2O5"],
    "nitride": ["Si3N4", "AlN", "GaN", "BN"],
    "carbide": ["SiC", "TiC", "WC", "B4C"],
    "elemental": ["Si", "Ge", "C"],
}

# 랭킹 정렬 기준 설명 (리포트 표기용)
RANK_BASIS = (
    "리스크 스코어(안정성 프록시 + 응용 적합성) 오름차순. "
    "원본 대비 band_gap 편차가 큰 후보는 응용 적합도 낮음으로 표기/후순위."
)


def _bg_deviation(source_bg: float | None, cand_bg: float | None) -> float | None:
    """source 대비 후보 band_gap 의 상대 편차(0~). None 이면 계산 불가."""
    if source_bg is None or cand_bg is None or source_bg == 0:
        return None
    return abs(cand_bg - source_bg) / abs(source_bg)


@dataclass
class AlternativesResult:
    candidates: list[RankedCandidate]
    basis: str = RANK_BASIS
    notes: list[str] = field(default_factory=list)


def _band_gap_tradeoff(source_bg: float | None, cand_bg: float | None) -> str | None:
    if source_bg is None or cand_bg is None:
        return None
    diff = cand_bg - source_bg
    if abs(diff) < 0.1:
        return "band_gap 유사(소자 특성 유지 유리)"
    direction = "증가" if diff > 0 else "감소"
    return f"band_gap {source_bg:.2f}→{cand_bg:.2f} eV ({direction} {abs(diff):.2f}), 소자 동작점 재검토 필요"


def rank_alternatives(
    source_material: dict[str, Any],
    candidate_materials: list[dict[str, Any]],
    k: int = 5,
    profile: ApplicationProfile | None = None,
    bg_deviation_limit: float = DEFAULT_BG_DEVIATION_LIMIT,
    exclude_unfit: bool = False,
) -> AlternativesResult:
    """후보 소재들을 리스크 기준으로 랭킹한다.

    source_material: 현재 소재의 best 상(dict). 개선폭 계산 기준.
    candidate_materials: 후보 best 상 dict 목록(각각 실제 MP 조회 결과).
    profile: 응용 프로파일. 주어지면 응용 적합성을 리스크에 반영.
    bg_deviation_limit: source 대비 band_gap 편차 한계(기본 0.5=50%).
    exclude_unfit: True 면 한계 초과 후보를 랭킹에서 제외, False 면 '적합도 낮음'으로 표기.
    """
    src_risk = score_material(source_material, profile=profile).score
    src_id = str(source_material.get("material_id", ""))
    src_formula = str(source_material.get("formula_pretty", "")).strip()
    src_bg = source_material.get("band_gap")

    ranked: list[RankedCandidate] = []
    notes: list[str] = []
    excluded: list[str] = []
    seen_ids: set[str] = set()
    seen_formulas: set[str] = set()

    for cand in candidate_materials:
        cid = str(cand.get("material_id", ""))
        cformula = str(cand.get("formula_pretty") or cid).strip()
        # 중복 제거: material_id 또는 화학식 기준. source 자기 자신(id/화학식) 제외.
        if cid and (cid == src_id or cid in seen_ids):
            continue
        if cformula and (cformula == src_formula or cformula in seen_formulas):
            continue
        if cid:
            seen_ids.add(cid)
        if cformula:
            seen_formulas.add(cformula)

        risk = score_material(cand, profile=profile)
        improvement = round(src_risk - risk.score, 1)
        cand_bg = cand.get("band_gap")

        # 응용 적합성 판정:
        # - 프로파일이 있으면 '응용 요구 band_gap 범위 이탈'을 우선 기준으로 삼는다.
        #   (예: 파워 응용에서 AlN 은 범위 내 → 적합. source 대비 편차는 부차적.)
        # - 프로파일이 없으면 source 대비 band_gap 편차로 판정한다.
        dev = _bg_deviation(src_bg, cand_bg)
        unfit_reason: str | None = None
        if profile is not None:
            if cand_bg is not None and not profile.band_gap_in_range(cand_bg):
                unfit_reason = (
                    f"응용({profile.name}) 요구 band_gap "
                    f"[{profile.band_gap_min}~{profile.band_gap_max}] 이탈 (후보 {cand_bg:.2f} eV)"
                )
        else:
            if dev is not None and dev > bg_deviation_limit:
                unfit_reason = (
                    f"원본 대비 band_gap 편차 {dev*100:.0f}% (한계 {bg_deviation_limit*100:.0f}%)"
                )
        unfit = unfit_reason is not None

        if unfit and exclude_unfit:
            excluded.append(cformula)
            continue

        evidences = [
            Evidence(
                source_type=EvidenceSource.MP, source_ref=cid,
                value=cand.get("energy_above_hull"), unit="eV/atom",
                note=f"{cformula} energy_above_hull",
            ),
        ]
        if cand_bg is not None:
            evidences.append(
                Evidence(
                    source_type=EvidenceSource.MP, source_ref=cid,
                    value=cand_bg, unit="eV", note=f"{cformula} band_gap",
                )
            )

        suitability = "적합도 낮음" if unfit else "적합"
        tradeoff = _band_gap_tradeoff(src_bg, cand_bg)
        if unfit:
            warn = f"[응용 적합도 낮음] {unfit_reason}"
            tradeoff = f"{warn}. {tradeoff}" if tradeoff else warn

        ranked.append(
            RankedCandidate(
                name=cformula,
                score=risk.score,
                metrics={
                    "risk": risk.score,
                    "energy_above_hull": cand.get("energy_above_hull"),
                    "formation_energy_per_atom": cand.get("formation_energy_per_atom"),
                    "band_gap": cand_bg,
                    "is_stable": cand.get("is_stable"),
                    "material_id": cid,
                    "suitability": suitability,
                    "band_gap_deviation": round(dev, 3) if dev is not None else None,
                },
                improvement=(
                    f"리스크 {src_risk}→{risk.score} (개선 {improvement})"
                    if improvement > 0
                    else f"리스크 개선 없음(현재 {src_risk}, 후보 {risk.score})"
                ),
                tradeoffs=tradeoff,
                evidences=evidences,
            )
        )

    # 정렬: 적합한 후보 우선 → 리스크 오름차순 → band_gap 근접도
    def _sort_key(rc: RankedCandidate):
        unfit_flag = 1 if rc.metrics.get("suitability") == "적합도 낮음" else 0
        bg = rc.metrics.get("band_gap")
        bg_dist = abs(bg - src_bg) if (bg is not None and src_bg is not None) else 1e9
        return (unfit_flag, rc.score, bg_dist)

    ranked.sort(key=_sort_key)

    if not ranked and not excluded:
        notes.append("대체 후보를 찾지 못함")
    if excluded:
        notes.append(f"응용 적합성 미달로 제외된 후보: {', '.join(excluded)}")
    unfit_kept = [c.name for c in ranked if c.metrics.get("suitability") == "적합도 낮음"]
    if unfit_kept:
        notes.append(f"응용 적합도 낮음(참고): {', '.join(unfit_kept)}")

    return AlternativesResult(candidates=ranked[:k], notes=notes)


def candidate_formulas_for_group(material_group: str | None, exclude: str | None = None) -> list[str]:
    """물질군에 맞는 대체 후보 화학식 목록(도메인 shortlist)."""
    if not material_group:
        return []
    cands = list(GROUP_ALTERNATIVES.get(material_group, []))
    if exclude:
        cands = [c for c in cands if c != exclude]
    return cands
