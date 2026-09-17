"""T-210: API/서비스 계층 테스트 (FastAPI TestClient, 가짜 커넥터로 네트워크 없음)."""

from __future__ import annotations

import matcause.app_service as app_service
from matcause.core.llm.mock_client import MockLLMClient
from matcause.core.pipeline import build_orchestrator
from matcause.plugins.semiconductor.material_analyzer import (
    SemiconductorMaterialAnalyzer,
)

from tests.test_material_path import FakeConnector
from tests.test_pipeline import FakePlugin


def _fake_service():
    """네트워크 없이 도는 DiagnosisService 를 수동 구성."""
    svc = app_service.DiagnosisService.__new__(app_service.DiagnosisService)
    llm = MockLLMClient()
    plugin = FakePlugin(llm)
    svc._llm = llm
    svc._plugin = plugin
    svc._orch = build_orchestrator(plugin, llm, report_kind="OCAP")
    svc._store = {}
    return svc


def test_service_diagnose_and_get(monkeypatch):
    svc = _fake_service()
    monkeypatch.setattr(app_service, "get_service", lambda: svc)

    dx = svc.diagnose("GaN 에피층 소재 물성 이상, 누설전류 상승")
    assert dx.triage.category.value == "MATERIAL"
    assert dx.report is not None
    # 조회 가능
    assert svc.get(dx.id) is dx


def test_api_diagnose_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    svc = _fake_service()
    monkeypatch.setattr(app_service, "get_service", lambda: svc)
    # routes 모듈이 참조하는 get_service 도 교체
    import matcause.api.routes as routes
    monkeypatch.setattr(routes, "get_service", lambda: svc)

    from matcause.api.main import app

    client = TestClient(app)
    resp = client.post("/diagnose", json={"text": "GaN 소재 물성 이상으로 누설전류 상승"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "REPORTED"
    assert data["triage"]["category"] == "MATERIAL"
    assert data["material_finding"]["risk_score"] == 0.0
    assert data["report"]["markdown"]

    # 조회 엔드포인트
    dx_id = data["id"]
    resp2 = client.get(f"/diagnosis/{dx_id}")
    assert resp2.status_code == 200
    assert resp2.json()["id"] == dx_id


def test_api_rejects_blank(monkeypatch):
    from fastapi.testclient import TestClient

    svc = _fake_service()
    import matcause.api.routes as routes
    monkeypatch.setattr(routes, "get_service", lambda: svc)
    from matcause.api.main import app

    client = TestClient(app)
    resp = client.post("/diagnose", json={"text": "   "})
    assert resp.status_code == 400


def test_health_endpoint():
    from fastapi.testclient import TestClient

    from matcause.api.main import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
