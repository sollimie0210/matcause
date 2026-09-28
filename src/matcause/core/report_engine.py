"""ReportEngine — 템플릿 렌더 + LLM 서술 보강 + Evidence 바인딩 (T-103, US-D1/D2).

동작:
1. 도메인 ReportTemplate 이 구조화된 Report(원인/조치/검증/근거/markdown)를 만든다.
2. ReportEngine 이 LLM 으로 '요약 서술'을 보강한다. 단, 수치는 Evidence 에서만 인용하고
   근거 밖 수치를 생성하지 못하도록 프롬프트로 제약한다(환각 방지).
3. 각 주장은 이미 Evidence ID 로 원본과 연결되어 있어 추적성이 유지된다(US-D2).

LLM 실패 시에도 템플릿 리포트를 그대로 반환한다(폴백).
"""

from __future__ import annotations

from .interfaces import ReportTemplate
from .llm.base import LLMClient, system, user
from .llm.prompts import SYSTEM_GUARDRAIL
from .models import Evidence, IssueRequest, Report, TriageResult

_SUMMARY_PROMPT = """\
아래는 결함 원인 분석 리포트의 구조화 데이터다. 이를 2~3문장의 한국어 경영진 요약으로
정리하라. 반드시 제공된 근거 안의 내용만 사용하고, 새로운 수치를 만들지 마라.

[판정 원인]
{cause}

[권장 조치]
{actions}

[근거 요약]
{evidence}

요약(2~3문장):
"""


class ReportEngine:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def build(
        self,
        template: ReportTemplate,
        finding,
        issue: IssueRequest,
        refs: list[Evidence],
        triage: TriageResult | None = None,
    ) -> Report:
        # 1) 구조화 리포트 생성 (템플릿)
        report = template.render(finding, issue, refs, triage=triage)

        # 2) LLM 서술 보강 (실패해도 리포트는 유효)
        narrative = self._narrate(report, refs)
        if narrative:
            report.markdown = f"## 요약\n{narrative}\n\n" + report.markdown

        return report

    def _narrate(self, report: Report, refs: list[Evidence]) -> str:
        evidence_summary = "; ".join(
            f"{e.note or e.source_ref or ''}={e.value}"
            for e in refs[:8]
            if e.value is not None
        ) or "정량 근거 없음"
        messages = [
            system(SYSTEM_GUARDRAIL),
            user(
                _SUMMARY_PROMPT.format(
                    cause=report.cause,
                    actions="; ".join(report.recommended_actions) or "없음",
                    evidence=evidence_summary,
                )
            ),
        ]
        try:
            resp = self._llm.complete(messages)
            return resp.text.strip()
        except Exception:  # noqa: BLE001 - 서술 보강 실패는 치명적이지 않음
            return ""
