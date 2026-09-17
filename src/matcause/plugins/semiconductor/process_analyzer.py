"""공정 분석기 — 이상 변수 규명(통계+ML) + 원인 매핑 (T-121/122, US-C1/C2).

ProcessAnalyzer Protocol을 구현한다.
SECOM 변수는 익명화 → 물리 원인 직접 매핑 불가. 매핑 테이블이 없으면
'통계 이상만 확인(원인 미매핑)'으로 정직하게 표기한다.
"""

from __future__ import annotations

from matcause.core.models import IssueRequest, ProcessFinding


class SecomProcessAnalyzer:
    def __init__(self, loader=None, mapping=None) -> None:
        self._loader = loader
        self._mapping = mapping

    def analyze(self, issue: IssueRequest) -> ProcessFinding:
        raise NotImplementedError("T-122에서 구현")
