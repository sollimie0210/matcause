"""API 라우트 (T-210).

파이프라인(Orchestrator)을 HTTP 로 노출한다. Streamlit UI 는 서비스를 직접
호출하지만, 외부 연동/React 대비용으로 동일 기능을 API 로도 제공한다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from matcause.app_service import get_service

router = APIRouter()


class DiagnoseRequest(BaseModel):
    text: str
    override: str | None = None  # "MATERIAL" | "PROCESS" | None


def _diagnosis_to_dict(dx) -> dict[str, Any]:
    return {
        "id": dx.id,
        "status": dx.status.value,
        "triage": (
            {
                "category": dx.triage.category.value,
                "confidence": dx.triage.confidence,
                "rationale": dx.triage.rationale,
                "signals": dx.triage.signals,
            }
            if dx.triage
            else None
        ),
        "material_finding": (
            {
                "risk_score": dx.material_finding.risk_score,
                "breakdown": dx.material_finding.breakdown,
                "summary": dx.material_finding.summary,
                "ranked_candidates": [
                    {
                        "name": c.name,
                        "score": c.score,
                        "metrics": c.metrics,
                        "improvement": c.improvement,
                        "tradeoffs": c.tradeoffs,
                    }
                    for c in dx.material_finding.ranked_candidates
                ],
            }
            if dx.material_finding
            else None
        ),
        "report": (
            {
                "cause": dx.report.cause,
                "format": dx.report.format.value,
                "recommended_actions": dx.report.recommended_actions,
                "recommended_experiments": dx.report.recommended_experiments,
                "markdown": dx.report.markdown,
            }
            if dx.report
            else None
        ),
        "error": dx.error,
    }


@router.post("/diagnose")
def diagnose(req: DiagnoseRequest) -> dict[str, Any]:
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="이슈 텍스트가 비어 있습니다")
    dx = get_service().diagnose(req.text, override=req.override)
    return _diagnosis_to_dict(dx)


@router.get("/diagnosis/{diagnosis_id}")
def get_diagnosis(diagnosis_id: str) -> dict[str, Any]:
    dx = get_service().get(diagnosis_id)
    if dx is None:
        raise HTTPException(status_code=404, detail="진단을 찾을 수 없습니다")
    return _diagnosis_to_dict(dx)
