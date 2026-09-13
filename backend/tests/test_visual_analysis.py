"""Automated unit and integration test suite for Milestone 7: AI Visual Consistency Analysis Using Gemini Vision."""
import io
import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ai import qwen_vision_service
from app.ai.gemini_vision import GeminiVisionService, GEMINI_VISION_SYSTEM_INSTRUCTION
from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.evidence_event import EvidenceEvent
from app.models.product_reference import ProductReference, ReferenceAngle
from app.models.verification import VerificationSession
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.schemas.visual_analysis import VisualAnalysisResult, VisualAnalysisResponse


def make_test_image(color: str = "blue", fmt: str = "JPEG") -> bytes:
    """Generate in-memory valid image bytes."""
    buf = io.BytesIO()
    img = Image.new("RGB", (30, 30), color=color)
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf.getvalue()


def register_and_auth(client: TestClient, email: str, name: str = "Test Store") -> tuple[str, str]:
    """Register and login a merchant, returning (merchant_id, auth_header)."""
    reg = client.post(
        "/api/v1/auth/register",
        json={"business_name": name, "email": email, "password": "Password123!"},
    )
    merchant_id = reg.json()["id"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    token = login.json()["access_token"]
    return merchant_id, f"Bearer {token}"


def setup_verified_session_with_image(
    client: TestClient,
    auth: str,
    sku: str = "PROD-VIS-1",
) -> tuple[dict, str, dict]:
    """Setup product with 4 angles, active workflow, started session, and submitted customer image."""
    # 1. Product with 4 reference angles
    prod_res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": f"Product {sku}", "sku": sku, "price": "199.99"},
    )
    product_id = prod_res.json()["id"]

    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        img_bytes = make_test_image(color="cyan")
        client.post(
            f"/api/v1/products/{product_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", img_bytes, "image/jpeg")},
        )

    # 2. Workflow with IMAGE and TEXT steps
    wf_res = client.post(
        "/api/v1/workflows",
        headers={"Authorization": auth},
        json={"name": f"Workflow {sku}"},
    )
    wf_id = wf_res.json()["id"]

    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "damage_photo",
            "step_type": "IMAGE",
            "title": "Damage Photograph",
            "step_order": 1,
            "required": True,
            "config": {"min_images": 1, "max_images": 3},
        },
    )

    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "damage_explanation",
            "step_type": "TEXT",
            "title": "Damage Details",
            "step_order": 2,
            "required": False,
            "config": {"min_length": 5, "max_length": 500},
        },
    )

    client.post(
        f"/api/v1/workflows/{wf_id}/publish",
        headers={"Authorization": auth},
    )

    # 3. Create verification session
    sess_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": product_id,
            "workflow_id": wf_id,
            "order_id": f"ORD-{sku}",
            "customer_name": "Test Customer",
        },
    )
    session_data = sess_res.json()
    token = session_data["customer_link"].split("/")[-1]

    # 4. Customer starts session
    client.post(f"/api/v1/public/verifications/{token}/start")

    # 5. Customer submits damage image evidence
    ev_img_bytes = make_test_image(color="red")
    ev_res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("damage.jpg", ev_img_bytes, "image/jpeg")},
    )
    evidence_data = ev_res.json()

    return session_data, token, evidence_data


SAMPLE_MOCK_GEMINI_RESULT = {
    "image_quality": {
        "is_clear": True,
        "lighting": "good",
        "blur_detected": False,
        "resolution_adequate": True,
        "notes": "Clear close-up photograph under indoor lighting",
    },
    "product_consistency": {
        "is_same_product_type": "observed",
        "matched_reference_angle": "FRONT",
        "brand_marking_visible": "observed",
        "color_consistency": "consistent",
        "shape_consistency": "consistent",
        "notes": "Ear cup silhouette and silver headband hinge match reference FRONT",
    },
    "visible_condition": {
        "claimed_damage_visible": "observed",
        "damage_type_detected": "crack",
        "damage_location": "left headband adjustment joint",
        "damage_severity_observation": "moderate",
        "packaging_condition": "unclear",
        "notes": "Visible structural hairline fracture across hinge mount",
    },
    "key_visual_observations": [
        "Headband geometry and finish match FRONT reference angle",
        "Structural fracture observed on left plastic adjustment assembly",
    ],
    "uncertainties": [
        "Internal wiring continuity cannot be evaluated visually from exterior photograph",
    ],
    "overall_visual_confidence": 0.94,
}


