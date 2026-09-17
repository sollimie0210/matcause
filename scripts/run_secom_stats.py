"""T-120/T-121 실데이터 검증 러너.

SECOM 실데이터를 로드(T-120)하고 Pass/Fail 그룹 이상 변수를 규명(T-121)해
결과를 요약 출력한다. 불균형 처리(class_weight, SMOTE)도 함께 점검한다.

사용: python scripts/run_secom_stats.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# src 를 import 경로에 추가 (pyproject 의 pythonpath=src 와 동일 효과)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matcause.plugins.semiconductor.secom_loader import SecomLoader
from matcause.plugins.semiconductor.secom_stats import identify_anomalous_vars


def main() -> int:
    loader = SecomLoader(ROOT / "data" / "secom")
    data = loader.load()

    print("=" * 64)
    print("[T-120] SECOM 로드/전처리")
    print("=" * 64)
    m = data.meta
    print(f"  샘플 수            : {m['n_samples']}")
    print(f"  원본 피처          : {m['n_features_original']}")
    print(f"  전처리 후 피처      : {m['n_features_kept']} "
          f"(결측과다 {m['dropped_missing_cols']} + 상수 {m['dropped_constant_cols']} 제거)")
    print(f"  결측 대치 셀 수     : {m['n_cells_imputed']} ({m['impute_strategy']})")
    print(f"  라벨 분포          : pass(0)={m['n_pass']}, fail(1)={m['n_fail']}")
    print(f"  불균형 비율        : 약 1:{m['imbalance_ratio']}")
    print(f"  class_weight       : {m['class_weight']}")

    # SMOTE 옵션 점검 (통계 검정엔 안 쓰지만 불균형 처리 경로 검증)
    try:
        Xr, yr, note = loader.resample(data, method="smote")
        print(f"  SMOTE 검증         : {note}")
    except Exception as exc:  # noqa: BLE001
        print(f"  SMOTE 검증         : 실패({exc})")

    print()
    print("=" * 64)
    print("[T-121] Pass/Fail 이상 변수 규명 (Welch t + Mann-Whitney, BH-FDR q=0.05)")
    print("=" * 64)
    report = identify_anomalous_vars(data, q=0.05, top_n=20)
    rm = report.meta
    print(f"  검정 피처 수        : {rm['n_features_tested']}")
    print(f"  유의 이상 변수 수    : {rm['n_significant']}  (FDR q={rm['q']})")
    print()
    print(f"  ▶ 유의 이상 변수 전체 목록 ({report.n_significant}개):")
    print("   ", ", ".join(report.significant_names()))
    print()
    print(f"  ▶ 효과크기 상위 {len(report.top)}개 대표 이상 변수:")
    print(f"    {'변수':<14} {'p_adj':>10} {'Cohen d':>9} {'평균(pass)':>12} "
          f"{'평균(fail)':>12}  방향")
    for r in report.top:
        print(f"    {r.feature:<14} {r.p_adj:>10.2e} {r.cohens_d:>9.3f} "
              f"{r.mean_pass:>12.4g} {r.mean_fail:>12.4g}  {r.direction}")

    print()
    print(f"  주의: {rm['caveat']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
