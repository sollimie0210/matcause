"""UCI SECOM 실데이터 다운로드 스크립트 (T-003).

SECOM: 1567 records x 590 features, Pass/Fail(-1/+1) 라벨 + 타임스탬프.
  -1 = pass, +1 = fail. 결측치 존재(원본은 'NaN' 표기).

`ucimlrepo` 패키지로 확보한다(직접 URL 다운로드보다 안정적: 미러/리다이렉트/포맷
변경에 견고하고 pandas DataFrame 으로 바로 받는다).

  from ucimlrepo import fetch_ucirepo
  secom = fetch_ucirepo(id=179)
  X = secom.data.features   # 1567 x 590
  y = secom.data.targets    # 1567 x 1 (label)

출처/라이선스: McCann, M. & Johnston, A. (2008). SECOM [Dataset]. UCI Machine
Learning Repository. https://doi.org/10.24432/C54305 — CC BY 4.0.

사용법:
  python scripts/download_secom.py            # 다운로드 + CSV 생성
  python scripts/download_secom.py --force    # 이미 있어도 다시 받기
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# 리포지토리 루트 기준 data/secom
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "secom"

UCI_SECOM_ID = 179
N_FEATURES = 590   # feature 개수 (라벨/타임스탬프 제외)
N_ROWS = 1567

# 원본 라벨/타임스탬프에 자주 쓰이는 컬럼명 후보 (ucimlrepo 버전차 대비)
_LABEL_CANDIDATES = ("label", "Pass/Fail", "class", "target")
_TIME_CANDIDATES = ("timestamp", "Time", "time", "date", "Date")

# SECOM(id=179)에서 feature 컬럼은 'Attribute 1' ... 'Attribute 590' 형태.
def _is_feature_col(name: str) -> bool:
    return str(name).lower().startswith("attribute")


def _fetch():
    """ucimlrepo 로 SECOM 을 가져온다. 미설치면 안내 후 종료."""
    try:
        from ucimlrepo import fetch_ucirepo
    except ImportError as exc:  # noqa: BLE001
        raise SystemExit(
            "ucimlrepo 가 설치돼 있지 않습니다. 먼저 설치하세요:\n"
            "  pip install ucimlrepo\n"
            f"(원인: {exc})"
        ) from exc

    print(f"[fetch] ucimlrepo fetch_ucirepo(id={UCI_SECOM_ID}) ...")
    return fetch_ucirepo(id=UCI_SECOM_ID)


def _pick_column(df, candidates: tuple[str, ...]):
    """df 컬럼 중 candidates(대소문자 무시)와 일치하는 첫 컬럼명을 반환."""
    lower = {str(c).lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _get_data_attr(data, name: str):
    """secom.data 에서 속성/딕셔너리 키 어느 쪽으로 오든 안전하게 값을 얻는다.

    ucimlrepo 버전에 따라 data 가 객체(.features)일 수도, dict('features') 일
    수도 있다. SECOM(id=179)의 경우 features/targets 는 None 이고 original 만
    채워져 있는 것으로 관찰됐다.
    """
    val = getattr(data, name, None)
    if val is None and hasattr(data, "get"):
        try:
            val = data.get(name)
        except Exception:  # noqa: BLE001
            val = None
    return val


def _build_frame(secom):
    """SECOM 데이터를 하나의 DataFrame 으로 정규화한다.

    반환 컬럼: label, timestamp(있으면), feature_000 ... feature_(N-1)

    ucimlrepo 가 features/targets 를 채워주면 그것을, 아니면 original 통합
    프레임(class/timestamp/Attribute N ...)을 사용한다.
    """
    import pandas as pd  # ucimlrepo 의존성으로 항상 존재

    data = secom.data
    features = _get_data_attr(data, "features")
    targets = _get_data_attr(data, "targets")
    original = _get_data_attr(data, "original")

    if features is not None and targets is not None:
        # 정상 경로: features/targets 가 분리 제공되는 경우
        features = features.reset_index(drop=True)
        targets = targets.reset_index(drop=True)

        label_col = _pick_column(targets, _LABEL_CANDIDATES) or targets.columns[0]
        label = targets[label_col].rename("label")

        timestamp = None
        ts_col = _pick_column(targets, _TIME_CANDIDATES)
        if ts_col is not None:
            timestamp = targets[ts_col].rename("timestamp")
        elif original is not None:
            ots = _pick_column(original, _TIME_CANDIDATES)
            if ots is not None:
                timestamp = original[ots].reset_index(drop=True).rename("timestamp")

        feat = features.copy()
    elif original is not None:
        # SECOM 실측 경로: original 만 채워져 있음
        original = original.reset_index(drop=True)

        label_col = _pick_column(original, _LABEL_CANDIDATES)
        if label_col is None:
            raise SystemExit(
                "original 프레임에서 라벨 컬럼을 찾지 못했습니다. "
                f"컬럼 예시: {list(original.columns)[:8]}"
            )
        label = original[label_col].rename("label")

        timestamp = None
        ts_col = _pick_column(original, _TIME_CANDIDATES)
        if ts_col is not None:
            timestamp = original[ts_col].rename("timestamp")

        # feature = 'Attribute N' 컬럼들. 없으면 라벨/타임스탬프를 제외한 나머지.
        feat_cols = [c for c in original.columns if _is_feature_col(c)]
        if not feat_cols:
            drop = {label_col} | ({ts_col} if ts_col else set())
            feat_cols = [c for c in original.columns if c not in drop]
        feat = original[feat_cols].copy()
    else:
        raise SystemExit(
            "ucimlrepo 가 features/targets/original 중 아무것도 반환하지 "
            "않았습니다. 반환 구조 변경 가능성을 확인하세요."
        )

    # feature 컬럼명을 안정적인 feature_### 로 재명명
    feat.columns = [f"feature_{i:03d}" for i in range(feat.shape[1])]

    parts = [label]
    if timestamp is not None:
        parts.append(timestamp)
    parts.append(feat)
    return pd.concat(parts, axis=1)


def main() -> int:
    force = "--force" in sys.argv
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = DATA_DIR / "secom.csv"

    if csv_path.exists() and not force:
        print(f"[skip] 이미 존재: {csv_path} (--force 로 재생성)")
        return 0

    secom = _fetch()
    print("[build] features + targets 통합 중...")
    df = _build_frame(secom)

    df.to_csv(csv_path, index=False, encoding="utf-8")
    n_rows = df.shape[0]
    n_feat = sum(1 for c in df.columns if str(c).startswith("feature_"))
    print(f"  saved -> {csv_path}")
    print(f"[done] rows={n_rows}, features={n_feat}")

    if n_rows != N_ROWS or n_feat != N_FEATURES:
        print(
            f"[warn] 예상({N_ROWS} x {N_FEATURES})과 다름. "
            "ucimlrepo 반환 구조 변경 가능성 확인 필요."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
