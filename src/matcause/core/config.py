"""애플리케이션 설정 (pydantic-settings). .env에서 로드 (T-104)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM 백엔드 선택: "mock" | "gateway"
    llm_provider: str = "mock"

    # Bedrock 게이트웨이 (OpenAI 호환, 주최 측 제공 — T-100)
    gateway_base_url: str = "https://52.79.201.46/v1"
    api_key: str | None = None
    gateway_model: str = "bedrock-haiku"
    gateway_fallback_model: str = "bedrock-claude-sonnet-5"
    gateway_verify_ssl: bool = False

    # AWS Bedrock (boto3 직접 연동 — 현재 미사용, 참고용)
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    bedrock_fallback_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"

    # Materials Project
    mp_api_key: str | None = None

    # 데이터 경로
    secom_data_dir: str = "data/secom"
    mp_cache_dir: str = "data/cache"

    # 저장소
    database_url: str = "sqlite:///matcause.db"

    # Triage
    triage_confidence_threshold: float = 0.6

    # 동작 모드
    offline_mode: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
