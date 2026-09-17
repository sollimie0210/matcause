"""T-004 / T-005 계약 테스트.

- 데이터 모델 검증(빈 텍스트 거부, 범위 검증, ID 자동생성, Diagnosis 집합체)
- LLMClient Protocol: MockLLMClient / BedrockLLMClient 가 인터페이스를 만족
- MockLLMClient 결정론적 동작 (JSON, embed, 스크립트 응답)
"""

from __future__ import annotations

import pytest


# ── T-004: 모델 ──


def test_issue_rejects_blank_text():
    from matcause.core.models import IssueRequest

    with pytest.raises(ValueError):
        IssueRequest(raw_text="   ")


def test_ids_autogenerate_with_prefix():
    from matcause.core.models import IssueRequest, Report

    issue = IssueRequest(raw_text="누설전류 상승")
    report = Report(cause="soldering")
    assert issue.id.startswith("iss_")
    assert report.id.startswith("rep_")


def test_confidence_and_risk_range_validation():
    from matcause.core.models import MaterialFinding, TriageCategory, TriageResult

    with pytest.raises(ValueError):
        TriageResult(category=TriageCategory.MATERIAL, confidence=1.5, rationale="x")
    with pytest.raises(ValueError):
        MaterialFinding(risk_score=150)


def test_evidence_missing_helper():
    from matcause.core.models import Evidence, EvidenceSource

    ev = Evidence.missing(EvidenceSource.MP, "mp-149", "결함 형성 에너지 직접값 부재")
    assert ev.value is None
    assert ev.note and ev.note.startswith("없음")


def test_issue_combined_text_merges_attachments():
    from matcause.core.models import Attachment, IssueRequest

    issue = IssueRequest(
        raw_text="본문",
        attachments=[Attachment(filename="a.txt", extracted_text="첨부내용")],
    )
    combined = issue.combined_text()
    assert "본문" in combined and "첨부내용" in combined


def test_diagnosis_aggregates_evidences():
    from matcause.core.models import (
        Diagnosis,
        DiagnosisStatus,
        Evidence,
        EvidenceSource,
        IssueRequest,
        MaterialFinding,
    )

    issue = IssueRequest(raw_text="누설전류 상승")
    dx = Diagnosis(issue=issue)
    assert dx.status is DiagnosisStatus.PENDING
    dx.material_finding = MaterialFinding(
        risk_score=42.0,
        evidences=[Evidence(source_type=EvidenceSource.MP, source_ref="mp-149")],
    )
    dx.touch(DiagnosisStatus.REPORTED)
    assert dx.status is DiagnosisStatus.REPORTED
    assert len(dx.all_evidences()) == 1


# ── T-005: LLM 인터페이스 ──


def test_mock_and_bedrock_satisfy_llmclient_protocol():
    from matcause.core.llm.base import LLMClient
    from matcause.core.llm.bedrock_client import BedrockLLMClient
    from matcause.core.llm.mock_client import MockLLMClient

    mock = MockLLMClient()
    bedrock = BedrockLLMClient(region="us-east-1", model_id="anthropic.x")
    assert isinstance(mock, LLMClient)
    assert isinstance(bedrock, LLMClient)


def test_mock_complete_json_heuristic_and_scripted():
    from matcause.core.llm.base import user
    from matcause.core.llm.mock_client import MockLLMClient

    # 휴리스틱: 공정 키워드 우세 → PROCESS
    mock = MockLLMClient()
    out = mock.complete_json([user("공정 챔버 온도 이상으로 수율 저하")])
    assert out["category"] == "PROCESS"
    assert 0.0 <= out["confidence"] <= 1.0

    # 스크립트: 특정 부분 문자열에 고정 응답
    scripted = MockLLMClient(scripted_responses={"특수케이스": {"category": "MATERIAL", "confidence": 0.9, "rationale": "scripted"}})
    out2 = scripted.complete_json([user("이것은 특수케이스 입력")])
    assert out2["category"] == "MATERIAL" and out2["confidence"] == 0.9


def test_mock_embed_is_deterministic():
    from matcause.core.llm.mock_client import MockLLMClient

    mock = MockLLMClient(embed_dim=8)
    v1 = mock.embed("같은 입력")
    v2 = mock.embed("같은 입력")
    assert v1 == v2 and len(v1) == 8


def test_bedrock_methods_raise_not_implemented():
    from matcause.core.llm.base import user
    from matcause.core.llm.bedrock_client import BedrockLLMClient

    bedrock = BedrockLLMClient(region="us-east-1", model_id="anthropic.x")
    with pytest.raises(NotImplementedError):
        bedrock.complete([user("hi")])
    with pytest.raises(NotImplementedError):
        bedrock.complete_json([user("hi")])


def test_extract_json_from_text():
    from matcause.core.llm.mock_client import extract_json

    parsed = extract_json('설명 텍스트 {"category": "MATERIAL", "confidence": 0.8} 뒤 텍스트')
    assert parsed["category"] == "MATERIAL"
