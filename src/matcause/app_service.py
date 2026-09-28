"""애플리케이션 서비스 조립 (UI/API 공용).

.env 로드 → LLM/플러그인/Orchestrator 를 빌드해 재사용한다. 진단 결과를
메모리에 보관해 조회할 수 있게 한다(간이 저장소; 영속화는 T-131).

LLM 은 현재 MockLLMClient. 실제 Bedrock 연동(T-100) 시 build_llm() 만 교체하면 된다.
"""

from __future__ import annotations

import os
from functools import lru_cache

from .core.llm.base import LLMClient
from .core.llm.gateway_client import BedrockGatewayLLMClient
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
    """LLM 구현체 생성 지점 (T-100).

    LLM_PROVIDER 설정으로 백엔드를 전환한다:
    - "gateway": 주최 측 OpenAI 호환 Bedrock 게이트웨이(BedrockGatewayLLMClient)
    - 그 외/실패: MockLLMClient (개발/테스트, 외부 호출 없음)

    게이트웨이 선택 시 API_KEY 가 없거나 openai 미설치면 안전하게 Mock 으로 폴백한다.
    """
    try:
        from .core.config import get_settings

        settings = get_settings()
    except Exception:  # noqa: BLE001
        return MockLLMClient()

    if settings.llm_provider.strip().lower() == "gateway":
        api_key = settings.api_key or os.environ.get("API_KEY")
        if not api_key:
            print("[MatCause] LLM_PROVIDER=gateway 이지만 API_KEY 가 없어 Mock 으로 폴백합니다.")
            return MockLLMClient()
        try:
            return BedrockGatewayLLMClient(
                base_url=settings.gateway_base_url,
                api_key=api_key,
                model=settings.gateway_model,
                fallback_model=settings.gateway_fallback_model,
                verify_ssl=settings.gateway_verify_ssl,
            )
        except Exception as exc:  # noqa: BLE001 - 생성 실패 시 Mock 폴백
            print(f"[MatCause] 게이트웨이 클라이언트 생성 실패({exc}), Mock 으로 폴백합니다.")
            return MockLLMClient()

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

    def diagnose(
        self, text: str, override: str | None = None, on_step=None
    ) -> Diagnosis:
        cat = None
        if override:
            try:
                cat = TriageCategory(override.upper())
            except ValueError:
                cat = None
        dx = self._orch.diagnose(IssueRequest(raw_text=text), override=cat, on_step=on_step)
        self._store[dx.id] = dx
        return dx

    def get(self, diagnosis_id: str) -> Diagnosis | None:
        return self._store.get(diagnosis_id)

    def list_all(self) -> list[Diagnosis]:
        """보관된 모든 진단을 최신순으로 반환한다."""
        return sorted(self._store.values(), key=lambda d: d.created_at, reverse=True)

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
        return engine.build(template, finding, dx.issue, refs, triage=dx.triage)

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
