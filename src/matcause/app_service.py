"""애플리케이션 서비스 조립 (UI/API 공용).

.env 로드 → LLM/플러그인/Orchestrator 를 빌드해 재사용한다. 진단 결과를
메모리에 보관해 조회할 수 있게 한다(간이 저장소; 영속화는 T-131).

LLM 은 현재 MockLLMClient. 실제 Bedrock 연동(T-100) 시 build_llm() 만 교체하면 된다.
"""

from __future__ import annotations

import os
from functools import lru_cache

from .core.llm.base import LLMClient
from .core.llm.mock_client import MockLLMClient
from .core.models import Diagnosis, IssueRequest, Report, TriageCategory
from .core.orchestrator import Orchestrator
from .core.pipeline import build_orchestrator
from .core.report_engine import ReportEngine
from .plugins.semiconductor import SemiconductorPlugin


def _load_env() -> None:
    """.env 로드 후 mp-api 가 읽는 OS 환경변수에 MP_API_KEY 를 반영."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001
        pass
    try:
        from .core.config import get_settings

        key = get_settings().mp_api_key
        if key and not os.environ.get("MP_API_KEY"):
            os.environ["MP_API_KEY"] = key
    except Exception:  # noqa: BLE001
        pass


def build_llm() -> LLMClient:
    """LLM 구현체 생성 지점. 실제 Bedrock 연동 시 여기만 교체(T-100)."""
    return MockLLMClient()


class DiagnosisService:
    """진단 실행 + 결과 보관(메모리)."""

    def __init__(self, report_kind: str = "OCAP") -> None:
        _load_env()
        self._llm = build_llm()
        self._plugin = SemiconductorPlugin(llm=self._llm)
        self._orch: Orchestrator = build_orchestrator(
            self._plugin, self._llm, report_kind=report_kind
        )
        self._store: dict[str, Diagnosis] = {}

    def diagnose(self, text: str, override: str | None = None) -> Diagnosis:
        cat = None
        if override:
            try:
                cat = TriageCategory(override.upper())
            except ValueError:
                cat = None
        dx = self._orch.diagnose(IssueRequest(raw_text=text), override=cat)
        self._store[dx.id] = dx
        return dx

    def get(self, diagnosis_id: str) -> Diagnosis | None:
        return self._store.get(diagnosis_id)

    def build_customer_report(self, diagnosis_id: str) -> Report | None:
        """저장된 진단으로부터 고객사 제출용 리포트를 생성한다(근거 ID 미노출)."""
        dx = self._store.get(diagnosis_id)
        if dx is None:
            return None
        finding = dx.material_finding or dx.process_finding
        if finding is None:
            return None
        refs = list(getattr(finding, "evidences", []))
        for c in getattr(finding, "ranked_candidates", []) or []:
            refs += c.evidences
        template = self._plugin.report_template("CUSTOMER")
        engine = ReportEngine(self._llm)
        return engine.build(template, finding, dx.issue, refs)

    def customer_report_pdf(self, diagnosis_id: str) -> bytes | None:
        """고객사 제출용 리포트를 PDF 바이트로 반환한다."""
        report = self.build_customer_report(diagnosis_id)
        if report is None:
            return None
        from .core.report_pdf import report_to_pdf_bytes

        return report_to_pdf_bytes(report.markdown, title="MatCause 고객사 리포트")


@lru_cache
def get_service() -> DiagnosisService:
    """프로세스당 하나의 서비스 인스턴스(Orchestrator 재사용)."""
    return DiagnosisService()
