"""소재-결함 지식베이스 + 변수→원인 매핑 (T-201, US-C2/E1).

KnowledgeBase Protocol을 구현한다. seed는 공개 문헌 인용(출처 URL 포함)으로 채운다.
"""

from __future__ import annotations

from matcause.core.models import Evidence


class SemiconductorKnowledgeBase:
    def __init__(self, resources_dir: str | None = None, store=None) -> None:
        self._resources_dir = resources_dir
        self._store = store

    def search(self, query: str, k: int = 5) -> list[Evidence]:
        raise NotImplementedError("T-201에서 구현")

    def add_feedback(self, feedback) -> None:
        raise NotImplementedError("T-220에서 구현")
