"""LLM 계층 — SDK 비종속 인터페이스 + 구현체.

- base.LLMClient: 추상 Protocol (코어는 여기에만 의존)
- MockLLMClient: 개발/테스트용 결정론적 구현
- BedrockLLMClient: 실제 백엔드 (T-100에서 구현)

코어 코드는 항상 LLMClient 타입으로 주입받는다. 구현체 교체는 생성 지점에서만
일어난다.
"""

from .base import LLMClient, LLMMessage, LLMResponse, assistant, system, user
from .gateway_client import BedrockGatewayLLMClient
from .mock_client import MockLLMClient, extract_json

__all__ = [
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "MockLLMClient",
    "BedrockGatewayLLMClient",
    "extract_json",
    "system",
    "user",
    "assistant",
]
