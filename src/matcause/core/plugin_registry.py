"""플러그인 레지스트리 — 도메인 플러그인 등록/조회 (T-104, US-G1)."""

from __future__ import annotations

from .interfaces import DomainPlugin

_REGISTRY: dict[str, DomainPlugin] = {}


def register(plugin: DomainPlugin) -> None:
    _REGISTRY[plugin.name] = plugin


def get(name: str) -> DomainPlugin:
    if name not in _REGISTRY:
        raise KeyError(f"등록되지 않은 도메인 플러그인: {name}")
    return _REGISTRY[name]


def available() -> list[str]:
    return list(_REGISTRY)