# ===========================================================================
# 1. Gemini Service Unit Tests
# ===========================================================================

def test_gemini_service_prompt_and_constraints():
    """Verify Gemini prompt contains strict ethical guardrails and epistemic uncertainty instructions."""
    assert "DO NOT make refund approval or rejection recommendations" in GEMINI_VISION_SYSTEM_INSTRUCTION
    assert "DO NOT make any accusations of fraud" in GEMINI_VISION_SYSTEM_INSTRUCTION
    assert "DO NOT calculate or provide fraud risk scores" in GEMINI_VISION_SYSTEM_INSTRUCTION
    assert "observed" in GEMINI_VISION_SYSTEM_INSTRUCTION
    assert "not_visible" in GEMINI_VISION_SYSTEM_INSTRUCTION
    assert "not_observed" in GEMINI_VISION_SYSTEM_INSTRUCTION
    assert "unclear" in GEMINI_VISION_SYSTEM_INSTRUCTION


def test_gemini_service_missing_api_key():
    """Verify GeminiVisionService raises ValueError if invoked without API key."""
    service = GeminiVisionService(api_key=None)
    service.api_key = None
    with pytest.raises(ValueError, match="Gemini API key is not configured"):
        service.analyze_evidence_image(
            evidence_bytes=b"dummy",
            evidence_mime_type="image/jpeg",
            reference_images=[],
            product_info={"name": "Test"},
        )


