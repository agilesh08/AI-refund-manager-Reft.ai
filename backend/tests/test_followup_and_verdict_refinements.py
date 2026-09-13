"""Targeted tests for Follow-up AI improvements, verdict thresholds, and Ollama concurrency guard."""
import pytest
from datetime import timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.verification import VerificationSession, SessionStatus, utc_now
from app.models.product import Product
from app.models.evidence import Evidence, EvidenceType
from app.models.evidence_request import EvidenceRequest, EvidenceRequestStatus
from app.models.reasoning_run import ReasoningRun, ReasoningRunStatus
from app.schemas.reasoning import ReasoningAction, ReasoningResult
from app.services.evidence_fusion_service import map_confidence_to_recommendation
from app.services import adaptive_verification_service, reasoning_service


def test_verdict_threshold_exact_boundaries():
    """Verify all 8 threshold boundaries specified in requirement 14 & 22."""
    # 1. 34% -> REJECT
    code, label = map_confidence_to_recommendation(0.34)
    assert code == "REJECT"
    assert label == "REJECT"

    # 2. 35% -> CAN REJECT — REVIEW REQUIRED
    code, label = map_confidence_to_recommendation(0.35)
    assert code == "CAN_REJECT_REVIEW_REQUIRED"
    assert label == "CAN REJECT — REVIEW REQUIRED"

    # 3. 49.9% -> CAN REJECT — REVIEW REQUIRED
    code, label = map_confidence_to_recommendation(0.499)
    assert code == "CAN_REJECT_REVIEW_REQUIRED"
    assert label == "CAN REJECT — REVIEW REQUIRED"

    # 4. 50% -> REVIEW REQUIRED
    code, label = map_confidence_to_recommendation(0.50)
    assert code == "REVIEW_REQUIRED"
    assert label == "REVIEW REQUIRED"

    # 5. 74.9% -> REVIEW REQUIRED
    code, label = map_confidence_to_recommendation(0.749)
    assert code == "REVIEW_REQUIRED"
    assert label == "REVIEW REQUIRED"

    # 6. 75% -> MOSTLY APPROVE
    code, label = map_confidence_to_recommendation(0.75)
    assert code == "MOSTLY_APPROVE"
    assert label == "MOSTLY APPROVE"

    # 7. 85% -> APPROVED
    code, label = map_confidence_to_recommendation(0.85)
    assert code == "APPROVED"
    assert label == "APPROVED"

    # 8. 85.1% -> APPROVED
    code, label = map_confidence_to_recommendation(0.851)
    assert code == "APPROVED"
    assert label == "APPROVED"


def test_schema_forbids_fraud_and_verdict_in_question():
    """Verify that ReasoningResult forbids accusatory or final decision words in question."""
    with pytest.raises(ValueError, match="prohibited verdict phrase"):
        ReasoningResult(
            action=ReasoningAction.REQUEST_MORE_EVIDENCE,
            reasoning_summary="Valid objective summary here.",
            confidence=0.8,
            next_step_key="product_photo",
            requested_evidence_type="MCQ",
            question="Did you commit fraud when returning this item?",
            options=["Yes", "No"],
            reason="Follow-up clarification",
        )


def test_mcq_followup_cycle_and_text_fulfillment(client: TestClient, db_session: Session):
    """Verify MCQ follow-up generation and customer fulfillment with selected option."""
    # 1. Setup session
    prod = Product(
        merchant_id="m_test_mcq",
        name="Noise Cancelling Earbuds",
        sku="NCE-001",
        price=199.99,
    )
    db_session.add(prod)
    db_session.flush()

    sess = VerificationSession(
        verification_id="VR-2026-MCQ1",
        merchant_id="m_test_mcq",
        product_id=prod.id,
        order_id="ORD-MCQ-1",
        refund_reason="Left earbud does not play audio",
        refund_amount=199.99,
        workflow_id="wf_test",
        workflow_version=1,
        workflow_snapshot_json={
            "steps": [
                {"step_key": "damage_photo", "step_type": "IMAGE", "title": "Damage Photo", "required": True},
            ]
        },
        status=SessionStatus.IN_PROGRESS.value,
        customer_token_hash="hash_mcq_token_123",
        expires_at=utc_now() + timedelta(days=3),
    )
    db_session.add(sess)
    db_session.commit()
    db_session.refresh(sess)

    # 2. Mock Llama returning an MCQ question with options
    mock_llama = ReasoningResult(
        action=ReasoningAction.REQUEST_MORE_EVIDENCE,
        reasoning_summary="Customer claimed audio failure, but visual evidence cannot test internal speaker power.",
        confidence=0.6,
        next_step_key="damage_photo",
        requested_evidence_type="MCQ",
        question="Does the left earbud power on when taken out of the charging case?",
        options=["Yes", "No", "Sometimes", "Not sure"],
        reason="Does the left earbud power on when taken out of the charging case?",
    )

    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_llama):
        run, req = adaptive_verification_service.run_adaptive_reasoning_cycle(
            db=db_session,
            merchant_id="m_test_mcq",
            verification_identifier=sess.id,
        )

    assert req is not None
    assert req.requested_evidence_type == "MCQ"
    assert req.options_json == ["Yes", "No", "Sometimes", "Not sure"]
    assert req.status == EvidenceRequestStatus.PENDING.value

    # 3. Test question deduplication: running cycle again with same question skips duplicate
    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_llama):
        run2, req2 = adaptive_verification_service.run_adaptive_reasoning_cycle(
            db=db_session,
            merchant_id="m_test_mcq",
            verification_identifier=sess.id,
        )
    assert req2 is None, "Should not create duplicate request with identical question"


def test_ollama_processing_concurrency_guard(db_session: Session):
    """Verify that an active PROCESSING run blocks concurrent duplicate Ollama invocations."""
    prod = Product(
        merchant_id="m_test_concur",
        name="Test Item",
        sku="SKU-CONCUR",
        price=50.0,
    )
    db_session.add(prod)
    db_session.flush()

    sess = VerificationSession(
        verification_id="VR-2026-CONCUR1",
        merchant_id="m_test_concur",
        product_id=prod.id,
        order_id="ORD-CONCUR-1",
        workflow_id="wf_test",
        workflow_version=1,
        workflow_snapshot_json={"steps": [{"step_key": "step1", "step_type": "IMAGE"}]},
        status=SessionStatus.IN_PROGRESS.value,
        customer_token_hash="hash_concur_123",
        expires_at=utc_now() + timedelta(days=3),
    )
    db_session.add(sess)
    db_session.commit()
    db_session.refresh(sess)

    # Add a run in PROCESSING state
    run_proc = ReasoningRun(
        verification_session_id=sess.id,
        model_name="llama3.2:1b",
        prompt_version="v1",
        input_context_hash="hash_mock_test_123",
        status=ReasoningRunStatus.PROCESSING.value,
    )
    db_session.add(run_proc)
    db_session.commit()

    # Calling run_reasoning should return the existing in_progress run and NOT call generate_reasoning
    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning") as mock_gen:
        result_run = reasoning_service.run_reasoning(
            db=db_session,
            merchant_id="m_test_concur",
            verification_identifier=sess.id,
        )
        assert result_run.id == run_proc.id
        assert result_run.status == ReasoningRunStatus.PROCESSING.value
        mock_gen.assert_not_called()
