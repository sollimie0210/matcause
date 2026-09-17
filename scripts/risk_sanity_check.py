"""리스크 스코어 상식성 검증 (T-112 튜닝 확인).

잘 알려진 안정 화합물 여러 개를 실제 MP 에서 조회해 best 상의 리스크 점수를
계산한다. 안정 화합물은 리스크가 낮게(상식적으로) 나와야 한다.

사용법:
  $env:MP_API_KEY="..."
  python scripts/risk_sanity_check.py
  python scripts/risk_sanity_check.py Si Al2O3 GaN SiO2 TiO2   # 대상 지정
"""

from __future__ import annotations

import os
import sys

# Windows 콘솔(cp949)에서 한글/기호 출력이 깨지지 않도록 UTF-8 강제
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# .env 자동 로드 (환경변수에 없으면 .env 의 값을 사용)
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

from matcause.plugins.semiconductor.mp_connector import MpConnector
from matcause.plugins.semiconductor.risk_scorer import score_material

DEFAULT_FORMULAS = ["Si", "Al2O3", "GaN", "SiO2", "TiO2", "GaAs"]


def main() -> int:
    formulas = sys.argv[1:] or DEFAULT_FORMULAS
    api_key = os.environ.get("MP_API_KEY")
    if not api_key:
        print("MP_API_KEY 환경변수가 없습니다.", file=sys.stderr)
        return 2

    conn = MpConnector(api_key=api_key, cache_dir="data/cache")

    header = f"{'formula':>8} | {'mp-id':>14} | {'E_f/atom':>10} | {'E_hull':>9} | {'stable':>6} | {'risk':>5}"
    print(header)
    print("-" * len(header))

    rows = []
    for formula in formulas:
        try:
            result = conn.query_summary(formula)
        except Exception as exc:  # noqa: BLE001
            print(f"{formula:>8} | 조회 실패: {exc}")
            continue
        best = result.get("best")
        if not best:
            print(f"{formula:>8} | best 없음")
            continue
        r = score_material(best)
        rows.append((formula, best, r))
        print(
            f"{formula:>8} | {str(best.get('material_id')):>14} | "
            f"{best.get('formation_energy_per_atom'):>10.4f} | "
            f"{best.get('energy_above_hull'):>9.4f} | "
            f"{str(best.get('is_stable')):>6} | {r.score:>5.1f}"
        )

    print("-" * len(header))
    print("\n[상식성 판정] 안정 화합물(E_hull~0, stable=True)은 리스크가 낮아야 함:")
    for formula, best, r in rows:
        verdict = "OK(낮음)" if r.score < 20 else ("경계" if r.score < 50 else "높음(주의)")
        print(f"  {formula:>8}: risk={r.score:>5.1f}  breakdown={r.breakdown}  -> {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
