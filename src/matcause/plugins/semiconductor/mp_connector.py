"""Materials Project 커넥터 — MPRester 조회 + 캐시 폴백 (T-110, US-B1).

데이터 정직성 (design.md 6.2):
- MP 본 DB는 '결함 형성 에너지(defect formation energy)' 직접값을 표준 필드로
  제공하지 않는다. 따라서 확보 가능한 지표만 조회한다:
  formation_energy_per_atom, energy_above_hull(안정성 프록시), band_gap,
  density, is_stable, symmetry 등.
- 응답에는 출처(source)와 조회 시점(retrieved_at)을 항상 표기한다.

폴백 (US-B1.4, NFR-7):
- offline 모드이거나 API 호출이 실패하면 data/cache 스냅샷을 사용한다.
- 라이브 조회 성공 시 결과를 캐시에 기록해 다음 오프라인 데모를 대비한다.

SDK 비종속: mp_api / pymatgen import 는 실제 호출 시점에 지연 로딩한다. 그래야
mp-api 미설치 환경(코어/테스트)에서도 이 모듈 import 가 깨지지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# summary 엔드포인트에서 요청할 필드 (확보 가능한 지표만)
SUMMARY_FIELDS = [
    "material_id",
    "formula_pretty",
    "formation_energy_per_atom",
    "energy_above_hull",
    "band_gap",
    "density",
    "is_stable",
    "is_metal",
    "symmetry",
    "nsites",
    "volume",
]

# 결함 형성 에너지 직접값이 없음을 리포트/근거에 남기기 위한 표준 메모
DEFECT_ENERGY_NOTE = (
    "결함 형성 에너지 직접값은 MP 본 DB 표준 필드가 아님. "
    "energy_above_hull 등 안정성 프록시로 대체함."
)


class MpConnectorError(RuntimeError):
    """MP 조회 실패이며 캐시 폴백도 불가능할 때."""


class MpConnector:
    def __init__(
        self,
        api_key: str | None,
        cache_dir: str,
        offline: bool = False,
    ) -> None:
        self._api_key = api_key
        self._cache_dir = Path(cache_dir)
        self._offline = offline

    # ─────────────────────── 공개 API ───────────────────────

    def query_summary(self, formula: str) -> dict[str, Any]:
        """조성/화학식에 대한 요약 물성을 조회한다.

        반환 dict 예:
        {
          "formula": "GaN",
          "source": "MP_API" | "CACHE",
          "retrieved_at": "...",
          "notes": [DEFECT_ENERGY_NOTE],
          "materials": [ { material_id, formula_pretty, band_gap, ... }, ... ],
          "best": { ... }  # energy_above_hull 최소(가장 안정) 후보
        }
        """
        formula = formula.strip()
        if not formula:
            raise ValueError("formula 가 비어 있습니다")

        cache_key = self._cache_key("summary", formula)

        # 오프라인이면 캐시만 사용
        if self._offline:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached
            raise MpConnectorError(
                f"오프라인 모드인데 '{formula}' 캐시가 없습니다. warm_mp_cache.py 로 미리 생성하세요."
            )

        # 라이브 조회 시도 → 실패 시 캐시 폴백
        try:
            result = self._live_summary(formula)
            self._write_cache(cache_key, result)
            return result
        except Exception as exc:  # noqa: BLE001 - 폴백을 위해 광범위 캐치
            cached = self._read_cache(cache_key)
            if cached is not None:
                cached = dict(cached)
                cached["source"] = "CACHE"
                cached.setdefault("notes", []).append(
                    f"라이브 조회 실패로 캐시 사용: {type(exc).__name__}: {exc}"
                )
                return cached
            raise MpConnectorError(
                f"'{formula}' MP 조회 실패이며 캐시도 없음: {exc}"
            ) from exc

    def query_thermo(self, formula: str) -> dict[str, Any]:
        """열역학 데이터(formation energy 등)를 thermo 엔드포인트에서 조회한다.

        summary 로 대부분의 지표를 얻을 수 있으나, 함수형(functional)별 값 등
        세부가 필요하면 이 메서드를 사용한다. 구현/필드는 T-112에서 확장한다.
        여기서는 summary 기반 최소 구현 + 캐시 폴백을 제공한다.
        """
        formula = formula.strip()
        cache_key = self._cache_key("thermo", formula)

        if self._offline:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached
            raise MpConnectorError(f"오프라인인데 '{formula}' thermo 캐시 없음")

        try:
            result = self._live_thermo(formula)
            self._write_cache(cache_key, result)
            return result
        except Exception as exc:  # noqa: BLE001
            cached = self._read_cache(cache_key)
            if cached is not None:
                cached = dict(cached)
                cached["source"] = "CACHE"
                return cached
            raise MpConnectorError(f"'{formula}' thermo 조회 실패이며 캐시 없음: {exc}") from exc

    def query_candidates(self, formulas: list[str]) -> list[dict[str, Any]]:
        """여러 후보 화학식을 각각 조회해 best 상만 모아 반환한다 (T-113).

        대체 소재 후보 목록(도메인이 제공)을 실제 MP 로 조회한다. 각 후보의
        가장 안정한 상(best)만 뽑아 리스트로 돌려준다. 조회 실패한 후보는 건너뛴다.
        랭킹/트레이드오프 계산은 alternatives_ranker(T-113) 에서 수행한다.
        """
        out: list[dict[str, Any]] = []
        for f in formulas:
            try:
                result = self.query_summary(f)
            except MpConnectorError:
                continue
            best = result.get("best")
            if best:
                cand = dict(best)
                cand.setdefault("formula_pretty", f)
                cand["_source"] = result.get("source")
                out.append(cand)
        return out

    def find_alternatives(self, formula: str, k: int = 5) -> list[dict[str, Any]]:
        """동일 화학공간(chemsys)의 대체 후보 조회.

        source 화학식의 원소들로 chemsys 를 구성해 같은 계열의 안정 물질을
        energy_above_hull 오름차순으로 가져온다. 실제 랭킹은 alternatives_ranker
        (T-113)/analyzer(T-114) 에서 리스크 기반으로 수행한다.
        """
        formula = formula.strip()
        if not formula:
            raise ValueError("formula 가 비어 있습니다")

        cache_key = self._cache_key("alt", formula)
        if self._offline:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached.get("candidates", [])
            raise MpConnectorError(f"오프라인인데 '{formula}' 대체후보 캐시 없음")

        try:
            candidates = self._live_alternatives(formula, k)
            self._write_cache(cache_key, {"formula": formula, "candidates": candidates})
            return candidates
        except Exception as exc:  # noqa: BLE001
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached.get("candidates", [])
            raise MpConnectorError(f"'{formula}' 대체후보 조회 실패이며 캐시 없음: {exc}") from exc

    def _live_alternatives(self, formula: str, k: int) -> list[dict[str, Any]]:
        elements = re.findall(r"[A-Z][a-z]?", formula)
        chemsys = "-".join(sorted(set(elements)))
        with self._mprester() as mpr:
            docs = mpr.materials.summary.search(
                chemsys=chemsys, fields=SUMMARY_FIELDS
            )
        mats = [self._doc_to_dict(d) for d in docs]
        # 안정성 순 정렬(energy_above_hull 오름차순), 상위 k
        mats = [m for m in mats if m.get("energy_above_hull") is not None]
        mats.sort(key=lambda m: m["energy_above_hull"])
        return mats[:k]

    # ─────────────────────── 라이브 조회 (지연 import) ───────────────────────

    def _mprester(self):
        from mp_api.client import MPRester  # 지연 import

        if not self._api_key:
            raise MpConnectorError("MP_API_KEY 가 설정되지 않았습니다")
        return MPRester(self._api_key)

    def _live_summary(self, formula: str) -> dict[str, Any]:
        with self._mprester() as mpr:
            docs = mpr.materials.summary.search(
                formula=formula, fields=SUMMARY_FIELDS
            )
        materials = [self._doc_to_dict(d) for d in docs]
        # energy_above_hull 최소(가장 안정) 후보를 best 로
        best = None
        stable = [m for m in materials if m.get("energy_above_hull") is not None]
        if stable:
            best = min(stable, key=lambda m: m["energy_above_hull"])
        return {
            "formula": formula,
            "source": "MP_API",
            "retrieved_at": _now_iso(),
            "notes": [DEFECT_ENERGY_NOTE],
            "materials": materials,
            "best": best,
        }

    def _live_thermo(self, formula: str) -> dict[str, Any]:
        # thermo 엔드포인트는 material_ids 기반 조회가 일반적이므로,
        # 먼저 summary 로 id 를 찾은 뒤 thermo 를 조회한다.
        summary = self._live_summary(formula)
        material_ids = [
            m["material_id"] for m in summary["materials"] if m.get("material_id")
        ]
        thermo: list[dict[str, Any]] = []
        if material_ids:
            with self._mprester() as mpr:
                docs = mpr.materials.thermo.search(
                    material_ids=material_ids,
                    fields=["material_id", "formation_energy_per_atom", "energy_above_hull"],
                )
            thermo = [self._doc_to_dict(d) for d in docs]
        return {
            "formula": formula,
            "source": "MP_API",
            "retrieved_at": _now_iso(),
            "notes": [DEFECT_ENERGY_NOTE],
            "thermo": thermo,
        }

    # ─────────────────────── 직렬화 헬퍼 ───────────────────────

    @staticmethod
    def _doc_to_dict(doc: Any) -> dict[str, Any]:
        """MPDataDoc → JSON 직렬화 가능한 dict.

        symmetry 등 중첩 pydantic 객체는 관심 필드만 평탄화한다.
        """
        out: dict[str, Any] = {}
        for field in SUMMARY_FIELDS + ["formation_energy_per_atom", "energy_above_hull"]:
            if not hasattr(doc, field):
                continue
            val = getattr(doc, field)
            out[field] = _jsonable(val)
        # material_id 는 문자열로 정규화
        if out.get("material_id") is not None:
            out["material_id"] = str(out["material_id"])
        return out

    # ─────────────────────── 캐시 ───────────────────────

    def _cache_key(self, kind: str, formula: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9]+", "_", formula).strip("_")
        digest = hashlib.sha256(f"{kind}:{formula}".encode("utf-8")).hexdigest()[:8]
        return f"{kind}_{safe}_{digest}"

    def _cache_path(self, cache_key: str) -> Path:
        return self._cache_dir / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        path = self._cache_path(cache_key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, cache_key: str, data: dict[str, Any]) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with self._cache_path(cache_key).open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            # 캐시 쓰기 실패는 조회 자체를 막지 않는다
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(val: Any) -> Any:
    """MP 응답 값(중첩 pydantic/enum 포함)을 JSON 직렬화 가능 형태로 변환."""
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, (list, tuple)):
        return [_jsonable(v) for v in val]
    if isinstance(val, dict):
        return {k: _jsonable(v) for k, v in val.items()}
    # pydantic 모델(symmetry 등): dict 로 덤프 시도
    for attr in ("model_dump", "dict", "as_dict"):
        method = getattr(val, attr, None)
        if callable(method):
            try:
                return _jsonable(method())
            except Exception:  # noqa: BLE001
                break
    return str(val)
