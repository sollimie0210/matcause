"""Bedrock 게이트웨이 LLM 구현체 (T-100, 실연동).

주최 측이 제공한 백엔드는 boto3(bedrock-runtime)가 아니라 **OpenAI 호환 게이트웨이**다.
따라서 `openai` 패키지의 `OpenAI` 클라이언트를 `base_url` 만 게이트웨이로 바꿔 사용한다.

- base_url  : 예) https://52.79.201.46/v1
- api_key   : .env 의 API_KEY
- model     : 기본 "bedrock-haiku", 필요 시 "bedrock-claude-sonnet-5" 로 교체

설계 원칙(SDK 비종속)은 유지된다: 코어는 여전히 core.llm.base.LLMClient Protocol 에만
의존하고, 이 구현체가 그 Protocol(complete / complete_json / embed)을 만족한다.
MockLLMClient 는 그대로 두고, app_service/config 의 LLM_PROVIDER 로 어느 쪽을 쓸지 전환한다.

주의:
- openai import 는 모듈 최상단이 아니라 클라이언트 생성 시점(지연 로딩)에 한다. 그래야
  openai 미설치 환경에서도 core.llm 패키지 import 가 깨지지 않는다.
- IP 기반 HTTPS 는 자체서명 인증서일 수 있어, verify_ssl=False 면 인증서 검증을 끈
  httpx 클라이언트를 주입한다(데모 편의). 운영에서는 정식 인증서 사용을 권장.
"""

from __future__ import annotations

from typing import Any

from .base import LLMMessage, LLMResponse
from .mock_client import extract_json


class BedrockGatewayLLMClient:
    """OpenAI 호환 Bedrock 게이트웨이 구현. LLMClient Protocol 을 만족한다."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "bedrock-haiku",
        fallback_model: str | None = "bedrock-claude-sonnet-5",
        embedding_model: str | None = None,
        verify_ssl: bool = False,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError(
                "게이트웨이 API_KEY 가 비어 있습니다. .env 의 API_KEY 를 설정하세요."
            )
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model_id = model  # 코어/로그에서 참조하는 표준 속성명
        self._model = model
        self._fallback_model = fallback_model
        self._embedding_model = embedding_model
        self._verify_ssl = verify_ssl
        self._timeout = timeout
        self._client = None  # openai.OpenAI 지연 생성

    # ── 내부: OpenAI 클라이언트 지연 생성 ──
    def _ensure_client(self):
        if self._client is not None:
            return self._client
        from openai import OpenAI  # 지연 import

        http_client = None
        if not self._verify_ssl:
            # 자체서명 인증서(IP HTTPS) 대응: 검증 비활성화한 httpx 클라이언트 주입.
            try:
                import httpx  # openai 의존성으로 항상 존재

                http_client = httpx.Client(verify=False, timeout=self._timeout)
            except Exception:  # noqa: BLE001 - httpx 주입 실패 시 기본 클라이언트 사용
                http_client = None

        kwargs: dict[str, Any] = {
            "base_url": self._base_url,
            "api_key": self._api_key,
            "timeout": self._timeout,
        }
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._client = OpenAI(**kwargs)
        return self._client

    @staticmethod
    def _to_openai_messages(messages: list[LLMMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    def _chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ):
        client = self._ensure_client()
        return client.chat.completions.create(
            model=model,
            messages=self._to_openai_messages(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    # ── LLMClient 인터페이스 ──
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        resp = self._chat(
            messages,
            model=self._model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        choice = resp.choices[0]
        text = (choice.message.content or "").strip()
        usage = {}
        if getattr(resp, "usage", None) is not None:
            u = resp.usage
            usage = {
                "prompt_tokens": getattr(u, "prompt_tokens", None),
                "completion_tokens": getattr(u, "completion_tokens", None),
                "total_tokens": getattr(u, "total_tokens", None),
            }
        return LLMResponse(
            text=text,
            raw=resp,
            usage=usage,
            model_id=getattr(resp, "model", self._model),
        )

    def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """구조화 출력. 먼저 기본 모델로 시도하고, JSON 파싱 실패 시 fallback 모델로 재시도."""
        # 1) 기본 모델
        resp = self.complete(
            messages, temperature=temperature, max_tokens=max_tokens, **kwargs
        )
        parsed = self._try_parse_json(resp.text)
        if parsed is not None:
            return parsed

        # 2) fallback 모델로 재시도(있을 때만)
        if self._fallback_model and self._fallback_model != self._model:
            fb = self._chat(
                messages,
                model=self._fallback_model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            text = (fb.choices[0].message.content or "").strip()
            parsed = self._try_parse_json(text)
            if parsed is not None:
                return parsed

        # 3) 그래도 실패하면 원문을 담아 반환(코어가 안전하게 폴백하도록)
        raise ValueError(f"게이트웨이 응답에서 JSON 파싱 실패: {resp.text[:300]!r}")

    @staticmethod
    def _try_parse_json(text: str) -> dict[str, Any] | None:
        try:
            return extract_json(text)
        except Exception:  # noqa: BLE001
            return None

    def embed(self, text: str) -> list[float]:
        if not self._embedding_model:
            raise NotImplementedError(
                "임베딩 모델이 설정되지 않았습니다(GATEWAY_EMBEDDING_MODEL). "
                "RAG 임베딩이 필요하면 지정하세요."
            )
        client = self._ensure_client()
        resp = client.embeddings.create(model=self._embedding_model, input=text)
        return list(resp.data[0].embedding)
