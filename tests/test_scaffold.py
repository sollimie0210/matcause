"""스캐폴드 무결성 테스트 (T-000).

핵심: 코어/플러그인 패키지가 import 되고, 플러그인이 코어 인터페이스를 만족하며,
레지스트리에 등록/조회된다. 실제 로직은 이후 스프린트에서 테스트한다.
"""

from __future__ import annotations


def test_core_imports():
    from matcause.core import (  # noqa: F401
        config,
        interfaces,
        models,
        orchestrator,
        plugin_registry,
        report_engine,
        triage,
    )


def test_models_construct():
    from matcause.core.models import Evidence, EvidenceSource, IssueRequest

    issue = IssueRequest(id="i1", raw_text="누설전류 상승")
    assert issue.raw_text == "누설전류 상승"
    ev = Evidence(id="e1", source_type=EvidenceSource.MP, source_ref="mp-149")
    assert ev.source_type == EvidenceSource.MP


def test_plugin_registers_and_satisfies_interface():
    from matcause.core import plugin_registry
    from matcause.core.interfaces import DomainPlugin
    from matcause.plugins.semiconductor import register

    plugin = register()
    assert isinstance(plugin, DomainPlugin)
    assert plugin.name == "semiconductor"
    assert "semiconductor" in plugin_registry.available()
    assert plugin_registry.get("semiconductor") is plugin
