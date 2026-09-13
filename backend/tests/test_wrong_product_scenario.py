"""Tests for Wrong Product claim scenario with Screen Display capture assessment."""
import io
import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.verification import VerificationSession, SessionStatus
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.schemas.evidence_fusion import VerificationAssessmentState, FusionDimensionResult, DimensionStatus, DimensionType
from app.schemas.reasoning import ReasoningAction, ReasoningResult
from app.schemas.visual_analysis import (
    VisualAnalysisResult,
    EvidenceCaptureAssessment,
    ProductIdentityAnalysis,
    ImageQualityAnalysis,
    ProductConsistencyAnalysis,
    VisibleConditionAnalysis,
)
from app.services import (
    reasoning_context_service,
    reasoning_service,
    evidence_fusion_service,
)
from tests.test_visual_analysis import (
    setup_verified_session_with_image,
    register_and_auth,
    make_test_image,
)


def make_mouse_screen_analysis_result() -> VisualAnalysisResult:
    """Create simulated Gemini analysis of a mouse displayed on a laptop screen."""
    return VisualAnalysisResult(
        overall_visual_confidence=0.92,
        image_quality=ImageQualityAnalysis(
            overall="MODERATE",
            product_visibility="CLEAR",
            issues=["screen glare", "pixelation"],
        ),
        product_consistency=ProductConsistencyAnalysis(
            is_same_product_type="not_observed",
            matched_reference_angle="NONE",
            brand_marking_visible="not_visible",
            color_consistency="inconsistent",
            shape_consistency="inconsistent",
            notes="Observed item is an optical mouse, whereas baseline product is a keyboard.",
        ),
        visible_condition=VisibleConditionAnalysis(
            claimed_damage_visible="not_observed",
            notes="No damage observed; product appears intact but is wrong product.",
        ),
        capture_assessment=EvidenceCaptureAssessment(
            type="SCREEN_DISPLAY_APPEARANCE",
            confidence=0.95,
            observations=[
                "Screen bezel visible in upper periphery",
                "Display pixels and moire pattern observed",
            ],
        ),
        product_identity=ProductIdentityAnalysis(
            apparent_product_type="Computer Mouse",
            matches_trusted_product="MISMATCH",
            confidence=0.92,
            identifying_features_visible=["scroll wheel", "optical sensor window", "curved ergonomic body"],
        ),
        key_visual_observations=[
            "Visible pixel grid and screen bezel indicates the image was captured of a monitor/display.",
            "Item depicted is a black optical mouse, inconsistent with the ordered keyboard.",
        ],
        uncertainties=["Serial number not legible on screen display"],
    )


def test_fusion_evaluates_screen_capture_and_product_mismatch():
    """Verify deterministic fusion accounts for screen capture and product mismatch for standard non-wrong-product claim."""
    analysis_result = make_mouse_screen_analysis_result()

    va = VisualAnalysis(
        evidence_id="ev-mock-1",
        model_name=settings.GEMINI_VISION_MODEL,
        prompt_version=settings.GEMINI_VISION_PROMPT_VERSION,
        status=VisualAnalysisStatus.COMPLETED.value,
        result_json=analysis_result.model_dump(),
        overall_confidence=0.92,
    )

    result, contradictions = evidence_fusion_service.evaluate_visual_vs_trusted_reference([va])

    # Status must be INCONSISTENT for standard mismatch without wrong product claim
    assert result.status == DimensionStatus.INCONSISTENT
    assert result.details["capture_assessment"]["type"] == "SCREEN_DISPLAY_APPEARANCE"
    assert result.details["product_identity"]["matches_trusted_product"] == "MISMATCH"
    assert len(contradictions) >= 1
    contra = contradictions[0]
    assert "screen display" in contra.description.lower()
    assert "fraud" not in contra.description.lower()


