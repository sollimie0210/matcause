"""응용(애플리케이션) 프로파일 — 응용 적합성 판정 기준 (T-112/113 확장).

같은 소재라도 응용에 따라 요구 물성이 다르다. 예: 파워 소자는 와이드 밴드갭이
핵심이라 밴드갭이 요구 범위를 벗어나면 소재가 안정해도 부적합할 수 있다.

이 모듈은 응용별 요구 물성(주로 band_gap 목표 범위)을 정의하고, 이슈 텍스트에서
응용을 감지한다. 리스크 산정/대체 랭킹이 이 프로파일을 참조한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ApplicationProfile:
    name: str
    # band_gap 요구 범위 [eV] (None 이면 제약 없음)
    band_gap_min: float | None = None
    band_gap_max: float | None = None
    # 밴드갭이 응용에 얼마나 중요한지 (리스크 가중치에 사용)
    band_gap_critical: bool = False
    note: str = ""

    def band_gap_target(self) -> float | None:
        """대표 목표값(범위 중앙). 편차 계산 기준."""
        if self.band_gap_min is not None and self.band_gap_max is not None:
            return (self.band_gap_min + self.band_gap_max) / 2
        return self.band_gap_min if self.band_gap_min is not None else self.band_gap_max

    def band_gap_in_range(self, bg: float) -> bool:
        if self.band_gap_min is not None and bg < self.band_gap_min:
            return False
        if self.band_gap_max is not None and bg > self.band_gap_max:
            return False
        return True


# 알려진 응용 프로파일 (문헌 관례 기반의 보수적 범위)
PROFILES: dict[str, ApplicationProfile] = {
    "power": ApplicationProfile(
        name="power",
        band_gap_min=2.3,   # 와이드 밴드갭(SiC/GaN 급) 지향
        band_gap_max=6.5,
        band_gap_critical=True,
        note="파워 소자: 고전압/저손실 위해 와이드 밴드갭 요구",
    ),
    "led": ApplicationProfile(
        name="led",
        band_gap_min=1.8,
        band_gap_max=3.5,
        band_gap_critical=True,
        note="발광소자: 가시광 대응 밴드갭",
    ),
    "logic": ApplicationProfile(
        name="logic",
        band_gap_min=0.5,
        band_gap_max=1.5,
        band_gap_critical=True,
        note="로직/트랜지스터: 적정 밴드갭(Si 급)",
    ),
    "dielectric": ApplicationProfile(
        name="dielectric",
        band_gap_min=4.0,
        band_gap_max=None,
        band_gap_critical=True,
        note="게이트 유전체: 넓은 밴드갭(high-k)",
    ),
}

# 이슈 텍스트 → 응용 감지 키워드
_APP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "power": ("파워", "power", "전력", "고전압", "high voltage", "인버터", "igbt", "mosfet"),
    "led": ("led", "발광", "광소자", "발광소자", "laser", "레이저"),
    "logic": ("로직", "logic", "트랜지스터", "transistor", "cpu", "소자 스위칭", "cmos"),
    "dielectric": ("유전체", "dielectric", "게이트", "gate oxide", "high-k", "절연막"),
}


def detect_application(text: str) -> ApplicationProfile | None:
    """이슈 텍스트에서 응용을 감지해 프로파일을 반환(없으면 None)."""
    low = text.lower()
    for app, kws in _APP_KEYWORDS.items():
        if any(k.lower() in low for k in kws):
            return PROFILES[app]
    return None