def test_gemini_service_successful_multimodal_call():
    """Verify GeminiVisionService formats multimodal contents and parses structured response."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(SAMPLE_MOCK_GEMINI_RESULT)
    mock_client.models.generate_content.return_value = mock_response

    service = GeminiVisionService(api_key="fake-test-key", model_name="gemini-2.5-flash")
    service._client = mock_client

    ref_images = [
        {"angle": "FRONT", "bytes": b"ref_front_bytes", "mime_type": "image/jpeg"},
        {"angle": "BACK", "bytes": b"ref_back_bytes", "mime_type": "image/jpeg"},
    ]
    product_info = {"name": "Test Headphone", "sku": "HP-1", "category": "Audio"}
    claim_context = {"workflow_step_key": "step_1", "customer_notes": "Cracked"}

    result = service.analyze_evidence_image(
        evidence_bytes=b"evidence_bytes",
        evidence_mime_type="image/jpeg",
        reference_images=ref_images,
        product_info=product_info,
        claim_context=claim_context,
    )

    assert isinstance(result, VisualAnalysisResult)
    assert result.overall_visual_confidence == 0.94
    assert result.image_quality.is_clear is True
    assert result.product_consistency.is_same_product_type == "observed"
    assert result.product_consistency.matched_reference_angle == "FRONT"
    assert result.visible_condition.claimed_damage_visible == "observed"

    # Verify mock call parameters
    mock_client.models.generate_content.assert_called_once()
    call_kwargs = mock_client.models.generate_content.call_args[1]
    assert call_kwargs["model"] == "gemini-2.5-flash"
    assert call_kwargs["config"].response_mime_type == "application/json"
    assert call_kwargs["config"].response_schema == VisualAnalysisResult


def test_gemini_service_epistemic_uncertainty_not_visible():
    """Verify epistemic uncertainty 'not_visible' is preserved without coercion."""
    uncertain_result_json = dict(SAMPLE_MOCK_GEMINI_RESULT)
    uncertain_result_json["product_consistency"] = {
        "is_same_product_type": "observed",
        "matched_reference_angle": "NONE",
        "brand_marking_visible": "not_visible",
        "color_consistency": "consistent",
        "shape_consistency": "unclear",
        "notes": "Logo is on the reverse side which is not visible in this angle",
    }
    uncertain_result_json["visible_condition"] = {
        "claimed_damage_visible": "not_visible",
        "damage_type_detected": None,
        "damage_location": None,
        "damage_severity_observation": None,
        "packaging_condition": "not_visible",
        "notes": "Customer took photo of packaging exterior, item itself is not visible",
    }

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(uncertain_result_json)
    mock_client.models.generate_content.return_value = mock_response

    service = GeminiVisionService(api_key="fake-test-key")
    service._client = mock_client

    result = service.analyze_evidence_image(
        evidence_bytes=b"evidence",
        evidence_mime_type="image/jpeg",
        reference_images=[],
        product_info={"name": "Test"},
    )

    assert result.product_consistency.brand_marking_visible == "not_visible"
    assert result.visible_condition.claimed_damage_visible == "not_visible"


# ===========================================================================
# 2. Integration Tests: Analyze Evidence Endpoint
# ===========================================================================

@patch("app.ai.qwen_vision.qwen_vision_service.analyze_evidence_image")
def test_analyze_customer_image_evidence_success(mock_analyze, client: TestClient, db_session: Session):
    """End-to-end test: merchant triggers visual analysis on customer image evidence."""
    mock_analyze.return_value = VisualAnalysisResult.model_validate(SAMPLE_MOCK_GEMINI_RESULT)

    _, auth = register_and_auth(client, "merchant_vis@example.com")
    session_data, _, ev_data = setup_verified_session_with_image(client, auth, sku="SKU-VIS-SUCCESS")

    verification_id = session_data["verification_id"]
    evidence_id = ev_data["evidence_id"]

    # Trigger analysis
    res = client.post(
        f"/api/v1/verifications/{verification_id}/evidence/{evidence_id}/analyze",
        headers={"Authorization": auth},
    )

    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["evidence_id"] == evidence_id
    assert data["status"] == "COMPLETED"
    assert data["overall_confidence"] == 0.94
    assert data["model_name"] == qwen_vision_service.model_name
    assert data["prompt_version"] == qwen_vision_service.prompt_version
    assert data["result"]["product_consistency"]["is_same_product_type"] == "observed"
    assert data["result"]["visible_condition"]["claimed_damage_visible"] == "observed"
    assert len(data["result"]["key_visual_observations"]) == 2

    # Verify Evidence state transitioned to ANALYZED
    ev_record = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == evidence_id)
    ).scalar_one()
    assert ev_record.status == EvidenceStatus.ANALYZED.value

    # Verify DB state: VisualAnalysis record exists
    analysis_record = db_session.execute(
        select(VisualAnalysis).where(VisualAnalysis.evidence_id == ev_record.id)
    ).scalar_one_or_none()
    assert analysis_record is not None
    assert analysis_record.status == VisualAnalysisStatus.COMPLETED.value
    assert analysis_record.overall_confidence == 0.94

    # Verify audit event logged
    events = db_session.execute(
        select(EvidenceEvent).where(EvidenceEvent.evidence_id == ev_record.id)
    ).scalars().all()
    event_types = [e.event_type for e in events]
    assert "AI_VISUAL_ANALYSIS_COMPLETED" in event_types


@patch("app.ai.qwen_vision.qwen_vision_service.analyze_evidence_image")
def test_get_evidence_analysis_endpoint(mock_analyze, client: TestClient):
    """Verify GET analysis endpoint returns the latest visual analysis for merchant."""
    mock_analyze.return_value = VisualAnalysisResult.model_validate(SAMPLE_MOCK_GEMINI_RESULT)

    _, auth = register_and_auth(client, "merchant_get_analysis@example.com")
    session_data, _, ev_data = setup_verified_session_with_image(client, auth, sku="SKU-VIS-GET")

    verification_id = session_data["verification_id"]
    evidence_id = ev_data["evidence_id"]

    # Before running analysis -> 404
    pre_res = client.get(
        f"/api/v1/verifications/{verification_id}/evidence/{evidence_id}/analysis",
        headers={"Authorization": auth},
    )
    assert pre_res.status_code == status.HTTP_404_NOT_FOUND

    # Trigger analysis
    client.post(
        f"/api/v1/verifications/{verification_id}/evidence/{evidence_id}/analyze",
        headers={"Authorization": auth},
    )

    # After running analysis -> 200 with result
    get_res = client.get(
        f"/api/v1/verifications/{verification_id}/evidence/{evidence_id}/analysis",
        headers={"Authorization": auth},
    )
    assert get_res.status_code == status.HTTP_200_OK
    data = get_res.json()
    assert data["status"] == "COMPLETED"
    assert data["result"]["overall_visual_confidence"] == 0.94


@patch("app.ai.qwen_vision.qwen_vision_service.analyze_evidence_image")
def test_analyze_evidence_caching_and_force_reanalyze(mock_analyze, client: TestClient):
    """Verify caching returns existing COMPLETED analysis, and force_reanalyze triggers new run."""
    mock_analyze.return_value = VisualAnalysisResult.model_validate(SAMPLE_MOCK_GEMINI_RESULT)

    _, auth = register_and_auth(client, "merchant_cache@example.com")
    session_data, _, ev_data = setup_verified_session_with_image(client, auth, sku="SKU-VIS-CACHE")

    verification_id = session_data["verification_id"]
    evidence_id = ev_data["evidence_id"]

    # First call: invokes Gemini
    res1 = client.post(
        f"/api/v1/verifications/{verification_id}/evidence/{evidence_id}/analyze",
        headers={"Authorization": auth},
    )
    assert res1.status_code == status.HTTP_200_OK
    first_analysis_id = res1.json()["id"]
    assert mock_analyze.call_count == 1

    # Second call without force_reanalyze: returns cached result without invoking Gemini again
    res2 = client.post(
        f"/api/v1/verifications/{verification_id}/evidence/{evidence_id}/analyze",
        headers={"Authorization": auth},
    )
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()["id"] == first_analysis_id
    assert mock_analyze.call_count == 1

    # Third call WITH force_reanalyze=true: invokes Gemini again
    res3 = client.post(
        f"/api/v1/verifications/{verification_id}/evidence/{evidence_id}/analyze?force_reanalyze=true",
        headers={"Authorization": auth},
    )
    assert res3.status_code == status.HTTP_200_OK
    assert res3.json()["id"] != first_analysis_id
    assert mock_analyze.call_count == 2


def test_analyze_text_evidence_rejected(client: TestClient):
    """Verify trying to analyze CUSTOMER_TEXT evidence returns 400 Bad Request."""
    _, auth = register_and_auth(client, "merchant_text_rej@example.com")
    session_data, token, _ = setup_verified_session_with_image(client, auth, sku="SKU-VIS-TEXT")

    verification_id = session_data["verification_id"]

    # Submit text evidence
    text_res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={
            "workflow_step_key": "damage_explanation",
            "text": "The left side snapped completely in half.",
        },
    )
    text_evidence_id = text_res.json()["evidence_id"]

    # Attempt visual analysis on text evidence
    res = client.post(
        f"/api/v1/verifications/{verification_id}/evidence/{text_evidence_id}/analyze",
        headers={"Authorization": auth},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "only applicable to image evidence" in res.json()["detail"]


@patch("app.ai.qwen_vision.qwen_vision_service.analyze_evidence_image")
def test_gemini_failure_handling_and_fail_safe(mock_analyze, client: TestClient, db_session: Session):
    """Verify that if Gemini throws an error, analysis is marked FAILED and evidence stays READY_FOR_ANALYSIS."""
    mock_analyze.side_effect = RuntimeError("Google API quota exhausted (RESOURCE_EXHAUSTED)")

    _, auth = register_and_auth(client, "merchant_fail_safe@example.com")
    session_data, _, ev_data = setup_verified_session_with_image(client, auth, sku="SKU-VIS-FAIL")

    verification_id = session_data["verification_id"]
    evidence_id = ev_data["evidence_id"]

    res = client.post(
        f"/api/v1/verifications/{verification_id}/evidence/{evidence_id}/analyze",
        headers={"Authorization": auth},
    )

    # API returns 200 with status=FAILED and error message preserved
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["status"] == "FAILED"
    assert "quota exhausted" in data["error_message"]
    assert data["result"] is None

    # CRITICAL: Evidence status MUST NOT be rejected or failed; remains READY_FOR_ANALYSIS
    ev_record = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == evidence_id)
    ).scalar_one()
    assert ev_record.status == EvidenceStatus.READY_FOR_ANALYSIS.value

    # Verify audit event for failure is recorded
    events = db_session.execute(
        select(EvidenceEvent).where(EvidenceEvent.evidence_id == ev_record.id)
    ).scalars().all()
    event_types = [e.event_type for e in events]
    assert "AI_VISUAL_ANALYSIS_FAILED" in event_types


def test_merchant_isolation_on_analyze_and_get(client: TestClient):
    """Verify Merchant A cannot trigger or view visual analysis for Merchant B's sessions."""
    _, auth_a = register_and_auth(client, "merchant_a_vis@example.com", "Merchant A")
    _, auth_b = register_and_auth(client, "merchant_b_vis@example.com", "Merchant B")

    session_a, _, ev_a = setup_verified_session_with_image(client, auth_a, sku="SKU-VIS-ISO-A")

    ver_id_a = session_a["verification_id"]
    ev_id_a = ev_a["evidence_id"]

    # Merchant B tries to trigger analysis on Merchant A's evidence -> 404
    hack_res = client.post(
        f"/api/v1/verifications/{ver_id_a}/evidence/{ev_id_a}/analyze",
        headers={"Authorization": auth_b},
    )
    assert hack_res.status_code == status.HTTP_404_NOT_FOUND

    # Merchant B tries to view analysis -> 404
    view_res = client.get(
        f"/api/v1/verifications/{ver_id_a}/evidence/{ev_id_a}/analysis",
        headers={"Authorization": auth_b},
    )
    assert view_res.status_code == status.HTTP_404_NOT_FOUND


