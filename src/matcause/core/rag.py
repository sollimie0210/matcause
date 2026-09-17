"""경량 RAG — 임베딩(Titan) + FAISS/sqlite-vec 인덱스 (T-221, US-E2).

과거 피드백/확정 리포트를 검색해 Triage/리포트 프롬프트에 주입한다.
"""

from __future__ import annotations

from .models import Evidence


class RagIndex:
    def __init__(self, embedder=None, index_path: str | None = None) -> None:
        self._embedder = embedder
        self._index_path = index_path

    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        raise NotImplementedError("T-221에서 구현")

    def search(self, query: str, k: int = 5) -> list[Evidence]:
        raise NotImplementedError("T-221에서 구현")
