"""파이프라인 조립 헬퍼 (T-102 연동).

플러그인 + TriageEngine + ReportEngine + Orchestrator 를 하나의 LLMClient 로
배선해 Orchestrator 를 만든다. 데모/UI/API 가 공통으로 사용한다.

LLM 구현체는 주입식(SDK 비종속): 지금은 MockLLMClient, 나중에 BedrockLLMClient 로 교체.
"""

from __future__ import annotations

from .config import get_settings
from .interfaces import DomainPlugin
from .llm.base import LLMClient
from .orchestrator import Orchestrator
from .report_engine import ReportEngine
from .triage import TriageEngine


def build_orchestrator(
    plugin: DomainPlugin,
    llm: LLMClient,
    store=None,
    report_kind: str = "OCAP",
    threshold: float | None = None,
) -> Orchestrator:
    if threshold is None:
        threshold = get_settings().triage_confidence_threshold
    triage = TriageEngine(plugin, llm, threshold=threshold)
    report_engine = ReportEngine(llm)
    return Orchestrator(
        plugin,
        triage=triage,
        report_engine=report_engine,
        store=store,
        report_kind=report_kind,
    )