def test_customer_token_cannot_access_merchant_analysis_endpoint(client: TestClient):
    """Verify customer cannot access internal merchant AI analysis endpoints."""
    _, auth = register_and_auth(client, "merchant_pub_block@example.com")
    session_data, token, ev_data = setup_verified_session_with_image(client, auth, sku="SKU-VIS-CUST")

    ver_id = session_data["verification_id"]
    ev_id = ev_data["evidence_id"]

    # Public customer attempts to access merchant analysis endpoint with no auth header
    unauth_res = client.post(
        f"/api/v1/verifications/{ver_id}/evidence/{ev_id}/analyze",
    )
    assert unauth_res.status_code == status.HTTP_401_UNAUTHORIZED

    # Also cannot GET analysis
    unauth_get = client.get(
        f"/api/v1/verifications/{ver_id}/evidence/{ev_id}/analysis",
    )
    assert unauth_get.status_code == status.HTTP_401_UNAUTHORIZED


def test_analyze_nonexistent_evidence_or_session(client: TestClient):
    """Verify 404 when analyzing nonexistent verification session or evidence ID."""
    _, auth = register_and_auth(client, "merchant_404_test@example.com")
    session_data, _, _ = setup_verified_session_with_image(client, auth, sku="SKU-VIS-404")

    ver_id = session_data["verification_id"]

    # Nonexistent evidence ID
    res1 = client.post(
        f"/api/v1/verifications/{ver_id}/evidence/ev_nonexistent_999/analyze",
        headers={"Authorization": auth},
    )
    assert res1.status_code == status.HTTP_404_NOT_FOUND

    # Nonexistent session ID
    res2 = client.post(
        "/api/v1/verifications/ver_nonexistent_888/evidence/ev_1/analyze",
        headers={"Authorization": auth},
    )
    assert res2.status_code == status.HTTP_404_NOT_FOUND


