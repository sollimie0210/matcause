"""MockLLMClient — 개발/테스트용 LLM 구현체 (T-005).

클라우드 접근 없이 코어/트랙이 병렬 개발할 수 있도록 하는 결정론적 LLM.
LLMClient Protocol 을 구현한다. 실제 Bedrock/게이트웨이 구현체와 동일하게
주입해서 사용하며, 나중에 그대로 교체 가능하다.

동작:
- complete: 마지막 user 메시지를 요약한 고정 텍스트를 반환
- complete_json: 규칙(scripted responses > 키워드 휴리스틱)으로 JSON 반환
- embed: 텍스트 해시 기반 결정론적 저차원 벡터 (RAG 개발용, 의미없는 값 아님을
  가정하지 말 것 — 어디까지나 목업)

scripted_responses 로 특정 프롬프트에 대한 응답을 지정할 수 있어 테스트에 유용하다.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .base import LLMMessage, LLMResponse

# Triage 휴리스틱용 키워드 (도메인 신호가 없을 때의 최소 폴백)
_MATERIAL_HINTS = (
    "소재", "물성", "조성", "화학식", "결정", "밴드갭", "band gap", "유전율",
    "material", "formation energy", "phase", "결함", "defect", "안정",
)
_PROCESS_HINTS = (
    "공정", "센서", "설비", "장비", "수율", "yield", "챔버", "chamber",
    "레시피", "recipe", "process", "온도", "압력", "etch", "deposition", "cvd",
)


class MockLLMClient:
    """LLMClient Protocol 을 만족하는 목업 구현."""

    def __init__(
        self,
        scripted_responses: dict[str, Any] | None = None,
        embed_dim: int = 16,
    ) -> None:
        # 키(부분 문자열) -> 응답(dict 또는 str). complete_json 에서 우선 적용.
        self._scripted = scripted_responses or {}
        self._embed_dim = embed_dim
        self.model_id = "mock-llm"

    # ── 내부 헬퍼 ──
    @staticmethod
    def _last_user(messages: list[LLMMessage]) -> str:
        for m in reversed(messages):
            if m.role == "user":
                return m.content
        return messages[-1].content if messages else ""

    def _match_script(self, text: str) -> Any | None:
        for key, resp in self._scripted.items():
            if key in text:
                return resp
        return None

    # ── LLMClient 인터페이스 ──
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        text = self._last_user(messages)
        scripted = self._match_script(text)
        if isinstance(scripted, str):
            out = scripted
        elif isinstance(scripted, dict):
            out = json.dumps(scripted, ensure_ascii=False)
        elif self._looks_like_summary_prompt(text):
            out = self._synthesize_summary(text)
        else:
            out = f"[MOCK] 요약: {text.strip()[:200]}"
        return LLMResponse(text=out, model_id=self.model_id, usage={"mock": True})

    def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> dict[str, Any]:
        text = self._last_user(messages)

        # 1) 스크립트 우선
        scripted = self._match_script(text)
        if isinstance(scripted, dict):
            return scripted
        if isinstance(scripted, str):
            try:
                return json.loads(scripted)
            except json.JSONDecodeError:
                return {"text": scripted}

        # 2) 키워드 휴리스틱으로 Triage 형태 JSON 생성 (개발용 기본값)
        return self._heuristic_triage(text)

    def _heuristic_triage(self, text: str) -> dict[str, Any]:
        low = text.lower()
        mat = sum(1 for k in _MATERIAL_HINTS if k.lower() in low)
        proc = sum(1 for k in _PROCESS_HINTS if k.lower() in low)
        total = mat + proc
        if total == 0:
            return {
                "category": "AMBIGUOUS",
                "confidence": 0.3,
                "rationale": "[MOCK] 소재/공정 신호가 뚜렷하지 않음",
            }
        if mat >= proc:
            conf = round(0.5 + 0.5 * (mat / total), 2)
            cat = "MATERIAL" if mat > proc else "AMBIGUOUS"
        else:
            conf = round(0.5 + 0.5 * (proc / total), 2)
            cat = "PROCESS"
        return {
            "category": cat,
            "confidence": conf,
            "rationale": f"[MOCK] 소재 신호 {mat}건 / 공정 신호 {proc}건",
        }

    # ── 리포트 요약 합성 (프롬프트의 원인/조치/근거를 파싱해 2~3문장 생성) ──

    @staticmethod
    def _looks_like_summary_prompt(text: str) -> bool:
        return "[판정 원인]" in text and "[권장 조치]" in text

    @staticmethod
    def _section(text: str, header: str) -> str:
        """`[header]` 다음부터 다음 `[` 섹션 전까지의 내용을 추출."""
        m = re.search(rf"\[{re.escape(header)}\]\s*(.*?)(?=\n\[|\Z)", text, re.DOTALL)
        return m.group(1).strip() if m else ""

    def _synthesize_summary(self, text: str) -> str:
        """제공된 근거만으로 2~3문장 한국어 요약을 조립(새 수치 생성 금지)."""
        cause = self._section(text, "판정 원인")
        actions = self._section(text, "권장 조치")
        evidence = self._section(text, "근거 요약")

        sentences: list[str] = []
        if cause:
            # 원인 문장이 너무 길면 앞부분만
            head = cause.split("\n")[0].strip()
            sentences.append(f"분석 결과, {head}")
        if actions and actions not in ("없음", ""):
            first_action = actions.split(";")[0].strip()
            sentences.append(f"권장 조치로는 {first_action}")
        if evidence and evidence not in ("정량 근거 없음", ""):
            # 근거 항목 수를 세어 신뢰성 언급(수치는 근거에서 온 것만)
            n = evidence.count("=")
            if n:
                sentences.append(f"이 판단은 {n}건의 정량 근거에 기반합니다.")
            else:
                sentences.append("이 판단은 제공된 근거에 기반합니다.")

        if not sentences:
            return "제공된 근거가 부족하여 요약을 생성할 수 없습니다."
        return " ".join(s.rstrip(". ") + "." for s in sentences[:3])

    def embed(self, text: str) -> list[float]:
        """해시 기반 결정론적 벡터 (목업). 같은 입력엔 같은 벡터를 반환한다."""
        vec: list[float] = []
        for i in range(self._embed_dim):
            h = hashlib.sha256(f"{i}:{text}".encode("utf-8")).digest()
            # 0~1 범위 float
            vec.append(int.from_bytes(h[:4], "big") / 0xFFFFFFFF)
        return vec


def extract_json(text: str) -> dict[str, Any]:
    """LLM 텍스트 응답에서 첫 JSON 객체를 추출한다 (실제 구현체 공용 유틸)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("응답에서 JSON 객체를 찾지 못함")
    return json.loads(match.group(0))
