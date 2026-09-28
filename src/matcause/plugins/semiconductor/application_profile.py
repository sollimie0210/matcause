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

    def band_gap_span(self) -> float | None:
        """요구 밴드갭 범위의 폭. 한쪽만 있으면 그 값을 스케일로 사용.

        적합성 리스크가 '범위 폭 대비' 상대 편차로 계산되도록(경계 대비/완만 증가)
        하는 데 쓰인다. midpoint(band_gap_target) 대비 방식은 경계 근처에서 과도한
        편차를 내는 옛 버그의 원인이라 폐기했다.
        """
        if self.band_gap_min is not None and self.band_gap_max is not None:
            span = self.band_gap_max - self.band_gap_min
            return span if span > 0 else None
        one = self.band_gap_min if self.band_gap_min is not None else self.band_gap_max
        return one if (one is not None and one > 0) else None

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
        band_gap_min=2.0,   # 와이드 밴드갭(SiC ≈3.3, GaN ≈3.4) 지향. 2.0으로 마진 확보
        band_gap_max=6.5,   # AlN≈6.0, diamond≈5.5 포함
        band_gap_critical=True,
        note="파워 소자: 고전압/저손실 위해 와이드 밴드갭 요구 (SiC/GaN/AlN/Ga2O3)",
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
    """[키워드 폴백] 이슈 텍스트에서 응용을 감지해 프로파일을 반환(없으면 None).

    고정 키워드 부분문자열 매칭. Mock LLM 모드나 LLM 분류 실패 시의 폴백 경로다.
    문맥적 표현('항복전압', '에피 성장' 등)은 여기서 놓칠 수 있으며, 그런 케이스는
    실제 LLM 분류(classify_application)가 담당한다.
    """
    low = text.lower()
    for app, kws in _APP_KEYWORDS.items():
        if any(k.lower() in low for k in kws):
            return PROFILES[app]
    return None


# ── LLM 기반 응용 분류 (실제 Bedrock 연동 시 사용) ──

_APP_SYSTEM = (
    "너는 반도체 이슈 텍스트를 읽고 소자의 '응용 분야'를 분류하는 도우미다. "
    "고정 키워드가 아니라 문맥으로 판단하라. 예: '항복전압', '고전압 스위칭', "
    "'전력 변환'은 power, '가시광 발광'은 led, '스위칭 트랜지스터/로직'은 logic, "
    "'게이트 절연막/high-k'은 dielectric. 응용이 분명치 않으면 unknown 으로 답하라. "
    "근거 없는 단정 금지."
)

_APP_PROMPT = """\
다음 반도체 이슈 텍스트의 응용 분야를 분류하라.

[텍스트]
{text}

가능한 값: power | led | logic | dielectric | unknown
JSON으로만 답하라: {{"application": "...", "confidence": 0~1, "rationale": "..."}}
"""

# 이 신뢰도 미만이면 LLM 분류를 신뢰하지 않고 키워드 폴백으로 내려간다.
_APP_LLM_MIN_CONFIDENCE = 0.5


def _is_mock_llm(llm) -> bool:
    """LLM 이 결정론적 목업인지 판별. 목업이면 LLM 분류 대신 키워드 폴백을 쓴다."""
    if llm is None:
        return True
    model_id = getattr(llm, "model_id", "") or ""
    return "mock" in str(model_id).lower()


def classify_application(text: str, llm=None) -> ApplicationProfile | None:
    """이슈 텍스트에서 응용 프로파일을 판정한다 (LLM 우선, 키워드 폴백).

    - 실제 LLM 백엔드(비-Mock)가 주어지면 LLM 으로 문맥 기반 분류를 우선 시도한다.
      고정 키워드에 없는 표현('항복전압', '에피 성장' 등)도 문맥으로 잡을 수 있다.
    - MockLLMClient 이거나 llm 이 없으면 기존 키워드 감지(detect_application)를 쓴다.
    - LLM 이 unknown/저신뢰/실패면 키워드 폴백으로 안전하게 내려간다.
    """
    # Mock 이거나 LLM 이 없으면 키워드 폴백
    if _is_mock_llm(llm):
        return detect_application(text)

    # 지연 import (core.llm 순환/선택 의존 회피)
    from matcause.core.llm.base import system, user

    try:
        data = llm.complete_json(
            [system(_APP_SYSTEM), user(_APP_PROMPT.format(text=text))]
        )
    except Exception:  # noqa: BLE001 - LLM 실패 시 키워드 폴백
        return detect_application(text)

    app = str(data.get("application", "")).strip().lower()
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0

    if app in PROFILES and conf >= _APP_LLM_MIN_CONFIDENCE:
        return PROFILES[app]

    # unknown / 저신뢰 / 알 수 없는 라벨 → 키워드 폴백(그래도 없으면 None)
    return detect_application(text)