@patch("app.ai.qwen_vision.qwen_vision_service.analyze_evidence_image")
def test_frozen_snapshot_and_product_reference_stability(mock_analyze, client: TestClient):
    """Verify visual analysis utilizes product references correctly even if workflow is updated."""
    mock_analyze.return_value = VisualAnalysisResult.model_validate(SAMPLE_MOCK_GEMINI_RESULT)

    _, auth = register_and_auth(client, "merchant_freeze_vis@example.com")
    session_data, _, ev_data = setup_verified_session_with_image(client, auth, sku="SKU-VIS-FREEZE")

    ver_id = session_data["verification_id"]
    ev_id = ev_data["evidence_id"]

    # Analyze succeeds
    res = client.post(
        f"/api/v1/verifications/{ver_id}/evidence/{ev_id}/analyze",
        headers={"Authorization": auth},
    )
    assert res.status_code == status.HTTP_200_OK

    # Verify references passed to Gemini were 4 angles
    call_kwargs = mock_analyze.call_args[1]
    assert len(call_kwargs["reference_images"]) == 4
    angles = [ref["angle"] for ref in call_kwargs["reference_images"]]
    assert set(angles) == {"FRONT", "BACK", "LEFT", "RIGHT"}
    assert call_kwargs["product_info"]["sku"] == "SKU-VIS-FREEZE"
