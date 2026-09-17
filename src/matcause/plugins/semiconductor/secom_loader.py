"""SECOM 로더 — CSV 로드/전처리/라벨정렬/불균형 처리 (T-120, US-C1).

SECOM: 1567 records x 590 anonymized features, Pass/Fail(-1/+1), ~104 fail (약 1:14).

이 모듈이 책임지는 것:
  1. `data/secom/secom.csv` 로드 (download_secom.py 산출물: label, timestamp,
     feature_000 ... feature_589).
  2. 결측 처리: 전부/거의 결측이거나 상수(분산 0)인 무의미 컬럼 제거,
     남은 결측은 중앙값(median)으로 대치.
  3. 라벨 정렬: 원본 -1(pass)/+1(fail) → 0(pass)/1(fail) 로 통일.
  4. 클래스 불균형(약 1:14) 처리 전략 산출:
       - class_weight="balanced" 용 가중치 dict
       - (옵션) SMOTE 오버샘플링된 (X, y)
     어떤 방법을 썼는지 메타데이터에 기록한다(데이터 정직성).

무거운 ML 라이브러리(imbalanced-learn)는 SMOTE 를 실제로 요청할 때만 import 한다.
통계 경로(T-121)만 쓰는 축소 시나리오에서는 pandas/numpy 만으로 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# SECOM 원본 라벨 규약
_RAW_PASS = -1  # pass
_RAW_FAIL = 1   # fail
# 정규화 라벨 (0=pass, 1=fail): scikit-learn 관례상 소수 클래스(fail)를 1(양성)로.
LABEL_PASS = 0
LABEL_FAIL = 1


@dataclass
class SecomData:
    """전처리를 마친 SECOM 데이터 묶음.

    X: (n_samples, n_features) 전처리된 피처 프레임 (결측 대치 완료).
    y: (n_samples,) 정규화 라벨 (0=pass, 1=fail).
    feature_names: 살아남은 피처 컬럼명 리스트.
    class_weight: {0: w0, 1: w1} — class_weight="balanced" 등가 가중치.
    meta: 전처리 과정에서 남긴 설명/통계 (근거·리포트용).
    """

    X: pd.DataFrame
    y: pd.Series
    feature_names: list[str]
    class_weight: dict[int, float]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_pass(self) -> int:
        return int((self.y == LABEL_PASS).sum())

    @property
    def n_fail(self) -> int:
        return int((self.y == LABEL_FAIL).sum())

    def imbalance_ratio(self) -> float:
        """다수:소수 비율 (예: 14.07 이면 약 1:14)."""
        return (self.n_pass / self.n_fail) if self.n_fail else float("inf")

    def pass_fail_frames(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """통계 검정용으로 그룹을 분리해 (pass_X, fail_X) 로 반환."""
        return (
            self.X[self.y == LABEL_PASS],
            self.X[self.y == LABEL_FAIL],
        )


class SecomLoader:
    """SECOM CSV 를 로드/전처리한다.

    사용:
        loader = SecomLoader("data/secom")
        data = loader.load()                 # SecomData
        Xr, yr, note = loader.resample(data) # (옵션) SMOTE 균형화
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        filename: str = "secom.csv",
        max_missing_frac: float = 0.5,
        impute_strategy: str = "median",
    ) -> None:
        self._data_dir = Path(data_dir)
        self._filename = filename
        # 결측 비율이 이 값을 넘는 컬럼은 신뢰할 수 없다고 보고 제거.
        self._max_missing_frac = max_missing_frac
        self._impute_strategy = impute_strategy

    @property
    def csv_path(self) -> Path:
        return self._data_dir / self._filename

    # ── 로드/전처리 ────────────────────────────────────────────────
    def load(self) -> SecomData:
        path = self.csv_path
        if not path.exists():
            raise FileNotFoundError(
                f"SECOM CSV 가 없습니다: {path}\n"
                "먼저 `python scripts/download_secom.py` 로 데이터를 확보하세요."
            )

        df = pd.read_csv(path)
        if "label" not in df.columns:
            raise ValueError(f"'label' 컬럼이 없습니다. 컬럼: {list(df.columns)[:8]}")

        y_raw = df["label"]
        feature_cols = [c for c in df.columns if str(c).startswith("feature_")]
        if not feature_cols:
            raise ValueError("feature_* 컬럼을 찾지 못했습니다.")
        X_raw = df[feature_cols].apply(pd.to_numeric, errors="coerce")

        n0_features = X_raw.shape[1]

        # (a) 무의미 컬럼 제거: 결측 과다 or 상수(분산 0)
        na_frac = X_raw.isna().mean()
        nunique = X_raw.nunique(dropna=True)
        drop_missing = na_frac[na_frac > self._max_missing_frac].index.tolist()
        drop_constant = nunique[nunique <= 1].index.tolist()
        drop_cols = sorted(set(drop_missing) | set(drop_constant))
        X = X_raw.drop(columns=drop_cols)

        # (b) 남은 결측 대치
        if self._impute_strategy == "median":
            fill = X.median(numeric_only=True)
        elif self._impute_strategy == "mean":
            fill = X.mean(numeric_only=True)
        else:
            raise ValueError(f"지원하지 않는 impute_strategy: {self._impute_strategy}")
        n_imputed = int(X.isna().sum().sum())
        X = X.fillna(fill)
        # 대치 후에도 남는 NaN(전부 결측이라 fill 값이 NaN인 극단 케이스) → 0
        X = X.fillna(0.0)

        kept_features = list(X.columns)

        # (c) 라벨 정규화 -1/+1 → 0/1
        y = self._normalize_labels(y_raw)

        # 인덱스 정리 (그룹 분리 시 정렬 안정성)
        X = X.reset_index(drop=True)
        y = y.reset_index(drop=True)

        # (d) 불균형 가중치 계산 (class_weight="balanced" 등가)
        class_weight = self._balanced_class_weight(y)

        n_pass = int((y == LABEL_PASS).sum())
        n_fail = int((y == LABEL_FAIL).sum())
        meta = {
            "csv_path": str(path),
            "n_samples": int(len(y)),
            "n_features_original": n0_features,
            "n_features_kept": len(kept_features),
            "dropped_missing_cols": len(drop_missing),
            "dropped_constant_cols": len(drop_constant),
            "n_cells_imputed": n_imputed,
            "impute_strategy": self._impute_strategy,
            "max_missing_frac": self._max_missing_frac,
            "label_map": {f"{_RAW_PASS}": LABEL_PASS, f"{_RAW_FAIL}": LABEL_FAIL},
            "n_pass": n_pass,
            "n_fail": n_fail,
            "imbalance_ratio": round(n_pass / n_fail, 2) if n_fail else None,
            "imbalance_handling": (
                "class_weight='balanced' (기본). SMOTE 는 resample()로 옵션 제공."
            ),
            "class_weight": class_weight,
        }

        return SecomData(
            X=X,
            y=y,
            feature_names=kept_features,
            class_weight=class_weight,
            meta=meta,
        )

    # ── 불균형 처리 ────────────────────────────────────────────────
    @staticmethod
    def _normalize_labels(y_raw: pd.Series) -> pd.Series:
        """원본 -1/+1(또는 0/1)을 0(pass)/1(fail) 로 통일."""
        y_num = pd.to_numeric(y_raw, errors="coerce")
        uniq = set(pd.unique(y_num.dropna()))
        if uniq <= {_RAW_PASS, _RAW_FAIL}:
            mapping = {_RAW_PASS: LABEL_PASS, _RAW_FAIL: LABEL_FAIL}
        elif uniq <= {0, 1}:
            # 이미 0/1 형태 — 다수=pass 가정을 검증하지 않고 그대로 사용
            mapping = {0: 0, 1: 1}
        else:
            raise ValueError(f"예상치 못한 라벨 값: {sorted(uniq)} (기대: -1/+1 또는 0/1)")
        return y_num.map(mapping).astype("int64").rename("label")

    @staticmethod
    def _balanced_class_weight(y: pd.Series) -> dict[int, float]:
        """sklearn 의 class_weight='balanced' 와 동일한 가중치.

        w_c = n_samples / (n_classes * count_c)
        """
        counts = y.value_counts().to_dict()
        n = len(y)
        k = len(counts)
        return {int(c): round(n / (k * cnt), 4) for c, cnt in counts.items()}

    def resample(
        self, data: SecomData, *, method: str = "smote", random_state: int = 42
    ) -> tuple[pd.DataFrame, pd.Series, str]:
        """소수 클래스(fail)를 오버샘플링해 균형 데이터를 만든다 (옵션).

        통계 검정(T-121)은 원본 분포로 하는 게 정석이므로 기본 경로가 아니며,
        ML 모델 학습(T-122 이후)이나 시각화용으로 필요할 때만 호출한다.
        반환: (X_res, y_res, note)  note 는 어떤 방법을 썼는지 설명.
        """
        if method != "smote":
            raise ValueError(f"지원하지 않는 resample method: {method}")
        try:
            from imblearn.over_sampling import SMOTE
        except ImportError as exc:  # noqa: BLE001
            raise RuntimeError(
                "SMOTE 를 쓰려면 imbalanced-learn 이 필요합니다: "
                "pip install \".[process]\""
            ) from exc

        n_fail = data.n_fail
        # SMOTE 는 k_neighbors < 소수 클래스 표본 수 여야 함
        k = min(5, max(1, n_fail - 1))
        sm = SMOTE(random_state=random_state, k_neighbors=k)
        X_res, y_res = sm.fit_resample(data.X, data.y)
        note = (
            f"SMOTE(k_neighbors={k}) 적용: fail {n_fail} → "
            f"{int((y_res == LABEL_FAIL).sum())} 로 오버샘플링 "
            f"(총 {len(y_res)} 샘플, 균형화)."
        )
        return X_res, pd.Series(y_res, name="label"), note
