"""LLM 클라이언트 추상 인터페이스 (T-005).

핵심 설계 원칙: 코어는 특정 SDK(boto3/Bedrock, HTTP 게이트웨이 등)에 종속되지 않는다.
코어의 TriageEngine/ReportEngine 등은 아래 LLMClient Protocol 에만 의존하며,
실제 백엔드는 이 Protocol 을 구현하는 별도 구현체(BedrockLLMClient,
GatewayLLMClient, MockLLMClient ...)로 주입된다.

지금 단계에서는 MockLLMClient 로 개발/테스트하고, 실제 Bedrock 연동은 나중에
동일 인터페이스 구현체로 갈아끼운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class LLMMessage:
    """대화 메시지. role 은 'system' | 'user' | 'assistant'."""

    role: str
    content: str


@dataclass
class LLMResponse:
    """LLM 응답 표준 형태 (백엔드 독립)."""

    text: str
    # 원본 응답/토큰 사용량 등 백엔드별 부가정보 (선택)
    raw: Any | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    model_id: str | None = None


@runtime_checkable
class LLMClient(Protocol):
    """LLM 백엔드 추상 인터페이스.

    구현체는 아래 세 메서드를 제공한다. 코어는 이 시그니처에만 의존한다.
    """

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        """자유 형식 텍스트 응답."""
        ...

    def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """JSON 객체로 파싱된 응답 (Triage/추출 등 구조화 출력용)."""
        ...

    def embed(self, text: str) -> list[float]:
        """임베딩 벡터 (RAG용). 미지원 구현체는 NotImplementedError 를 던질 수 있다."""
        ...


def system(content: str) -> LLMMessage:
    return LLMMessage(role="system", content=content)


def user(content: str) -> LLMMessage:
    return LLMMessage(role="user", content=content)


def assistant(content: str) -> LLMMessage:
    return LLMMessage(role="assistant", content=content)
