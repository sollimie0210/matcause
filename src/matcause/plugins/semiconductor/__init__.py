"""반도체 도메인 플러그인.

DomainPlugin을 구현하는 SemiconductorPlugin을 노출하고 레지스트리에 등록한다 (US-G1).
구현체는 스프린트 1~2에서 채운다.
"""

from __future__ import annotations

from matcause.core.interfaces import DomainPlugin
from matcause.core.models import IssueRequest


class SemiconductorPlugin:
    name = "semiconductor"

    def __init__(self, settings=None, llm: "object | None" = None) -> None:
        self._settings = settings
        self._llm = llm

    def _get_settings(self):
        if self._settings is not None:
            return self._settings
        from matcause.core.config import get_settings

        return get_settings()

    def _build_connector(self):
        from .mp_connector import MpConnector

        s = self._get_settings()
        return MpConnector(
            api_key=getattr(s, "mp_api_key", None),
            cache_dir=getattr(s, "mp_cache_dir", "data/cache"),
            offline=getattr(s, "offline_mode", False),
        )

    def material_analyzer(self):
        from .material_analyzer import SemiconductorMaterialAnalyzer

        return SemiconductorMaterialAnalyzer(
            connector=self._build_connector(), llm=self._llm
        )

    def process_analyzer(self):
        from .process_analyzer import SecomProcessAnalyzer

        return SecomProcessAnalyzer()

    def knowledge_base(self):
        from .knowledge_base import SemiconductorKnowledgeBase

        return SemiconductorKnowledgeBase()

    def report_template(self, kind: str):
        from .report_templates import get_template

        return get_template(kind)

    def triage_signals(self, issue: IssueRequest) -> dict:
        """도메인 규칙 신호: 소재/공정 키워드 카운트 + 추출된 화학식 유무 (T-101)."""
        from .material_extractor import extract_by_regex

        text = issue.combined_text()
        low = text.lower()

        material_kw = (
            "소재", "물성", "조성", "화학식", "결정", "밴드갭", "band gap", "유전율",
            "material", "formation energy", "phase", "결함", "defect", "안정",
            "웨이퍼", "에피", "기판", "박막",
        )
        process_kw = (
            "공정", "센서", "설비", "장비", "수율", "yield", "챔버", "chamber",
            "레시피", "recipe", "process", "온도", "압력", "etch", "식각",
            "증착", "deposition", "cvd", "리소", "litho", "어닐", "anneal",
        )
        mat_hits = [k for k in material_kw if k.lower() in low]
        proc_hits = [k for k in process_kw if k.lower() in low]

        extraction = extract_by_regex(text)
        return {
            "material_keyword_hits": mat_hits,
            "process_keyword_hits": proc_hits,
            "material_keyword_count": len(mat_hits),
            "process_keyword_count": len(proc_hits),
            "extracted_formulas": extraction.formulas,
            "has_chemical_formula": extraction.has_result(),
        }


def register() -> DomainPlugin:
    """레지스트리에 플러그인을 등록하고 인스턴스를 반환한다."""
    from matcause.core import plugin_registry

    plugin = SemiconductorPlugin()
    plugin_registry.register(plugin)
    return plugin
