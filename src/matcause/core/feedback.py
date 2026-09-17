"""피드백 로거 — 리포트 피드백을 KB에 구조화 저장 (T-220, US-E1)."""

from __future__ import annotations

from .models import Feedback


class FeedbackLogger:
    def __init__(self, store=None, knowledge_base=None) -> None:
        self._store = store
        self._kb = knowledge_base

    def record(self, feedback: Feedback) -> None:
        raise NotImplementedError("T-220에서 구현")