def test_claim_aware_wrong_product_mismatch_produces_review_required():
    """TEST 1: Claim = 'Received wrong product', Reference = Earbuds, Customer Image = PC Mouse.
    Expected: REVIEW_REQUIRED (NOT REJECT).
    """
    session = VerificationSession(
        id="sess-wrong-prod-1",
        verification_id="VR-WRONG-001",
        merchant_id="merchant-1",
        refund_reason="Received wrong product",
        status=SessionStatus.IN_PROGRESS.value,
    )

    visual_result = VisualAnalysisResult(
        image_quality=ImageQualityAnalysis(overall="GOOD", product_visibility="CLEAR"),
        product_consistency=ProductConsistencyAnalysis(
            is_same_product_type="not_observed",
            brand_marking_visible="not_observed",
            color_consistency="inconsistent",
            shape_consistency="inconsistent",
            is_identical_model=False,
            branding_match=False,
            structural_shape_match=False,
        ),
        visible_condition=VisibleConditionAnalysis(claimed_damage_visible="not_applicable"),
        capture_assessment=EvidenceCaptureAssessment(
            type="DIRECT_PHYSICAL_APPEARANCE",
            capture_context="PHYSICAL_PHOTO",
            confidence=0.90,
            observations=["Direct physical photograph of a black ergonomic computer mouse"],
        ),
        product_identity=ProductIdentityAnalysis(
            apparent_product_type="computer mouse",
            matches_trusted_product="MISMATCH",
            confidence=0.95,
        ),
        key_visual_observations=["Subject is a wired USB computer mouse, not in-ear earbuds"],
        overall_visual_confidence=0.92,
    )

    va = VisualAnalysis(
        id="va-1",
        evidence_id="ev-1",
        status=VisualAnalysisStatus.COMPLETED.value,
        overall_confidence=0.92,
        result_json=visual_result.model_dump(),
    )

    ev = Evidence(
        id="ev-1",
        evidence_id="EV-101",
        verification_session_id=session.id,
        evidence_type=EvidenceType.CUSTOMER_IMAGE.value,
        workflow_step_key="damage_photo",
    )

    d1, c1, m1 = evidence_fusion_service.evaluate_claim_vs_visual(session, [ev], [va])
    d2, c2 = evidence_fusion_service.evaluate_visual_vs_trusted_reference([va], session=session)

    # Claim vs Visual should be CONSISTENT (since photo shows different item supporting "wrong product" claim)
    assert d1.status == DimensionStatus.CONSISTENT
    assert "SUPPORTING_CLAIM" in str(d1.details.get("claim_alignment"))

    # Visual vs Reference should be INSUFFICIENT / MEDIUM severity, NOT HIGH severity contradiction
    assert not any(c.severity.value == "HIGH" for c in c2)

    # Overall fusion mapped recommendation must be REVIEW_REQUIRED / MANUAL REVIEW REQUIRED
    rec_code, rec_label = evidence_fusion_service.map_confidence_to_recommendation(0.60, VerificationAssessmentState.REVIEW_REQUIRED.value)
    assert rec_code == "REVIEW_REQUIRED"
    assert "REVIEW" in rec_label
    assert rec_code != "REJECT"


def test_claim_aware_damaged_product_consistent():
    """TEST 2: Claim = 'Product is damaged', Customer image = Earbuds with visible damage.
    Expected: EVIDENCE_CONSISTENT.
    """
    session = VerificationSession(
        id="sess-damaged-1",
        verification_id="VR-DAM-001",
        merchant_id="merchant-1",
        refund_reason="Product arrived damaged",
        status=SessionStatus.IN_PROGRESS.value,
    )

    visual_result = VisualAnalysisResult(
        image_quality=ImageQualityAnalysis(overall="GOOD", product_visibility="CLEAR"),
        product_consistency=ProductConsistencyAnalysis(
            is_same_product_type="observed",
            brand_marking_visible="observed",
            color_consistency="consistent",
            shape_consistency="consistent",
            is_identical_model=True,
            branding_match=True,
            structural_shape_match=True,
        ),
        visible_condition=VisibleConditionAnalysis(
            claimed_damage_visible="observed",
            localized_damage=True,
            damage_type_detected="crack",
            damage_location="left earbud housing",
            damage_severity_observation="moderate",
        ),
        capture_assessment=EvidenceCaptureAssessment(
            type="DIRECT_PHYSICAL_APPEARANCE",
            capture_context="PHYSICAL_PHOTO",
            confidence=0.92,
        ),
        product_identity=ProductIdentityAnalysis(
            apparent_product_type="in-ear earbuds",
            matches_trusted_product="MATCH",
            confidence=0.95,
        ),
        key_visual_observations=["Visible hairline fracture on left earbud outer casing"],
        overall_visual_confidence=0.90,
    )

    va = VisualAnalysis(
        id="va-2",
        evidence_id="ev-2",
        status=VisualAnalysisStatus.COMPLETED.value,
        overall_confidence=0.90,
        result_json=visual_result.model_dump(),
    )

    ev = Evidence(
        id="ev-2",
        evidence_id="EV-102",
        verification_session_id=session.id,
        evidence_type=EvidenceType.CUSTOMER_IMAGE.value,
        workflow_step_key="damage_photo",
    )

    d1, c1, m1 = evidence_fusion_service.evaluate_claim_vs_visual(session, [ev], [va])
    assert d1.status == DimensionStatus.CONSISTENT
    assert len(c1) == 0


