"""T-110: MpConnector 테스트.

네트워크 없이 검증: 캐시 폴백, 오프라인 모드, 캐시 키 안정성, 직렬화, 라이브 조회
모킹(가짜 MPRester). mp-api 미설치 환경에서도 동작하도록 지연 import 지점만 모킹한다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from matcause.plugins.semiconductor.mp_connector import (
    DEFECT_ENERGY_NOTE,
    MpConnector,
    MpConnectorError,
)


class _FakeDoc(SimpleNamespace):
    """MPDataDoc 대용: 필드를 속성으로 노출."""


def _fake_docs():
    return [
        _FakeDoc(
            material_id="mp-804",
            formula_pretty="GaN",
            formation_energy_per_atom=-0.74,
            energy_above_hull=0.0,
            band_gap=1.74,
            density=6.1,
            is_stable=True,
            is_metal=False,
            symmetry=SimpleNamespace(model_dump=lambda: {"crystal_system": "Hexagonal"}),
            nsites=4,
            volume=45.2,
        ),
        _FakeDoc(
            material_id="mp-1007824",
            formula_pretty="GaN",
            formation_energy_per_atom=-0.60,
            energy_above_hull=0.12,
            band_gap=1.50,
            density=5.9,
            is_stable=False,
            is_metal=False,
            symmetry=SimpleNamespace(model_dump=lambda: {"crystal_system": "Cubic"}),
            nsites=4,
            volume=47.0,
        ),
    ]


class _FakeSummary:
    def search(self, formula=None, fields=None, **kwargs):
        return _fake_docs()


class _FakeMaterials:
    summary = _FakeSummary()


class _FakeMPRester:
    """MPRester 컨텍스트 매니저 대용."""

    last_api_key = None

    def __init__(self, api_key=None):
        _FakeMPRester.last_api_key = api_key
        self.materials = _FakeMaterials()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


def _patch_live(monkeypatch, rester=_FakeMPRester):
    """MpConnector._mprester 가 가짜 MPRester 를 쓰도록 패치."""
    monkeypatch.setattr(
        MpConnector, "_mprester", lambda self: rester(self._api_key)
    )


def test_live_summary_picks_best_and_notes_defect_energy(monkeypatch, cache_dir):
    _patch_live(monkeypatch)
    conn = MpConnector(api_key="KEY", cache_dir=str(cache_dir))

    result = conn.query_summary("GaN")

    assert result["source"] == "MP_API"
    assert result["formula"] == "GaN"
    # 결함 에너지 부재 메모가 반드시 포함(데이터 정직성)
    assert DEFECT_ENERGY_NOTE in result["notes"]
    # best 는 energy_above_hull 최소(0.0) 후보
    assert result["best"]["material_id"] == "mp-804"
    assert len(result["materials"]) == 2
    # 중첩 symmetry 가 dict 로 직렬화됨
    assert result["materials"][0]["symmetry"] == {"crystal_system": "Hexagonal"}


def test_live_success_writes_cache(monkeypatch, cache_dir):
    _patch_live(monkeypatch)
    conn = MpConnector(api_key="KEY", cache_dir=str(cache_dir))
    conn.query_summary("GaN")

    files = list(cache_dir.glob("summary_GaN_*.json"))
    assert len(files) == 1
    # 캐시 내용이 유효 JSON
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["formula"] == "GaN"


def test_api_failure_falls_back_to_cache(monkeypatch, cache_dir):
    # 1) 먼저 성공 조회로 캐시 생성
    _patch_live(monkeypatch)
    conn = MpConnector(api_key="KEY", cache_dir=str(cache_dir))
    conn.query_summary("GaN")

    # 2) 이후 라이브 조회가 실패하도록 패치
    def _boom(self):
        raise RuntimeError("network down")

    monkeypatch.setattr(MpConnector, "_mprester", _boom)

    result = conn.query_summary("GaN")
    assert result["source"] == "CACHE"
    assert any("라이브 조회 실패" in n for n in result["notes"])


def test_offline_uses_cache_only(monkeypatch, cache_dir):
    # 캐시를 먼저 만들어 둔다
    _patch_live(monkeypatch)
    MpConnector(api_key="KEY", cache_dir=str(cache_dir)).query_summary("GaN")

    # 오프라인 커넥터는 라이브를 아예 호출하지 않아야 한다
    def _should_not_call(self):
        raise AssertionError("offline 모드에서 라이브 조회를 시도함")

    monkeypatch.setattr(MpConnector, "_mprester", _should_not_call)
    offline = MpConnector(api_key=None, cache_dir=str(cache_dir), offline=True)
    result = offline.query_summary("GaN")
    assert result["formula"] == "GaN"


def test_offline_without_cache_raises(cache_dir):
    offline = MpConnector(api_key=None, cache_dir=str(cache_dir), offline=True)
    with pytest.raises(MpConnectorError):
        offline.query_summary("NeverCached")


def test_missing_api_key_falls_back_or_errors(cache_dir):
    # 키 없음 + 캐시 없음 → MpConnectorError
    conn = MpConnector(api_key=None, cache_dir=str(cache_dir))
    with pytest.raises(MpConnectorError):
        conn.query_summary("GaN")


def test_blank_formula_rejected(cache_dir):
    conn = MpConnector(api_key="KEY", cache_dir=str(cache_dir))
    with pytest.raises(ValueError):
        conn.query_summary("   ")


def test_cache_key_stable_and_distinct(cache_dir):
    conn = MpConnector(api_key="KEY", cache_dir=str(cache_dir))
    k1 = conn._cache_key("summary", "GaN")
    k2 = conn._cache_key("summary", "GaN")
    k3 = conn._cache_key("summary", "Si")
    assert k1 == k2
    assert k1 != k3
    assert k1.startswith("summary_GaN_")
