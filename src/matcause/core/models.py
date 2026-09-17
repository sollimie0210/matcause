"""공통 데이터 모델 (T-004, 확정).

코어와 도메인 플러그인이 주고받는 모든 데이터의 계약(contract)이다.
design.md 6절 기준. 모든 근거는 Evidence 로 흐르며(추적성), 값이 없으면
note 에 명시한다(데이터 정직성). 필드 검증으로 잘못된 값을 조기에 차단한다.

이 모듈은 순수 데이터 정의만 포함한다 (도메인 지식/외부 SDK 의존 없음).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    """짧고 사람이 읽기 쉬운 접두사 기반 ID."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ─────────────────────────── 열거형 ───────────────────────────


class TriageCategory(str, Enum):
    MATERIAL = "MATERIAL"
    PROCESS = "PROCESS"
    AMBIGUOUS = "AMBIGUOUS"


class EvidenceSource(str, Enum):
    MP = "MP"
    SECOM = "SECOM"
    LITERATURE = "LITERATURE"
    FEEDBACK = "FEEDBACK"


class ReportFormat(str, Enum):
    GAP = "GAP"
    OCAP = "OCAP"
    CUSTOMER = "CUSTOMER"   # 고객사 제출용(근거 ID 없이 요약 중심)


class DiagnosisStatus(str, Enum):
    """진단 수명주기 상태 (Orchestrator/UI 가 공유)."""

    PENDING = "PENDING"          # 접수됨, 아직 분류 전
    TRIAGED = "TRIAGED"          # 분류 완료
    ANALYZING = "ANALYZING"      # 도메인 분석 진행 중
    REPORTED = "REPORTED"        # 리포트 생성 완료
    FAILED = "FAILED"            # 오류로 중단


class FeedbackAction(str, Enum):
    APPROVE = "APPROVE"
    CORRECT = "CORRECT"
    REJECT = "REJECT"


# ─────────────────────────── 근거 ───────────────────────────


class Evidence(BaseModel):
    """모든 근거의 단위. 값이 없으면 note 에 '없음'을 명시한다 (데이터 정직성).

    추적성(US-D2): 리포트의 각 주장은 Evidence.id 로 원본과 연결된다.
    """

    id: str = Field(default_factory=lambda: _new_id("ev"))
    source_type: EvidenceSource
    source_ref: str | None = None  # 예: mp-id, SECOM 변수명, 문헌 DOI
    value: Any | None = None
    unit: str | None = None
    note: str | None = None
    url: str | None = None

    @classmethod
    def missing(cls, source_type: EvidenceSource, source_ref: str, why: str) -> "Evidence":
        """확보하지 못한 지표를 정직하게 표기하는 헬퍼."""
        return cls(source_type=source_type, source_ref=source_ref, value=None, note=f"없음: {why}")


# ─────────────────────────── 입력 ───────────────────────────


class Attachment(BaseModel):
    filename: str
    content_type: str | None = None
    extracted_text: str | None = None


class IssueRequest(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("iss"))
    raw_text: str
    attachments: list[Attachment] = Field(default_factory=list)
    parsed_specs: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)

    @field_validator("raw_text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        # US-A1.3: 빈 입력은 거부
        if v is None or not v.strip():
            raise ValueError("이슈 텍스트가 비어 있습니다")
        return v

    def combined_text(self) -> str:
        """원문 + 첨부에서 추출한 텍스트를 하나로 합친다 (US-A1.2)."""
        parts = [self.raw_text]
        parts += [a.extracted_text for a in self.attachments if a.extracted_text]
        return "\n\n".join(parts)


# ─────────────────────────── Triage ───────────────────────────


class TriageResult(BaseModel):
    category: TriageCategory
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    signals: dict[str, Any] = Field(default_factory=dict)

    def is_ambiguous(self) -> bool:
        return self.category is TriageCategory.AMBIGUOUS


# ─────────────────────────── 물성 추출 (T-111) ───────────────────────────


class MaterialExtraction(BaseModel):
    """이슈 텍스트에서 뽑아낸 소재 식별 정보.

    소재 분석기(T-114)가 이 결과의 formulas 를 MP 조회에 사용한다.
    method 는 근거 출처("regex" | "llm" | "regex+llm")를 표기한다.
    """

    formulas: list[str] = Field(default_factory=list)   # 예: ["GaN", "Al2O3"]
    material_names: list[str] = Field(default_factory=list)  # 예: ["sapphire"]
    material_group: str | None = None  # 예: "III-V", "oxide", "nitride"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    method: str = "none"
    rationale: str = ""

    def has_result(self) -> bool:
        return bool(self.formulas or self.material_names)

    def primary_formula(self) -> str | None:
        return self.formulas[0] if self.formulas else None


# ─────────────────────────── 분석 결과 ───────────────────────────


class RankedCandidate(BaseModel):
    name: str
    score: float
    metrics: dict[str, Any] = Field(default_factory=dict)
    improvement: str | None = None
    tradeoffs: str | None = None
    evidences: list[Evidence] = Field(default_factory=list)


class MaterialFinding(BaseModel):
    risk_score: float = Field(ge=0.0, le=100.0)
    breakdown: dict[str, float] = Field(default_factory=dict)
    evidences: list[Evidence] = Field(default_factory=list)
    ranked_candidates: list[RankedCandidate] = Field(default_factory=list)
    summary: str = ""


class ProcessFinding(BaseModel):
    anomalous_vars: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    evidences: list[Evidence] = Field(default_factory=list)
    # 변수 -> 원인 설명. 매핑이 없으면 값에 '미매핑'을 넣어 정직하게 표기 (US-C2).
    cause_mappings: dict[str, str] = Field(default_factory=dict)
    summary: str = ""


# 두 경로의 Finding 을 함께 다루기 위한 별칭
Finding = MaterialFinding | ProcessFinding


# ─────────────────────────── 리포트 ───────────────────────────


class Report(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("rep"))
    cause: str
    evidences: list[Evidence] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    recommended_experiments: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    format: ReportFormat = ReportFormat.OCAP
    markdown: str = ""
    created_at: datetime = Field(default_factory=_now)


# ─────────────────────────── 피드백 ───────────────────────────


class Feedback(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("fb"))
    diagnosis_id: str
    action: FeedbackAction = FeedbackAction.CORRECT
    field: str | None = None
    original: str | None = None
    corrected: str | None = None
    reason: str | None = None
    created_at: datetime = Field(default_factory=_now)


# ─────────────────────────── 진단 집합체 ───────────────────────────


class Diagnosis(BaseModel):
    """하나의 이슈에 대한 진단 전 과정을 담는 집합체.

    Orchestrator 가 채우고, API/UI 가 상태와 결과를 조회한다.
    material_finding / process_finding 중 실행된 경로만 채워진다.
    """

    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(default_factory=lambda: _new_id("dx"))
    issue: IssueRequest
    status: DiagnosisStatus = DiagnosisStatus.PENDING
    triage: TriageResult | None = None
    material_finding: MaterialFinding | None = None
    process_finding: ProcessFinding | None = None
    report: Report | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def touch(self, status: DiagnosisStatus | None = None) -> None:
        if status is not None:
            self.status = status
        self.updated_at = _now()

    def all_evidences(self) -> list[Evidence]:
        """실행된 경로에서 수집된 모든 근거를 모은다 (추적성)."""
        out: list[Evidence] = []
        if self.material_finding:
            out += self.material_finding.evidences
            for c in self.material_finding.ranked_candidates:
                out += c.evidences
        if self.process_finding:
            out += self.process_finding.evidences
        if self.report:
            out += self.report.evidences
        return out
