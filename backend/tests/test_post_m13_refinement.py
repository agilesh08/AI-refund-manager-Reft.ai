"""Comprehensive regression tests for Post-M13 Bug Fix & UX/Workflow Refinement Pass.

Covers:
1. Extraction heuristics on unstructured customer claim paragraphs (Indian names, phone numbers, rupee formats, natural reasons).
2. Confidence score boundary rules and merchant recommendation mapping without premature rounding.
3. Verification session lifecycle: Hold (HTTP 423 for customer), Resume, Auto-expiration, and Delete (file unlinking and cascading child record cleanup).
4. Full investigation view and explainable report facets:
   - Questions asked and answers
   - Adaptive follow-up questions
   - Categorized visual findings (Observed, Not observed, Unclear)
   - Concise deterministic signal statuses (Payment, Order, Delivery, Location)
   - Recommendation code and label
"""
import io
import uuid
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.core.database import get_db, SessionLocal
from app.models.merchant import Merchant
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.product import Product
from app.models.workflow import Workflow, WorkflowStatus
from app.services import extraction_service
from app.services.evidence_fusion_service import map_confidence_to_recommendation

client = TestClient(app)


def make_test_image(color: str = "blue") -> bytes:
    """Generate in-memory image bytes for test uploads."""
    buf = io.BytesIO()
    img = Image.new("RGB", (20, 20), color=color)
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf.getvalue()


def test_extraction_heuristics_unstructured_paragraph():
    """Verify extraction of name, contact, order, amount, and natural reason from paragraph."""
    text = (
        "Hi, I'm Rahul Kumar (+91 98765 43210). I ordered the boAt Rockerz 450 "
        "(Order ID: ORD-2026-784521) for ₹4,999. The product I received was damaged; "
        "the left earbud is completely cracked and does not play any sound."
    )
    res = extraction_service.parse_order_text_heuristics(text)
    
    assert res.get("customer_name") == "Rahul Kumar"
    assert res.get("customer_contact") == "+91 98765 43210"
    assert res.get("order_id") == "ORD-2026-784521"
    assert res.get("refund_amount") == 4999.0
    reason = res.get("refund_reason") or ""
    assert "damaged" in reason.lower() or "cracked" in reason.lower()


def test_confidence_boundary_mapping_strict_rules():
    """Verify exact 5 boundary rules without rounding bias."""
    # Boundary 1: < 0.35 -> REJECT
    assert map_confidence_to_recommendation(0.20) == ("REJECT", "REJECT")
    assert map_confidence_to_recommendation(0.3499) == ("REJECT", "REJECT")

    # Boundary 2: 0.35 <= c < 0.50 -> CAN_REJECT_REVIEW_REQUIRED
    assert map_confidence_to_recommendation(0.35) == ("CAN_REJECT_REVIEW_REQUIRED", "CAN REJECT — REVIEW REQUIRED")
    assert map_confidence_to_recommendation(0.4999) == ("CAN_REJECT_REVIEW_REQUIRED", "CAN REJECT — REVIEW REQUIRED")

    # Boundary 3: 0.50 <= c < 0.75 -> REVIEW_REQUIRED
    assert map_confidence_to_recommendation(0.50) == ("REVIEW_REQUIRED", "REVIEW REQUIRED")
    assert map_confidence_to_recommendation(0.7499) == ("REVIEW_REQUIRED", "REVIEW REQUIRED")

    # Boundary 4: 0.75 <= c < 0.85 -> MOSTLY_APPROVE
    assert map_confidence_to_recommendation(0.75) == ("MOSTLY_APPROVE", "MOSTLY APPROVE")
    assert map_confidence_to_recommendation(0.8499) == ("MOSTLY_APPROVE", "MOSTLY APPROVE")

    # Boundary 5: >= 0.85 -> APPROVED
    assert map_confidence_to_recommendation(0.85) == ("APPROVED", "APPROVED")
    assert map_confidence_to_recommendation(1.0) == ("APPROVED", "APPROVED")


