"""이상 변수 규명(통계) — Pass/Fail 그룹 검정 + FDR 보정 (T-121, US-C1).

SECOM Pass(양품) vs Fail(불량) 두 그룹 간에 분포가 유의하게 다른 피처(이상 변수)를
통계적으로 찾아낸다. 590개 피처를 동시에 검정하므로 다중검정 보정(Benjamini-Hochberg
FDR)이 필수다. 익명 피처라 "왜"는 알 수 없고(원인 매핑은 T-202), 여기서는 "어떤
변수가 두 그룹을 유의하게 가르는가"까지를 정직하게 규명한다.

검정 설계:
  - 각 피처마다 Welch t-test(등분산 가정 X)와 Mann-Whitney U(비모수) 를 함께 계산.
  - 기본 판정은 Mann-Whitney p-value 사용(SECOM 피처는 비정규·이상치 많음).
  - Benjamini-Hochberg 로 FDR(기본 q=0.05) 보정 → 유의 피처 선정.
  - 효과크기(Cohen's d) 로 정렬해 상위 N 을 대표 이상 변수로 제시.

불균형(약 1:14) 대응: 그룹 검정 자체는 표본 수 차이에 강건하지만, Fail 표본이
104개로 작다는 점을 신뢰도 한계로 meta 에 명시한다. (오버샘플링은 통계 검정을
왜곡하므로 여기서는 원본 분포를 사용한다.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from .secom_loader import SecomData


@dataclass
class VarTestResult:
    """단일 피처에 대한 그룹 검정 결과."""

    feature: str
    p_ttest: float
    p_mannwhitney: float
    p_value: float          # 판정에 사용한 대표 p-value (기본: Mann-Whitney)
    p_adj: float            # BH-FDR 보정 p-value
    significant: bool
    cohens_d: float         # 효과크기 (부호: fail 평균 - pass 평균 방향)
    mean_pass: float
    mean_fail: float
    direction: str          # "higher_in_fail" | "lower_in_fail"

    def to_row(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "p_value": self.p_value,
            "p_adj": self.p_adj,
            "cohens_d": self.cohens_d,
            "mean_pass": self.mean_pass,
            "mean_fail": self.mean_fail,
            "direction": self.direction,
            "significant": self.significant,
        }


@dataclass
class AnomalyReport:
    """전체 이상 변수 규명 결과."""

    results: list[VarTestResult]          # 모든 피처 결과 (p_adj 오름차순 정렬)
    significant: list[VarTestResult]      # 유의 피처 (p_adj <= q)
    top: list[VarTestResult]              # 효과크기 상위 N (유의 피처 중)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_significant(self) -> int:
        return len(self.significant)

    def significant_names(self) -> list[str]:
        return [r.feature for r in self.significant]

    def top_names(self) -> list[str]:
        return [r.feature for r in self.top]

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([r.to_row() for r in self.results])


def _cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """b(fail) - a(pass) 방향의 Cohen's d (pooled SD).

    양수면 fail 그룹에서 값이 큼. SD 가 0 이면 0 반환.
    """
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    va, vb = a.var(ddof=1), b.var(ddof=1)
    pooled = ((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)
    sd = np.sqrt(pooled)
    if not np.isfinite(sd) or sd == 0:
        return 0.0
    return float((b.mean() - a.mean()) / sd)


def benjamini_hochberg(pvals: np.ndarray, q: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg FDR 보정.

    반환: (reject, p_adj)
      reject: bool 배열, 귀무가설 기각(=유의) 여부
      p_adj:  BH 보정 p-value (단조 증가 보정 적용)
    NaN p-value 는 유의하지 않은 것(p_adj=1.0)으로 처리한다.
    """
    p = np.asarray(pvals, dtype=float)
    n = p.size
    reject = np.zeros(n, dtype=bool)
    p_adj = np.ones(n, dtype=float)
    if n == 0:
        return reject, p_adj

    valid = np.isfinite(p)
    idx_valid = np.where(valid)[0]
    m = idx_valid.size
    if m == 0:
        return reject, p_adj

    pv = p[idx_valid]
    order = np.argsort(pv)
    ranked = pv[order]
    ranks = np.arange(1, m + 1)

    # 보정값: p * m / rank, 뒤에서부터 누적 최소(단조성 보장), 1로 클리핑
    adj_sorted = ranked * m / ranks
    adj_sorted = np.minimum.accumulate(adj_sorted[::-1])[::-1]
    adj_sorted = np.clip(adj_sorted, 0.0, 1.0)

    adj = np.empty(m, dtype=float)
    adj[order] = adj_sorted
    p_adj[idx_valid] = adj
    reject[idx_valid] = adj <= q
    return reject, p_adj


