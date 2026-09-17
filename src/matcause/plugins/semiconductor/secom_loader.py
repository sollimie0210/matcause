"""SECOM 로더 — CSV 로드/전처리/불균형 처리 (T-120, US-C1).

SECOM: 1567 records x 590 anonymized features, Pass/Fail(-1/+1), ~104 fail (약 1:14).
클래스 불균형을 명시적으로 처리하고 방법을 기록한다.
"""

from __future__ import annotations


class SecomLoader:
    def __init__(self, data_dir: str) -> None:
        self._data_dir = data_dir

    def load(self):
        """(X, y) 형태로 로드. 결측 처리·라벨 정렬 포함."""
        raise NotImplementedError("T-120에서 구현")