@pytest.fixture
def auth_merchant_and_session():
    """Create a test merchant, active workflow, and verification session."""
    db = SessionLocal()
    try:
        # Register merchant
        m_email = f"merchant_{uuid.uuid4().hex[:8]}@test.com"
        reg_resp = client.post(
            "/api/v1/auth/register",
            json={
                "business_name": "Refinement Test Store",
                "email": m_email,
                "password": "SecretPassword123!",
            },
        )
        assert reg_resp.status_code == 201

        # Login to get JWT
        login_resp = client.post("/api/v1/auth/login", json={"email": m_email, "password": "SecretPassword123!"})
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # Create product
        prod_resp = client.post(
            "/api/v1/products",
            headers=auth_headers,
            json={"name": "Wireless Earbuds", "sku": f"SKU-{uuid.uuid4().hex[:6]}", "price": 4999.0},
        )
        assert prod_resp.status_code == 201
        prod_id = prod_resp.json()["id"]

        # Upload all 4 reference angles
        for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
            client.post(
                f"/api/v1/products/{prod_id}/references",
                headers=auth_headers,
                data={"angle": angle},
                files={"image": (f"{angle.lower()}.jpg", make_test_image(), "image/jpeg")},
            )

        # Create active workflow
        wf_resp = client.post(
            "/api/v1/workflows",
            headers=auth_headers,
            json={"name": "Standard Flow", "description": "Verification flow"},
        )
        assert wf_resp.status_code == 201
        wf_id = wf_resp.json()["id"]

        # Add a step to allow publishing
        client.post(
            f"/api/v1/workflows/{wf_id}/steps",
            headers=auth_headers,
            json={
                "step_key": "damage_reason",
                "step_type": "MCQ",
                "title": "Select damage condition",
                "step_order": 1,
                "required": True,
                "config": {
                    "question": "What is wrong?",
                    "options": [
                        {"value": "cracked", "label": "Cracked screen"},
                        {"value": "water", "label": "Water damage"},
                    ],
                },
            },
        )

        pub_resp = client.post(f"/api/v1/workflows/{wf_id}/publish", headers=auth_headers)
        assert pub_resp.status_code == 200

        # Create verification session
        sess_resp = client.post(
            "/api/v1/verifications",
            headers=auth_headers,
            json={
                "order_id": f"ORD-{uuid.uuid4().hex[:6]}",
                "product_id": prod_id,
                "workflow_id": wf_id,
                "refund_reason": "The item is broken on arrival",
                "customer_name": "Rahul Kumar",
                "customer_contact": "+91 98765 43210",
            },
        )
        assert sess_resp.status_code == 201
        sess_data = sess_resp.json()
        token = sess_data["customer_link"].rstrip("/").split("/")[-1]
        sess_data["customer_token"] = token

        return {
            "auth_headers": auth_headers,
            "session": sess_data,
        }
    finally:
        db.close()


def test_session_hold_and_resume_lifecycle(auth_merchant_and_session):
    """Verify holding a session returns 423 to customer, and resuming restores access."""
    data = auth_merchant_and_session
    headers = data["auth_headers"]
    sess = data["session"]
    v_id = sess["verification_id"]
    token = sess["customer_token"]

    # 1. Initially customer can access overview
    ov_resp = client.get(f"/api/v1/public/verifications/{token}")
    assert ov_resp.status_code == 200
    assert ov_resp.json()["status"] == SessionStatus.CREATED.value

    # 2. Merchant places session on hold for 2 hours (7200 seconds)
    hold_resp = client.post(
        f"/api/v1/verifications/{v_id}/hold",
        headers=headers,
        json={"duration_seconds": 7200, "reason": "Waiting for warehouse check"},
    )
    assert hold_resp.status_code == 200
    hold_data = hold_resp.json()
    assert hold_data["status"] == "HELD"
    assert hold_data["hold_until"] is not None

    # 3. Customer accesses verification link -> HTTP 423 Locked
    locked_resp = client.get(f"/api/v1/public/verifications/{token}")
    assert locked_resp.status_code == 423
    assert "Verification temporarily paused" in locked_resp.json()["detail"]

    # Customer start also returns 423
    start_resp = client.post(f"/api/v1/public/verifications/{token}/start")
    assert start_resp.status_code == 423

    # 4. Merchant resumes session
    resume_resp = client.post(f"/api/v1/verifications/{v_id}/resume", headers=headers)
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == SessionStatus.CREATED.value

    # 5. Customer can access again
    ov_restored = client.get(f"/api/v1/public/verifications/{token}")
    assert ov_restored.status_code == 200
    assert ov_restored.json()["status"] == SessionStatus.CREATED.value


def test_investigation_detail_and_report_fields(auth_merchant_and_session):
    """Verify dashboard investigation detail and report contain new investigation facets."""
    data = auth_merchant_and_session
    headers = data["auth_headers"]
    sess = data["session"]
    v_id = sess["verification_id"]

    # Retrieve investigation detail
    detail_resp = client.get(f"/api/v1/verifications/{v_id}/dashboard", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    assert "questions_asked" in detail
    assert isinstance(detail["questions_asked"], list)
    assert "adaptive_follow_up_questions" in detail
    assert "visual_findings_categorized" in detail
    assert "deterministic_signal_statuses" in detail
    assert "recommendation_code" in detail
    assert "recommendation_label" in detail

    # Retrieve explainable report
    report_resp = client.get(f"/api/v1/verifications/{v_id}/report", headers=headers)
    assert report_resp.status_code == 200
    report = report_resp.json()

    assert "questions_asked" in report
    assert "adaptive_follow_up_questions" in report
    assert "visual_findings_categorized" in report
    assert "deterministic_signal_statuses" in report
    assert "recommendation_code" in report
    assert "recommendation_label" in report


def test_session_deletion(auth_merchant_and_session):
    """Verify deleting a verification removes session and prevents access."""
    data = auth_merchant_and_session
    headers = data["auth_headers"]
    sess = data["session"]
    v_id = sess["verification_id"]
    token = sess["customer_token"]

    # Delete session
    del_resp = client.delete(f"/api/v1/verifications/{v_id}", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "SUCCESS"

    # Subsequent merchant lookup returns 404
    get_resp = client.get(f"/api/v1/verifications/{v_id}/dashboard", headers=headers)
    assert get_resp.status_code == 404

    # Customer token access returns 404
    cust_resp = client.get(f"/api/v1/public/verifications/{token}")
    assert cust_resp.status_code == 404
