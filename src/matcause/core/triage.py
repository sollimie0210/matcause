"""TriageEngine — 소재/공정 1차 분류 (T-101, US-A2).

규칙 기반 신호(도메인 플러그인 제공) + LLM 확신도를 결합해
MATERIAL / PROCESS / AMBIGUOUS 로 분류한다.

결합 방식:
- 규칙 신호: 소재/공정 키워드 카운트 + 화학식 추출 유무로 rule_score(방향 + 강도) 산출.
- LLM: 규칙 신호와 이슈 텍스트를 프롬프트에 넣어 category/confidence/rationale 획득.
- 두 신호를 가중 결합. confidence 가 임계값 미만이면 AMBIGUOUS (US-A2.3).
- 사용자 override 는 Orchestrator 단에서 처리(여기서는 순수 분류).
"""

from __future__ import annotations

from .interfaces import DomainPlugin
from .llm.base import LLMClient, system, user
from .llm.prompts import SYSTEM_GUARDRAIL, TRIAGE_PROMPT
from .models import IssueRequest, TriageCategory, TriageResult

# 규칙 신호 vs LLM 확신도 가중치
_RULE_WEIGHT = 0.5
_LLM_WEIGHT = 0.5


class TriageEngine:
    def __init__(
        self, plugin: DomainPlugin, llm: LLMClient, threshold: float = 0.6
    ) -> None:
        self._plugin = plugin
        self._llm = llm
        self._threshold = threshold

    def classify(self, issue: IssueRequest) -> TriageResult:
        signals = self._plugin.triage_signals(issue)

        rule_cat, rule_conf = self._rule_vote(signals)
        llm_cat, llm_conf, llm_rationale = self._llm_vote(issue, signals)

        category, confidence, rationale = self._combine(
            rule_cat, rule_conf, llm_cat, llm_conf, llm_rationale
        )

        # 임계값 미만이면 모호로 강등 (US-A2.3)
        if confidence < self._threshold and category is not TriageCategory.AMBIGUOUS:
            rationale = (
                f"확신도 {confidence:.2f} < 임계값 {self._threshold} → 모호로 처리. "
                + rationale
            )
            category = TriageCategory.AMBIGUOUS

        return TriageResult(
            category=category,
            confidence=round(confidence, 2),
            rationale=rationale,
            signals=signals,
        )

    # ── 규칙 기반 투표 ──
    def _rule_vote(self, signals: dict) -> tuple[TriageCategory, float]:
        mat = signals.get("material_keyword_count", 0)
        proc = signals.get("process_keyword_count", 0)
        # 화학식이 실제로 잡히면 소재 쪽 신호 강화
        if signals.get("has_chemical_formula"):
            mat += 2
        total = mat + proc
        if total == 0:
            return TriageCategory.AMBIGUOUS, 0.0
        if mat > proc:
            return TriageCategory.MATERIAL, mat / total
        if proc > mat:
            return TriageCategory.PROCESS, proc / total
        return TriageCategory.AMBIGUOUS, 0.5

    # ── LLM 투표 ──
    def _llm_vote(
        self, issue: IssueRequest, signals: dict
    ) -> tuple[TriageCategory, float, str]:
        messages = [
            system(SYSTEM_GUARDRAIL),
            user(
                TRIAGE_PROMPT.format(
                    signals=signals, issue_text=issue.combined_text()
                )
            ),
        ]
        try:
            data = self._llm.complete_json(messages)
        except Exception as exc:  # noqa: BLE001 - LLM 실패 시 규칙만 사용
            return TriageCategory.AMBIGUOUS, 0.0, f"LLM 분류 실패({exc}), 규칙 신호만 사용"

        cat = self._parse_category(data.get("category"))
        try:
            conf = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        rationale = str(data.get("rationale", "")) or "LLM 근거 없음"
        return cat, conf, rationale

    @staticmethod
    def _parse_category(raw) -> TriageCategory:
        if isinstance(raw, str):
            key = raw.strip().upper()
            if key in TriageCategory.__members__:
                return TriageCategory[key]
        return TriageCategory.AMBIGUOUS

    # ── 결합 ──
    def _combine(
        self,
        rule_cat: TriageCategory,
        rule_conf: float,
        llm_cat: TriageCategory,
        llm_conf: float,
        llm_rationale: str,
    ) -> tuple[TriageCategory, float, str]:
        # 두 신호가 일치하면 확신도 가중합, 방향 유지
        if rule_cat == llm_cat and rule_cat is not TriageCategory.AMBIGUOUS:
            conf = _RULE_WEIGHT * rule_conf + _LLM_WEIGHT * llm_conf
            return rule_cat, conf, f"규칙·LLM 일치({rule_cat.value}). {llm_rationale}"

        # 한쪽만 확정적이면 그쪽 채택(확신도는 감쇠)
        if rule_cat is not TriageCategory.AMBIGUOUS and llm_cat is TriageCategory.AMBIGUOUS:
            return rule_cat, rule_conf * 0.8, f"규칙 신호 우세({rule_cat.value}). {llm_rationale}"
        if llm_cat is not TriageCategory.AMBIGUOUS and rule_cat is TriageCategory.AMBIGUOUS:
            return llm_cat, llm_conf * 0.8, f"LLM 우세({llm_cat.value}). {llm_rationale}"

        # 둘 다 모호하거나 서로 상충 → 더 높은 확신도 쪽, 단 감쇠
        if rule_conf >= llm_conf:
            cat = rule_cat
            conf = rule_conf * 0.6
        else:
            cat = llm_cat
            conf = llm_conf * 0.6
        return cat, conf, f"규칙·LLM 상충/모호. {llm_rationale}"
