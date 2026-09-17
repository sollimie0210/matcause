"""공정 분석기 — 공정 경로(3-B) end-to-end 조립 (T-122, US-C1/C2).

ProcessAnalyzer Protocol 구현. 소재 분석기(T-114)와 동일한 방식으로:
  1. SECOM 로드/전처리/불균형 처리 (T-120, SecomLoader)
  2. Pass/Fail 이상 변수 규명 (T-121, identify_anomalous_vars)
  3. 결과를 ProcessFinding + Evidence(source_type=SECOM) 로 래핑 (추적성, US-D2)

SECOM 변수는 익명화되어 있어 물리 원인 직접 매핑이 불가능하다. 변수→원인 매핑
테이블(T-202, secom_mapping.yaml)이 주입되면 사용하고, 없으면 각 변수 원인을
'미매핑(통계 이상만 확인)'으로 정직하게 표기한다(US-C2).

데이터가 없거나 로드 실패 시에도 합성하지 않고 정직한 빈/부분 결과를 반환한다.
"""

from __future__ import annotations

from matcause.core.models import (
    Evidence,
    EvidenceSource,
    IssueRequest,
    ProcessFinding,
)

from .secom_loader import SecomLoader
from .secom_stats import AnomalyReport, identify_anomalous_vars

# 매핑이 없을 때 표기하는 정직 문구 (US-C2)
_UNMAPPED = "미매핑(통계 이상만 확인, 물리 원인은 변수 익명화로 직접 규명 불가)"


class SecomProcessAnalyzer:
    """SECOM 기반 공정 이상 변수 분석기.

    loader: SecomLoader (미지정 시 data_dir 로 생성).
    mapping: {feature_name: 원인설명} 형태 변수→원인 매핑(T-202). 없으면 미매핑 표기.
    """

    def __init__(
        self,
        loader: SecomLoader | None = None,
        mapping: dict[str, str] | None = None,
        *,
        data_dir: str = "data/secom",
        q: float = 0.05,
        top_n: int = 20,
    ) -> None:
        self._loader = loader or SecomLoader(data_dir)
        self._mapping = mapping or {}
        self._q = q
        self._top_n = top_n

    def analyze(self, issue: IssueRequest) -> ProcessFinding:
        # 1) 로드/전처리/불균형 처리
        try:
            data = self._loader.load()
        except FileNotFoundError as exc:
            return ProcessFinding(
                anomalous_vars=[],
                evidences=[Evidence.missing(EvidenceSource.SECOM, "secom.csv", str(exc))],
                summary="SECOM 데이터가 없어 공정 분석을 수행할 수 없습니다.",
            )
        except Exception as exc:  # noqa: BLE001
            return ProcessFinding(
                anomalous_vars=[],
                evidences=[
                    Evidence.missing(EvidenceSource.SECOM, "secom.csv", f"로드 실패: {exc}")
                ],
                summary=f"SECOM 로드 중 오류가 발생했습니다: {exc}",
            )

        # 2) 이상 변수 규명 (통계 + FDR)
        report: AnomalyReport = identify_anomalous_vars(
            data, q=self._q, top_n=self._top_n
        )

        # 3) Evidence 래핑 (추적성)
        evidences: list[Evidence] = []

        # (a) 데이터셋/전처리/불균형 근거
        m = data.meta
        evidences.append(
            Evidence(
                source_type=EvidenceSource.SECOM,
                source_ref="dataset",
                value=f"{m['n_samples']} rows × {m['n_features_kept']} feat",
                note=(
                    f"원본 {m['n_features_original']}개 중 무의미 컬럼 "
                    f"{m['dropped_missing_cols'] + m['dropped_constant_cols']}개 제거, "
                    f"결측 {m['n_cells_imputed']}셀 {m['impute_strategy']} 대치"
                ),
            )
        )
        evidences.append(
            Evidence(
                source_type=EvidenceSource.SECOM,
                source_ref="class_balance",
                value=f"pass {m['n_pass']} / fail {m['n_fail']}",
                note=(
                    f"클래스 불균형 약 1:{m['imbalance_ratio']}. "
                    f"처리: {m['imbalance_handling']} class_weight={m['class_weight']}"
                ),
            )
        )
        evidences.append(
            Evidence(
                source_type=EvidenceSource.SECOM,
                source_ref="method",
                value=report.meta["test"],
                note=(
                    f"다중검정 보정 {report.meta['fdr_method']}(q={report.meta['q']}); "
                    f"{report.meta['n_features_tested']}개 검정 → 유의 "
                    f"{report.meta['n_significant']}개. {report.meta['caveat']}"
                ),
            )
        )

        # (b) 상위 이상 변수별 근거 + 원인 매핑
        cause_mappings: dict[str, str] = {}
        for r in report.top:
            cause = self._mapping.get(r.feature, _UNMAPPED)
            cause_mappings[r.feature] = cause
            direction_kr = "불량군에서 높음" if r.direction == "higher_in_fail" else "불량군에서 낮음"
            evidences.append(
                Evidence(
                    source_type=EvidenceSource.SECOM,
                    source_ref=r.feature,
                    value=f"p_adj={r.p_adj:.2e}, d={r.cohens_d:.3f}",
                    note=(
                        f"{direction_kr} (pass 평균 {r.mean_pass:.4g} → "
                        f"fail 평균 {r.mean_fail:.4g}). 원인: {cause}"
                    ),
                )
            )

        # 유의하지만 상위 N 밖인 나머지 변수도 anomalous_vars 에는 포함(원인은 매핑만)
        for r in report.significant:
            if r.feature not in cause_mappings:
                cause_mappings[r.feature] = self._mapping.get(r.feature, _UNMAPPED)

        anomalous_vars = report.significant_names()

        # 4) 통계 요약(stats) — UI/리포트에서 활용
        stats = {
            "n_features_tested": report.meta["n_features_tested"],
            "n_significant": report.n_significant,
            "fdr_q": report.meta["q"],
            "test": report.meta["test"],
            "fdr_method": report.meta["fdr_method"],
            "n_pass": data.n_pass,
            "n_fail": data.n_fail,
            "imbalance_ratio": m["imbalance_ratio"],
            "class_weight": m["class_weight"],
            "top_vars": [
                {
                    "feature": r.feature,
                    "p_adj": r.p_adj,
                    "cohens_d": r.cohens_d,
                    "direction": r.direction,
                }
                for r in report.top
            ],
        }

        n_mapped = sum(1 for v in cause_mappings.values() if v != _UNMAPPED)
        mapping_note = (
            f"{n_mapped}/{len(cause_mappings)}개 변수만 원인 매핑됨"
            if n_mapped
            else "모든 변수 원인 미매핑(변수 익명화)"
        )
        summary = (
            f"SECOM Pass/Fail {data.n_pass}:{data.n_fail}(약 1:{m['imbalance_ratio']}) "
            f"그룹 검정에서 유의 이상 변수 {report.n_significant}개 규명 "
            f"(FDR q={report.meta['q']}). 효과크기 상위: "
            f"{', '.join(report.top_names()[:5])}. {mapping_note}."
        )

        return ProcessFinding(
            anomalous_vars=anomalous_vars,
            stats=stats,
            evidences=evidences,
            cause_mappings=cause_mappings,
            summary=summary,
        )
