"""Tests for AI Reasoning Fail-Safe and Gemini Auth/API Error Handling."""
import io
import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ai.gemini_vision import GeminiVisionService
from app.ai.ollama_reasoning import OllamaReasoningService, LLAMA_REASONING_SYSTEM_INSTRUCTION
from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.verification import VerificationSession, SessionStatus
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.models.reasoning_run import ReasoningRun, ReasoningRunStatus
from app.schemas.reasoning import ReasoningAction, ReasoningResult
from app.services import (
    reasoning_context_service,
    reasoning_service,
    evidence_processing_service,
)
from tests.test_visual_analysis import (
    setup_verified_session_with_image,
    register_and_auth,
    make_test_image,
)


def test_ollama_prompt_contains_failsafe_and_guardrails():
    """Verify system instructions forbid ACCEPT_EVIDENCE on FAILED visual analysis."""
    assert "visual_analysis_status == 'FAILED'" in LLAMA_REASONING_SYSTEM_INSTRUCTION
    assert "Under NO circumstance may you choose 'ACCEPT_EVIDENCE'" in LLAMA_REASONING_SYSTEM_INSTRUCTION
    assert "DO NOT OVERRIDE GEMINI OBSERVATIONS" in LLAMA_REASONING_SYSTEM_INSTRUCTION
    assert "SCREEN_DISPLAY_APPEARANCE" in LLAMA_REASONING_SYSTEM_INSTRUCTION


def test_build_reasoning_context_flags_failed_visual(client: TestClient, db_session: Session):
    """Verify that build_reasoning_context detects FAILED visual analysis and sets flag."""
    _, auth = register_and_auth(client, "failsafe1@store.com")
    sess_data, token, ev_data = setup_verified_session_with_image(client, auth, "SKU-FS-1")
    session = db_session.execute(
        select(VerificationSession).where(VerificationSession.id == sess_data["id"])
    ).scalar_one()

    ev = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == ev_data["evidence_id"])
    ).scalar_one()

    # Add failed visual analysis for this evidence
    va = VisualAnalysis(
        evidence_id=ev.id,
        model_name=settings.GEMINI_VISION_MODEL,
        prompt_version=settings.GEMINI_VISION_PROMPT_VERSION,
        status=VisualAnalysisStatus.FAILED.value,
        error_message="401 UNAUTHENTICATED: ACCESS_TOKEN_TYPE_UNSUPPORTED",
    )
    db_session.add(va)
    db_session.commit()

    # Build context
    ctx = reasoning_context_service.build_reasoning_context(
        session=session,
        evidence_items=[ev],
        visual_analyses=[va],
    )

    # Assertions
    assert ctx["has_failed_visual_analysis"] is True
    ev_entries = [e for e in ctx["visual_observations"] if e.get("evidence_id") == ev.evidence_id]
    assert len(ev_entries) == 1
    assert ev_entries[0]["visual_analysis_status"] == "FAILED"


def test_programmatic_failsafe_overrides_accept_evidence(client: TestClient, db_session: Session):
    """Verify programmatic fail-safe converts ACCEPT_EVIDENCE to REQUEST_MORE_EVIDENCE."""
    merchant_id, auth = register_and_auth(client, "failsafe2@store.com")
    sess_data, token, ev_data = setup_verified_session_with_image(client, auth, "SKU-FS-2")
    session = db_session.execute(
        select(VerificationSession).where(VerificationSession.id == sess_data["id"])
    ).scalar_one()

    ev = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == ev_data["evidence_id"])
    ).scalar_one()

    va = VisualAnalysis(
        evidence_id=ev.id,
        model_name=settings.GEMINI_VISION_MODEL,
        prompt_version=settings.GEMINI_VISION_PROMPT_VERSION,
        status=VisualAnalysisStatus.FAILED.value,
        error_message="Gemini connection timeout",
    )
    db_session.add(va)
    db_session.commit()

    # Mock Ollama returning ACCEPT_EVIDENCE
    mock_result = ReasoningResult(
        action=ReasoningAction.ACCEPT_EVIDENCE,
        confidence=0.90,
        reasoning_summary="Image looks acceptable to LLM",
        missing_evidence=[],
    )

    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_result):
        run = reasoning_service.run_reasoning(
            db=db_session,
            merchant_id=session.merchant_id,
            verification_identifier=session.id,
        )

    assert run.status == ReasoningRunStatus.COMPLETED.value
    result_data = run.result_json

    # Programmatic fail-safe MUST have overridden ACCEPT_EVIDENCE
    assert result_data["action"] == ReasoningAction.REQUEST_MORE_EVIDENCE.value
    assert result_data["confidence"] <= 0.40
    assert "Visual evidence analysis could not be completed" in result_data["reason"]
    assert "CUSTOMER_IMAGE" in result_data.get("requested_evidence_type", "")


def test_gemini_401_graceful_handling_and_evidence_safe_state(client: TestClient, db_session: Session):
    """Verify Gemini 401 error results in FAILED visual analysis without crashing or corrupting evidence."""
    merchant_id, auth = register_and_auth(client, "failsafe3@store.com")
    sess_data, token, ev_data = setup_verified_session_with_image(client, auth, "SKU-FS-3")

    session = db_session.execute(
        select(VerificationSession).where(VerificationSession.id == sess_data["id"])
    ).scalar_one()

    ev = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == ev_data["evidence_id"])
    ).scalar_one()

    service = GeminiVisionService()

    # Mock get_client to simulate 401 error
    with patch.object(service, "get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "401 UNAUTHENTICATED: ACCESS_TOKEN_TYPE_UNSUPPORTED"
        )
        mock_get_client.return_value = mock_client

        with pytest.raises(Exception) as excinfo:
            service.analyze_evidence_image(
                evidence_bytes=make_test_image(),
                evidence_mime_type="image/jpeg",
                reference_images=[],
                product_info={"name": "Sample Widget"},
            )
        assert "401" in str(excinfo.value) or "UNAUTHENTICATED" in str(excinfo.value)

    # Verify that in the processing pipeline, failure is recorded as FAILED
    with patch("app.services.evidence_processing_service.qwen_vision_service.analyze_evidence_image", side_effect=Exception("401 UNAUTHENTICATED")):
        analysis = evidence_processing_service.analyze_evidence_image(
            db=db_session,
            merchant_id=session.merchant_id,
            verification_identifier=session.id,
            evidence_identifier=ev.id,
        )

    assert analysis.status == VisualAnalysisStatus.FAILED.value
    assert "401" in (analysis.error_message or "")
    # Evidence status must remain safe in READY_FOR_ANALYSIS
    assert ev.status == EvidenceStatus.READY_FOR_ANALYSIS.value

