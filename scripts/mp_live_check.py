"""MP 라이브 조회 스모크 (T-110 검증용).

실제 MP_API_KEY 로 화합물 하나를 조회해서 formation_energy_per_atom,
energy_above_hull 값이 실제로 나오는지 확인한다.

사용법:
  $env:MP_API_KEY="..."
  python scripts/mp_live_check.py SiC
  python scripts/mp_live_check.py            # 기본값 SiC
"""

from __future__ import annotations

import json
import os
import sys

from matcause.plugins.semiconductor.mp_connector import MpConnector


def main() -> int:
    formula = sys.argv[1] if len(sys.argv) > 1 else "SiC"
    api_key = os.environ.get("MP_API_KEY")
    if not api_key:
        print("MP_API_KEY 환경변수가 없습니다. 먼저 키를 설정하세요.", file=sys.stderr)
        return 2

    conn = MpConnector(api_key=api_key, cache_dir="data/cache")
    result = conn.query_summary(formula)

    print(f"formula     : {result['formula']}")
    print(f"source      : {result['source']}")
    print(f"retrieved_at: {result.get('retrieved_at')}")
    print(f"# materials : {len(result['materials'])}")
    print(f"notes       : {result['notes']}")
    print("-" * 60)

    best = result.get("best")
    if best:
        print("가장 안정(best, energy_above_hull 최소):")
        print(json.dumps(best, ensure_ascii=False, indent=2))
    else:
        print("best 후보 없음 (energy_above_hull 값을 가진 항목 부재)")

    print("-" * 60)
    print("전체 후보 요약:")
    for m in result["materials"]:
        print(
            f"  {m.get('material_id'):>14}  {m.get('formula_pretty'):>8}  "
            f"E_f/atom={m.get('formation_energy_per_atom')}  "
            f"E_hull={m.get('energy_above_hull')}  "
            f"band_gap={m.get('band_gap')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
