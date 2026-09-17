"""데모용 Materials Project 조회 캐시 스냅샷 생성 (T-130).

네트워크/키 없이도 소재 경로 데모가 동작하도록, 데모 시나리오가 실제로 조회하는
모든 MP 요청을 라이브로 미리 실행해 data/cache 에 저장한다. 오프라인 모드
(OFFLINE_MODE=true)에서 동일 결과가 재현된다.

warming 은 런타임 파이프라인과 정확히 같은 조회를 수행하므로 캐시 키가 100% 일치한다:
  1. 이슈 텍스트 -> 화학식/물질군 추출 (T-111)
  2. query_summary(primary)             -> summary_* 캐시
  3. query_summary(group shortlist 후보) -> 각 후보 summary_* 캐시
  4. find_alternatives(primary)         -> alt_* 캐시

합성 없이 실제 MP 값만 저장한다.

사용법:
  python scripts/warm_mp_cache.py            # 온라인 1회(.env MP_API_KEY)
  python scripts/warm_mp_cache.py --verify   # 오프라인 재현 검증
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

try:
    from dotenv import load_dotenv

    load_dotenv()
    from matcause.core.config import get_settings as _gs

    _key = _gs().mp_api_key
    if _key and not os.environ.get("MP_API_KEY"):
        os.environ["MP_API_KEY"] = _key
except Exception:  # noqa: BLE001
    pass

from matcause.core.config import get_settings
from matcause.core.llm.mock_client import MockLLMClient
from matcause.plugins.semiconductor.alternatives_ranker import (
    candidate_formulas_for_group,
)
from matcause.plugins.semiconductor.material_extractor import extract_materials
from matcause.plugins.semiconductor.mp_connector import MpConnector, MpConnectorError

DEMO_ISSUES = [
    "고객사에서 GaN 기반 파워 소자의 특정 로트에서 누설전류가 규격 상한을 초과했다는 "
    "클레임이 접수됨. 동일 공정 조건에서 생산됐으나 소재 물성 편차가 의심됨.",
    "GaAs 기반 파워 소자(고전압 인버터)에서 누설전류가 규격을 초과함. 소재 물성 적합성 의심.",
    "SiC 웨이퍼 기반 파워 소자에서 특성 이상 발생, 소재 물성 검토 필요.",
]


def _collect_formulas(issues, llm):
    primaries = []
    candidates = set()
    for text in issues:
        ext = extract_materials(text, llm=llm)
        pf = ext.primary_formula()
        if pf:
            primaries.append(pf)
            for c in candidate_formulas_for_group(ext.material_group, exclude=pf):
                candidates.add(c)
    for p in primaries:
        candidates.add(p)
    return primaries, sorted(candidates)


def warm(offline):
    s = get_settings()
    conn = MpConnector(api_key=s.mp_api_key, cache_dir=s.mp_cache_dir, offline=offline)
    llm = MockLLMClient()

    primaries, all_formulas = _collect_formulas(DEMO_ISSUES, llm)
    print("primary:", primaries)
    print("summary formulas (%d):" % len(all_formulas), all_formulas)
    print("cache_dir:", s.mp_cache_dir, "offline:", offline)
    print("-" * 60)

    ok = 0
    fail = 0
    for f in all_formulas:
        try:
            r = conn.query_summary(f)
            best = r.get("best") or {}
            print("[summary] %6s -> %s best=%s E_hull=%s bg=%s" % (
                f, r.get("source"), best.get("material_id"),
                best.get("energy_above_hull"), best.get("band_gap")))
            ok += 1
        except MpConnectorError as exc:
            print("[summary] %6s -> FAIL: %s" % (f, exc))
            fail += 1

    for p in primaries:
        try:
            alts = conn.find_alternatives(p, k=5)
            print("[alt]     %6s -> %d cands (chemsys)" % (p, len(alts)))
            ok += 1
        except MpConnectorError as exc:
            print("[alt]     %6s -> FAIL: %s" % (p, exc))
            fail += 1

    print("-" * 60)
    print("done: ok=%d fail=%d" % (ok, fail))
    return 0 if fail == 0 else 1


def main():
    if "--verify" in sys.argv:
        print("=== OFFLINE reproduce verify ===")
        return warm(offline=True)
    print("=== ONLINE cache warm ===")
    rc = warm(offline=False)
    if rc == 0:
        print("\nverify offline: python scripts/warm_mp_cache.py --verify")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