def identify_anomalous_vars(
    data: SecomData,
    *,
    q: float = 0.05,
    top_n: int = 20,
    decision: str = "mannwhitney",
    min_abs_d: float = 0.0,
) -> AnomalyReport:
    """Pass/Fail 그룹 검정으로 이상 변수를 규명한다.

    q:         FDR 목표 수준 (기본 0.05).
    top_n:     대표 이상 변수 개수 (효과크기 기준 상위).
    decision:  판정에 쓸 p-value 종류 ("mannwhitney" | "ttest").
    min_abs_d: 유의 판정에 추가로 요구할 최소 |Cohen's d| (0 이면 미적용).
    """
    if decision not in ("mannwhitney", "ttest"):
        raise ValueError("decision 은 'mannwhitney' 또는 'ttest' 여야 합니다.")

    pass_X, fail_X = data.pass_fail_frames()
    features = data.feature_names

    rows: list[dict[str, Any]] = []
    for f in features:
        a = pass_X[f].to_numpy(dtype=float)
        b = fail_X[f].to_numpy(dtype=float)

        # Welch t-test
        try:
            t_p = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit").pvalue
        except Exception:  # noqa: BLE001
            t_p = np.nan
        # Mann-Whitney U (양측)
        try:
            u_p = stats.mannwhitneyu(a, b, alternative="two-sided").pvalue
        except ValueError:
            # 두 그룹이 완전히 동일(타이) 등으로 검정 불가한 상수 피처
            u_p = np.nan

        d = _cohens_d(a, b)
        mean_p = float(np.nanmean(a)) if a.size else float("nan")
        mean_f = float(np.nanmean(b)) if b.size else float("nan")
        rows.append(
            {
                "feature": f,
                "p_ttest": float(t_p) if t_p == t_p else np.nan,
                "p_mw": float(u_p) if u_p == u_p else np.nan,
                "cohens_d": d,
                "mean_pass": mean_p,
                "mean_fail": mean_f,
            }
        )

    df = pd.DataFrame(rows)
    p_col = "p_mw" if decision == "mannwhitney" else "p_ttest"
    reject, p_adj = benjamini_hochberg(df[p_col].to_numpy(), q=q)
    df["p_value"] = df[p_col]
    df["p_adj"] = p_adj
    df["reject"] = reject
    if min_abs_d > 0:
        df["significant"] = df["reject"] & (df["cohens_d"].abs() >= min_abs_d)
    else:
        df["significant"] = df["reject"]

    # p_adj 오름차순, 동률이면 |d| 내림차순 정렬
    df = df.sort_values(
        by=["p_adj", "cohens_d"],
        key=lambda s: s.abs() if s.name == "cohens_d" else s,
        ascending=[True, False],
    ).reset_index(drop=True)

    results = [
        VarTestResult(
            feature=r["feature"],
            p_ttest=r["p_ttest"],
            p_mannwhitney=r["p_mw"],
            p_value=r["p_value"],
            p_adj=r["p_adj"],
            significant=bool(r["significant"]),
            cohens_d=r["cohens_d"],
            mean_pass=r["mean_pass"],
            mean_fail=r["mean_fail"],
            direction="higher_in_fail" if r["cohens_d"] >= 0 else "lower_in_fail",
        )
        for r in df.to_dict(orient="records")
    ]

    significant = [r for r in results if r.significant]
    # 대표 상위 N: 유의 피처를 효과크기 크기순으로
    top = sorted(significant, key=lambda r: abs(r.cohens_d), reverse=True)[:top_n]

    meta = {
        "test": f"Welch t-test + Mann-Whitney U (decision={decision})",
        "fdr_method": "Benjamini-Hochberg",
        "q": q,
        "n_features_tested": len(features),
        "n_significant": len(significant),
        "top_n": len(top),
        "min_abs_cohens_d": min_abs_d,
        "n_pass": data.n_pass,
        "n_fail": data.n_fail,
        "imbalance_ratio": data.meta.get("imbalance_ratio"),
        "caveat": (
            "Fail 표본이 적어(약 1:14 불균형) 검정력에 한계가 있음. "
            "SECOM 피처는 익명이라 통계 이상까지만 규명하며 물리 원인은 미매핑."
        ),
    }

    return AnomalyReport(results=results, significant=significant, top=top, meta=meta)
