"""AWS Bedrock LLM 구현체 (T-100에서 실제 구현).

LLMClient Protocol 을 구현하는 '실제 백엔드' 자리. 지금은 인터페이스만 맞춰 두고
호출 시 NotImplementedError 를 던진다. 개발/테스트는 MockLLMClient 를 사용한다.

주의: boto3 import 는 이 모듈 최상단이 아니라 실제 호출 시점(메서드 내부)에서
지연 로딩한다. 그래야 boto3 미설치 환경에서도 core.llm 패키지 import 가 깨지지
않는다 (SDK 비종속 원칙).
"""

from __future__ import annotations

from typing import Any

from .base import LLMMessage, LLMResponse


class BedrockLLMClient:
    """LLMClient Protocol 구현. 실제 로직은 T-100."""

    def __init__(
        self,
        region: str,
        model_id: str,
        fallback_model_id: str | None = None,
        embedding_model_id: str | None = None,
    ) -> None:
        self._region = region
        self._model_id = model_id
        self._fallback_model_id = fallback_model_id
        self._embedding_model_id = embedding_model_id
        self._client = None  # boto3 client 지연 생성

    def _ensure_client(self):
        if self._client is None:
            import boto3  # 지연 import

            self._client = boto3.client("bedrock-runtime", region_name=self._region)
        return self._client

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        raise NotImplementedError("T-100에서 구현: Bedrock invoke_model 연동")

    def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError("T-100에서 구현: 응답 JSON 파싱 + 폴백")

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError("T-221에서 구현: Titan Embeddings")
