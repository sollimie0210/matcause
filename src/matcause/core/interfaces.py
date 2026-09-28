"""코어가 의존하는 추상 인터페이스 (Contract-first, T-005 확정).

코어의 Orchestrator/TriageEngine/ReportEngine 은 아래 Protocol 에만 의존한다.
반도체 플러그인(plugins/semiconductor)이 도메인 Protocol 을 구현한다. 새 산업은
새 플러그인이 DomainPlugin 을 구현하면 코어 수정 없이 동작한다 (US-G1).

LLM 백엔드 인터페이스는 core.llm.base.LLMClient 에 별도로 정의되어 있으며,
코어는 특정 SDK(boto3 등)가 아니라 그 Protocol 에만 의존한다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    Diagnosis,
    Evidence,
    Feedback,
    IssueRequest,
    MaterialFinding,
    ProcessFinding,
    Report,
    TriageResult,
)


@runtime_checkable
class MaterialAnalyzer(Protocol):
    def analyze(self, issue: IssueRequest) -> MaterialFinding: ...


@runtime_checkable
class ProcessAnalyzer(Protocol):
    def analyze(self, issue: IssueRequest) -> ProcessFinding: ...


@runtime_checkable
class KnowledgeBase(Protocol):
    def search(self, query: str, k: int = 5) -> list[Evidence]: ...

    def add_feedback(self, feedback: Feedback) -> None: ...


@runtime_checkable
class ReportTemplate(Protocol):
    def render(
        self,
        finding,
        issue: IssueRequest,
        refs: list[Evidence],
        triage: TriageResult | None = None,
    ) -> Report: ...


@runtime_checkable
class DomainPlugin(Protocol):
    name: str

    def material_analyzer(self) -> MaterialAnalyzer: ...

    def process_analyzer(self) -> ProcessAnalyzer: ...

    def knowledge_base(self) -> KnowledgeBase: ...

    def report_template(self, kind: str) -> ReportTemplate: ...

    def triage_signals(self, issue: IssueRequest) -> dict: ...


@runtime_checkable
class DiagnosisStore(Protocol):
    """진단/피드백 영속화 (T-131). 코어는 이 인터페이스로 저장소를 사용한다."""

    def save_diagnosis(self, diagnosis: Diagnosis) -> None: ...

    def get_diagnosis(self, diagnosis_id: str) -> Diagnosis | None: ...

    def save_feedback(self, feedback: Feedback) -> None: ...