def test_wrong_product_claim_with_matching_product_image():
    """TEST 3: Claim = 'Received wrong product', Customer image = Matching Earbuds.
    Expected: Discrepancy requiring review (INSUFFICIENT / REVIEW_REQUIRED).
    """
    session = VerificationSession(
        id="sess-wrong-match-1",
        verification_id="VR-WRONG-MATCH-001",
        merchant_id="merchant-1",
        refund_reason="Received wrong product",
        status=SessionStatus.IN_PROGRESS.value,
    )

    visual_result = VisualAnalysisResult(
        image_quality=ImageQualityAnalysis(overall="GOOD", product_visibility="CLEAR"),
        product_consistency=ProductConsistencyAnalysis(
            is_same_product_type="observed",
            brand_marking_visible="observed",
            color_consistency="consistent",
            shape_consistency="consistent",
            is_identical_model=True,
            branding_match=True,
            structural_shape_match=True,
        ),
        visible_condition=VisibleConditionAnalysis(claimed_damage_visible="not_observed"),
        capture_assessment=EvidenceCaptureAssessment(type="DIRECT_PHYSICAL_APPEARANCE", confidence=0.90),
        product_identity=ProductIdentityAnalysis(
            apparent_product_type="in-ear earbuds",
            matches_trusted_product="MATCH",
            confidence=0.95,
        ),
        key_visual_observations=["Product matches merchant earbuds reference"],
        overall_visual_confidence=0.90,
    )

    va = VisualAnalysis(
        id="va-3",
        evidence_id="ev-3",
        status=VisualAnalysisStatus.COMPLETED.value,
        overall_confidence=0.90,
        result_json=visual_result.model_dump(),
    )

    ev = Evidence(
        id="ev-3",
        evidence_id="EV-103",
        verification_session_id=session.id,
        evidence_type=EvidenceType.CUSTOMER_IMAGE.value,
        workflow_step_key="damage_photo",
    )

    d1, c1, m1 = evidence_fusion_service.evaluate_claim_vs_visual(session, [ev], [va])
    assert d1.status == DimensionStatus.INSUFFICIENT
    assert len(c1) == 1
    assert c1[0].severity.value == "MEDIUM"


def test_reasoning_context_includes_capture_and_product_identity(client: TestClient, db_session: Session):
    """Verify reasoning context passes capture assessment and product identity to Llama."""
    _, auth = register_and_auth(client, "wrongprod1@store.com")
    sess_data, token, ev_data = setup_verified_session_with_image(client, auth, "SKU-WP-1")
    session = db_session.execute(
        select(VerificationSession).where(VerificationSession.id == sess_data["id"])
    ).scalar_one()

    ev = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == ev_data["evidence_id"])
    ).scalar_one()

    analysis_res = make_mouse_screen_analysis_result()
    va = VisualAnalysis(
        evidence_id=ev.id,
        model_name=settings.GEMINI_VISION_MODEL,
        prompt_version=settings.GEMINI_VISION_PROMPT_VERSION,
        status=VisualAnalysisStatus.COMPLETED.value,
        result_json=analysis_res.model_dump(),
    )
    db_session.add(va)
    db_session.commit()

    ctx = reasoning_context_service.build_reasoning_context(
        session=session,
        evidence_items=[ev],
        visual_analyses=[va],
    )

    matching_items = [item for item in ctx["visual_observations"] if item.get("evidence_id") == ev.evidence_id]
    assert len(matching_items) == 1
    item = matching_items[0]
    assert item["capture_assessment"]["type"] == "SCREEN_DISPLAY_APPEARANCE"
    assert item["product_identity"]["matches_trusted_product"] == "MISMATCH"
    assert item["product_identity"]["apparent_product_type"] == "Computer Mouse"


def test_llama_reasoning_requests_direct_physical_photo_non_accusatory(client: TestClient, db_session: Session):
    """Verify reasoning produces polite targeted request for direct physical photo."""
    merchant_id, auth = register_and_auth(client, "wrongprod2@store.com")
    sess_data, token, ev_data = setup_verified_session_with_image(client, auth, "SKU-WP-2")
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
        status=VisualAnalysisStatus.COMPLETED.value,
        result_json=make_mouse_screen_analysis_result().model_dump(),
    )
    db_session.add(va)
    db_session.commit()

    # Simulate Llama output adhering to instructions
    simulated_llama_output = ReasoningResult(
        action=ReasoningAction.REQUEST_MORE_EVIDENCE,
        confidence=0.88,
        requested_evidence_type="CUSTOMER_IMAGE",
        reason=(
            "The submitted photo appears to be taken of a display screen rather than the physical item received. "
            "Please take a direct photo of the physical product and packaging you received on a flat surface."
        ),
        missing_evidence=[],
        reasoning_summary="Evidence shows screen display capture of a different product. Direct physical photo required.",
    )

    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=simulated_llama_output):
        run = reasoning_service.run_reasoning(
            db=db_session,
            merchant_id=session.merchant_id,
            verification_identifier=session.id,
        )

    assert run.status == "COMPLETED"
    result = run.result_json

    assert result["action"] == "REQUEST_MORE_EVIDENCE"
    # Never accuse of fraud
    assert "fraud" not in result["reason"].lower()
    assert "fake" not in result["reason"].lower()
    assert "scam" not in result["reason"].lower()
    # Asks for direct physical photo
    assert "direct photo" in result["reason"].lower() or "physical" in result["reason"].lower()


