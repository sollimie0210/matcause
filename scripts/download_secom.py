"""UCI SECOM 실데이터 다운로드 스크립트 (T-003).

SECOM: 1567 records x 590 features, Pass/Fail(-1/+1) 라벨.
실행: python scripts/download_secom.py
스캐폴드 단계에서는 다운로드 URL/로직 골격만 둔다 (T-003에서 완성).
"""

from __future__ import annotations

# UCI ML Repository SECOM:
#   http://archive.ics.uci.edu/ml/datasets/SECOM
# 원본 파일: secom.data (feature), secom_labels.data (label + timestamp)


def main() -> None:
    raise NotImplementedError("T-003에서 구현: UCI에서 secom.data / secom_labels.data 확보")


if __name__ == "__main__":
    main()
