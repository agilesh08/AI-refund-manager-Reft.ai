"""Comprehensive test suite for Milestone M9: Adaptive Evidence Follow-Up Engine.

Tests cover:
- Step validation against frozen workflow snapshot (IMAGE/CAMERA vs TEXT/MCQ).
- EvidenceRequest lifecycle: PENDING -> FULFILLED, CANCELLED.
- Deduplication of pending requests.
- MAX_ADAPTIVE_FOLLOWUPS hard limit cutoff (3).
- Customer public API for listing and fulfilling evidence requests.
- Automatic downstream Gemini Vision re-analysis upon fulfillment.
- Automatic downstream Llama re-reasoning upon fulfillment.
- Terminal action resolution (COMPLETE_VERIFICATION / CONTINUE_WORKFLOW).
- Merchant API for viewing evidence requests with tenant isolation.
- Context hash invalidation upon adaptive request creation/fulfillment.
- Fail-safe resilience: AI errors never corrupt session or accuse customer.
"""
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from PIL import Image
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence, EvidenceStatus, EvidenceType
from app.models.evidence_request import EvidenceRequest, EvidenceRequestStatus
from app.models.reasoning_run import ReasoningRun, ReasoningRunStatus
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.schemas.reasoning import ReasoningAction, ReasoningResult
from app.services import (
    adaptive_verification_service,
    evidence_request_service,
    reasoning_context_service,
)


def make_test_image(color: str = "blue", fmt: str = "JPEG") -> bytes:
    """Generate in-memory valid image bytes."""
    buf = io.BytesIO()
    img = Image.new("RGB", (30, 30), color=color)
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf.getvalue()


def register_and_auth(client: TestClient, email: str, name: str = "Merchant") -> tuple[str, str]:
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


def setup_test_verification(
    client: TestClient,
    auth: str,
    sku: str = "PROD-ADAPT-1",
) -> tuple[dict, str]:
    """Setup product with 4 angles, active workflow with 3 steps, and started session.

    Steps created:
    1. 'damage_photo' (IMAGE)
    2. 'serial_number_photo' (CAMERA)
    3. 'customer_explanation' (TEXT)

    Returns (session_dict, customer_token).
    """
    # 1. Product
    prod_res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": f"Product {sku}", "sku": sku, "price": "199.99"},
    )
    product_id = prod_res.json()["id"]

    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        img_bytes = make_test_image(color="teal")
        client.post(
            f"/api/v1/products/{product_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", img_bytes, "image/jpeg")},
        )

    # 2. Workflow with 3 steps
    wf_res = client.post(
        "/api/v1/workflows",
        headers={"Authorization": auth},
        json={"name": f"Adaptive Workflow {sku}"},
    )
    wf_id = wf_res.json()["id"]

    # Step 1: IMAGE
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "damage_photo",
            "step_type": "IMAGE",
            "title": "Damage Photo",
            "step_order": 1,
            "required": True,
            "config": {"min_images": 1, "max_images": 2},
        },
    )

    # Step 2: CAMERA
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "serial_number_photo",
            "step_type": "CAMERA",
            "title": "Serial Number Camera Photo",
            "step_order": 2,
            "required": True,
            "config": {"min_images": 1, "max_images": 1},
        },
    )

    # Step 3: TEXT
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "customer_explanation",
            "step_type": "TEXT",
            "title": "Customer Statement",
            "step_order": 3,
            "required": False,
        },
    )

    # Publish workflow
    client.post(
        f"/api/v1/workflows/{wf_id}/publish",
        headers={"Authorization": auth},
    )

    # 3. Verification Session
    sess_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": product_id,
            "workflow_id": wf_id,
            "order_id": f"ORD-{sku}",
            "customer_name": "Test Customer",
            "customer_contact": "customer@example.com",
            "refund_reason": "Device arrived cracked and doesn't power on.",
            "refund_amount": 199.99,
        },
    )
    sess_data = sess_res.json()
    customer_link = sess_data["customer_link"]
    token = customer_link.rstrip("/").split("/")[-1]

    # Start session so status is IN_PROGRESS
    client.post(f"/api/v1/public/verifications/{token}/start")

    return sess_data, token


# ===========================================================================
# 1. Step Validation Tests
# ===========================================================================

class TestStepValidation:
    """Test validation of requested steps against the session's frozen snapshot."""

    def test_step_validation_image_step_allowed(self, client: TestClient, db_session: Session):
        """1. IMAGE steps are eligible for adaptive evidence follow-up."""
        _, auth = register_and_auth(client, "adapt1@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A1")

        session = db_session.get(VerificationSession, sess_data["id"])
        step = evidence_request_service.validate_requested_step(session, "damage_photo", "CUSTOMER_IMAGE")
        assert step["step_key"] == "damage_photo"
        assert step["step_type"] == "IMAGE"

    def test_step_validation_camera_step_allowed(self, client: TestClient, db_session: Session):
        """2. CAMERA steps are eligible for adaptive evidence follow-up."""
        _, auth = register_and_auth(client, "adapt2@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A2")

        session = db_session.get(VerificationSession, sess_data["id"])
        step = evidence_request_service.validate_requested_step(session, "serial_number_photo", "CUSTOMER_IMAGE")
        assert step["step_key"] == "serial_number_photo"
        assert step["step_type"] == "CAMERA"

    def test_step_validation_text_step_rejected(self, client: TestClient, db_session: Session):
        """3. TEXT steps cannot be targeted for adaptive image evidence requests (422)."""
        _, auth = register_and_auth(client, "adapt3@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A3")

        session = db_session.get(VerificationSession, sess_data["id"])
        with pytest.raises(Exception) as exc_info:
            evidence_request_service.validate_requested_step(session, "customer_explanation", "CUSTOMER_IMAGE")
        assert "not eligible for adaptive follow-up" in str(exc_info.value.detail)

    def test_step_validation_nonexistent_step_rejected(self, client: TestClient, db_session: Session):
        """4. Step keys not in the frozen snapshot are rejected (422)."""
        _, auth = register_and_auth(client, "adapt4@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A4")

        session = db_session.get(VerificationSession, sess_data["id"])
        with pytest.raises(Exception) as exc_info:
            evidence_request_service.validate_requested_step(session, "nonexistent_step", "CUSTOMER_IMAGE")
        assert "does not exist in the session's frozen workflow snapshot" in str(exc_info.value.detail)

    def test_step_validation_cancelled_session_rejected(self, client: TestClient, db_session: Session):
        """5. Cancelled session rejects evidence requests (410)."""
        _, auth = register_and_auth(client, "adapt5@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A5")

        client.post(
            f"/api/v1/verifications/{sess_data['id']}/cancel",
            headers={"Authorization": auth},
            json={"reason": "Cancelled by merchant"},
        )

        session = db_session.get(VerificationSession, sess_data["id"])
        db_session.refresh(session)
        with pytest.raises(Exception) as exc_info:
            evidence_request_service.validate_requested_step(session, "damage_photo", "CUSTOMER_IMAGE")
        assert exc_info.value.status_code == status.HTTP_410_GONE

    def test_step_validation_expired_session_rejected(self, client: TestClient, db_session: Session):
        """6. Expired session rejects evidence requests (410)."""
        _, auth = register_and_auth(client, "adapt6@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A6")

        session = db_session.get(VerificationSession, sess_data["id"])
        session.status = SessionStatus.EXPIRED.value
        db_session.commit()

        with pytest.raises(Exception) as exc_info:
            evidence_request_service.validate_requested_step(session, "damage_photo", "CUSTOMER_IMAGE")
        assert exc_info.value.status_code == status.HTTP_410_GONE

    def test_step_validation_created_session_rejected(self, client: TestClient, db_session: Session):
        """7. Session not yet started (CREATED state) rejects evidence requests (400)."""
        _, auth = register_and_auth(client, "adapt7@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A7")

        session = db_session.get(VerificationSession, sess_data["id"])
        session.status = SessionStatus.CREATED.value
        db_session.commit()

        with pytest.raises(Exception) as exc_info:
            evidence_request_service.validate_requested_step(session, "damage_photo", "CUSTOMER_IMAGE")
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


# ===========================================================================
# 2. Evidence Request Lifecycle & Deduplication Tests
# ===========================================================================

class TestEvidenceRequestLifecycle:
    """Test creation, deduplication, and cutoff limits."""

    def test_create_evidence_request_success(self, client: TestClient, db_session: Session):
        """8. Successfully create EvidenceRequest in PENDING state with audit event."""
        _, auth = register_and_auth(client, "adapt8@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A8")

        session = db_session.get(VerificationSession, sess_data["id"])
        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Please provide a clear photo of the cracked display without glare.",
        )
        assert req is not None
        assert req.status == EvidenceRequestStatus.PENDING.value
        assert req.workflow_step_key == "damage_photo"
        assert req.requested_evidence_type == "CUSTOMER_IMAGE"
        assert "without glare" in req.reason

        # Check audit event
        events = db_session.execute(
            select(VerificationEvent).where(
                VerificationEvent.session_id == session.id,
                VerificationEvent.event_type == VerificationEventType.EVIDENCE_REQUEST_CREATED.value,
            )
        ).scalars().all()
        assert len(events) >= 1
        assert events[0].metadata_json["request_id"] == req.id

    def test_create_evidence_request_deduplication(self, client: TestClient, db_session: Session):
        """9. Idempotently returns existing PENDING request for identical step and type."""
        _, auth = register_and_auth(client, "adapt9@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A9")

        session = db_session.get(VerificationSession, sess_data["id"])
        req1 = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Initial request",
        )
        req2 = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Duplicate attempt",
        )
        assert req1.id == req2.id
        all_reqs = evidence_request_service.list_session_requests(db_session, session.id)
        assert len(all_reqs) == 1

    def test_max_adaptive_followups_cutoff(self, client: TestClient, db_session: Session):
        """10. Creating more than MAX_ADAPTIVE_FOLLOWUPS (3) returns None and halts requests."""
        _, auth = register_and_auth(client, "adapt10@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A10")

        session = db_session.get(VerificationSession, sess_data["id"])

        # Create 3 requests (fulfilling each so deduplication doesn't trigger)
        for i in range(settings.MAX_ADAPTIVE_FOLLOWUPS):
            req = evidence_request_service.create_evidence_request(
                db=db_session,
                session=session,
                step_key="damage_photo" if i % 2 == 0 else "serial_number_photo",
                requested_evidence_type="CUSTOMER_IMAGE",
                reason=f"Request #{i+1}",
            )
            assert req is not None
            # Mark fulfilled so we can request again
            evidence_request_service.fulfill_request(db_session, req)

        # 4th request must be suppressed
        req4 = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Exceeds limit",
        )
        assert req4 is None

        # Total non-cancelled requests stays at 3
        all_reqs = evidence_request_service.list_session_requests(db_session, session.id)
        assert len(all_reqs) == settings.MAX_ADAPTIVE_FOLLOWUPS


# ===========================================================================
# 3. Customer Public Evidence Request API Tests
# ===========================================================================

class TestCustomerEvidenceRequestAPI:
    """Test public customer-facing evidence request listing and fulfillment."""

    def test_customer_list_evidence_requests(self, client: TestClient, db_session: Session):
        """11. Customer can list evidence requests for their session."""
        _, auth = register_and_auth(client, "adapt11@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A11")

        session = db_session.get(VerificationSession, sess_data["id"])
        evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Please provide a closer image of the crack.",
        )

        res = client.get(f"/api/v1/public/verifications/{token}/evidence-requests")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert len(data) == 1
        assert data[0]["workflow_step_key"] == "damage_photo"
        assert data[0]["status"] == "PENDING"
        assert "closer image" in data[0]["reason"]

    def test_customer_list_evidence_requests_sanitized(self, client: TestClient, db_session: Session):
        """12. Customer response is sanitized (no internal session UUID or merchant ID)."""
        _, auth = register_and_auth(client, "adapt12@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A12")

        session = db_session.get(VerificationSession, sess_data["id"])
        evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Sanitization check",
        )

        res = client.get(f"/api/v1/public/verifications/{token}/evidence-requests")
        data = res.json()[0]
        assert "verification_session_id" not in data
        assert "merchant_id" not in data
        assert "id" in data
        assert "workflow_step_key" in data

    def test_customer_fulfill_evidence_request_success(self, client: TestClient, db_session: Session):
        """13. Customer fulfills evidence request via image upload; status transitions to FULFILLED."""
        _, auth = register_and_auth(client, "adapt13@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A13")

        session = db_session.get(VerificationSession, sess_data["id"])
        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Please upload a photo of the damaged screen.",
        )

        img_bytes = make_test_image(color="cyan")
        with patch("app.services.evidence_processing_service.analyze_evidence_image"):
            with patch("app.services.adaptive_verification_service.run_adaptive_reasoning_cycle", return_value=(None, None)):
                res = client.post(
                    f"/api/v1/public/verifications/{token}/evidence-requests/{req.id}/fulfill",
                    files={"file": ("followup.jpg", img_bytes, "image/jpeg")},
                )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["request"]["status"] == "FULFILLED"
        assert data["request"]["fulfilled_at"] is not None
        assert data["evidence"]["workflow_step_key"] == "damage_photo"
        assert data["evidence"]["status"] == "READY_FOR_ANALYSIS"

        # Verify DB state
        db_req = db_session.get(EvidenceRequest, req.id)
        db_session.refresh(db_req)
        assert db_req.status == EvidenceRequestStatus.FULFILLED.value
        assert db_req.fulfilled_at is not None

    def test_customer_fulfill_request_already_fulfilled_rejected(self, client: TestClient, db_session: Session):
        """14. Fulfilling an already FULFILLED request returns 400."""
        _, auth = register_and_auth(client, "adapt14@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A14")

        session = db_session.get(VerificationSession, sess_data["id"])
        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Initial request",
        )
        evidence_request_service.fulfill_request(db_session, req)

        img_bytes = make_test_image(color="navy")
        res = client.post(
            f"/api/v1/public/verifications/{token}/evidence-requests/{req.id}/fulfill",
            files={"file": ("again.jpg", img_bytes, "image/jpeg")},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "only PENDING requests can be fulfilled" in res.json()["detail"]

    def test_customer_fulfill_nonexistent_request_rejected(self, client: TestClient, db_session: Session):
        """15. Fulfilling nonexistent request ID returns 404."""
        _, auth = register_and_auth(client, "adapt15@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A15")

        img_bytes = make_test_image(color="yellow")
        res = client.post(
            f"/api/v1/public/verifications/{token}/evidence-requests/nonexistent-id/fulfill",
            files={"file": ("missing.jpg", img_bytes, "image/jpeg")},
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_customer_fulfill_cancelled_session_rejected(self, client: TestClient, db_session: Session):
        """16. Fulfillment on cancelled session returns 410."""
        _, auth = register_and_auth(client, "adapt16@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A16")

        session = db_session.get(VerificationSession, sess_data["id"])
        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Test",
        )

        client.post(
            f"/api/v1/verifications/{sess_data['id']}/cancel",
            headers={"Authorization": auth},
            json={"reason": "Cancelled"},
        )

        img_bytes = make_test_image(color="gold")
        res = client.post(
            f"/api/v1/public/verifications/{token}/evidence-requests/{req.id}/fulfill",
            files={"file": ("test.jpg", img_bytes, "image/jpeg")},
        )
        assert res.status_code == status.HTTP_410_GONE

    def test_customer_fulfill_expired_session_rejected(self, client: TestClient, db_session: Session):
        """17. Fulfillment on expired session returns 410."""
        _, auth = register_and_auth(client, "adapt17@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A17")

        session = db_session.get(VerificationSession, sess_data["id"])
        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Test",
        )

        session.status = SessionStatus.EXPIRED.value
        db_session.commit()

        img_bytes = make_test_image(color="silver")
        res = client.post(
            f"/api/v1/public/verifications/{token}/evidence-requests/{req.id}/fulfill",
            files={"file": ("test.jpg", img_bytes, "image/jpeg")},
        )
        assert res.status_code == status.HTTP_410_GONE


# ===========================================================================
# 4. Merchant API & Security Isolation Tests
# ===========================================================================

class TestMerchantEvidenceRequestAPI:
    """Test merchant viewing and security isolation of evidence requests."""

    def test_merchant_list_evidence_requests(self, client: TestClient, db_session: Session):
        """18. Merchant can list all evidence requests for their verification session."""
        _, auth = register_and_auth(client, "adapt18@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A18")

        session = db_session.get(VerificationSession, sess_data["id"])
        evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Merchant listing test",
        )

        res = client.get(
            f"/api/v1/verifications/{sess_data['id']}/evidence-requests",
            headers={"Authorization": auth},
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert len(data) == 1
        assert data[0]["verification_session_id"] == sess_data["id"]

    def test_merchant_get_evidence_request_by_id(self, client: TestClient, db_session: Session):
        """19. Merchant can retrieve a specific evidence request by ID."""
        _, auth = register_and_auth(client, "adapt19@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A19")

        session = db_session.get(VerificationSession, sess_data["id"])
        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="serial_number_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Specific request retrieval",
        )

        res = client.get(
            f"/api/v1/verifications/{sess_data['id']}/evidence-requests/{req.id}",
            headers={"Authorization": auth},
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["id"] == req.id
        assert data["workflow_step_key"] == "serial_number_photo"

    def test_merchant_isolation_evidence_requests(self, client: TestClient, db_session: Session):
        """20. Merchant B cannot view or access Merchant A's evidence requests (404)."""
        _, auth_a = register_and_auth(client, "merchA@store.com")
        sess_a, token_a = setup_test_verification(client, auth_a, "SKU-MA")

        _, auth_b = register_and_auth(client, "merchB@store.com")

        session_a = db_session.get(VerificationSession, sess_a["id"])
        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session_a,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Merchant A request",
        )

        # Merchant B tries to list Merchant A's evidence requests -> 404
        res_list = client.get(
            f"/api/v1/verifications/{sess_a['id']}/evidence-requests",
            headers={"Authorization": auth_b},
        )
        assert res_list.status_code == status.HTTP_404_NOT_FOUND

        # Merchant B tries to get specific request -> 404
        res_get = client.get(
            f"/api/v1/verifications/{sess_a['id']}/evidence-requests/{req.id}",
            headers={"Authorization": auth_b},
        )
        assert res_get.status_code == status.HTTP_404_NOT_FOUND

    def test_unauthenticated_evidence_requests_blocked(self, client: TestClient, db_session: Session):
        """21. Unauthenticated requests to merchant endpoints are rejected (401)."""
        res = client.get("/api/v1/verifications/some-id/evidence-requests")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


# ===========================================================================
# 5. Closed-Loop Adaptive Verification Cycle Tests
# ===========================================================================

class TestClosedLoopAdaptiveCycle:
    """Test full multi-turn cycle: Initial Evidence -> Llama -> Follow-Up -> Fulfillment -> Re-Analysis -> Terminal Action."""

    def test_adaptive_cycle_flow_to_complete_verification(self, client: TestClient, db_session: Session):
        """22. Complete multi-turn adaptive verification cycle terminating in COMPLETE_VERIFICATION."""
        _, auth = register_and_auth(client, "adapt22@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A22")
        verification_id = sess_data["id"]

        # Step 1: Customer submits initial damage photo
        img1 = make_test_image(color="red")
        client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("damage1.jpg", img1, "image/jpeg")},
        )

        # Turn 1: Llama reasons and requests more evidence (serial_number_photo)
        mock_llama_turn1 = ReasoningResult(
            action=ReasoningAction.REQUEST_MORE_EVIDENCE,
            reasoning_summary="Initial damage photo is blurry; need serial number to verify product authenticity.",
            confidence=0.75,
            next_step_key="serial_number_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Please provide a clear photo of the serial number label on the back of the device.",
            observations_used=["Blurry front image"],
            limitations=["Serial number not visible"],
        )

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_llama_turn1):
            res1 = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )
        assert res1.status_code == status.HTTP_200_OK
        data1 = res1.json()
        assert data1["result"]["action"] == "REQUEST_MORE_EVIDENCE"

        # Verify EvidenceRequest was created in DB
        requests = client.get(
            f"/api/v1/verifications/{verification_id}/evidence-requests",
            headers={"Authorization": auth},
        ).json()
        assert len(requests) == 1
        req_id = requests[0]["id"]
        assert requests[0]["workflow_step_key"] == "serial_number_photo"
        assert requests[0]["status"] == "PENDING"

        # Turn 2: Customer fulfills request with serial number photo
        # Mock Gemini Vision analysis and next Llama turn (COMPLETE_VERIFICATION)
        mock_gemini_analysis = VisualAnalysis(
            overall_confidence=0.92,
            status=VisualAnalysisStatus.COMPLETED.value,
            result_json={
                "product_consistency": {"is_same_product_type": "consistent"},
                "visible_condition": {"claimed_damage_visible": "visible"},
                "key_visual_observations": ["Serial label clearly visible and matches merchant reference"],
            },
        )

        mock_llama_turn2 = ReasoningResult(
            action=ReasoningAction.COMPLETE_VERIFICATION,
            reasoning_summary="Serial number photo confirmed consistent with baseline references; verification complete.",
            confidence=0.95,
            next_step_key=None,
            observations_used=["Serial number label matches baseline"],
            limitations=[],
        )

        img2 = make_test_image(color="green")
        with patch("app.services.evidence_processing_service.analyze_evidence_image", return_value=mock_gemini_analysis):
            with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_llama_turn2):
                fulfill_res = client.post(
                    f"/api/v1/public/verifications/{token}/evidence-requests/{req_id}/fulfill",
                    files={"file": ("serial.jpg", img2, "image/jpeg")},
                )

        assert fulfill_res.status_code == status.HTTP_200_OK
        f_data = fulfill_res.json()
        assert f_data["request"]["status"] == "FULFILLED"
        assert f_data["reasoning_action"] == "COMPLETE_VERIFICATION"

        # Check reasoning runs history (should have 2 runs)
        runs = client.get(
            f"/api/v1/verifications/{verification_id}/reasoning",
            headers={"Authorization": auth},
        ).json()
        assert len(runs) == 2
        assert runs[0]["result"]["action"] == "COMPLETE_VERIFICATION"
        assert runs[1]["result"]["action"] == "REQUEST_MORE_EVIDENCE"

    def test_adaptive_cycle_flow_to_continue_workflow(self, client: TestClient, db_session: Session):
        """23. Multi-turn adaptive cycle terminating in CONTINUE_WORKFLOW."""
        _, auth = register_and_auth(client, "adapt23@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A23")
        verification_id = sess_data["id"]

        mock_llama_req = ReasoningResult(
            action=ReasoningAction.REQUEST_MORE_EVIDENCE,
            reasoning_summary="Need additional angle.",
            confidence=0.7,
            next_step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Please provide another photo.",
        )

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_llama_req):
            client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        reqs = evidence_request_service.list_session_requests(db_session, verification_id)
        assert len(reqs) == 1
        req_id = reqs[0].id

        mock_llama_cont = ReasoningResult(
            action=ReasoningAction.CONTINUE_WORKFLOW,
            reasoning_summary="Photo received; proceed to customer statement step.",
            confidence=0.85,
            next_step_key="customer_explanation",
            observations_used=["Additional photo inspected"],
            limitations=[],
        )

        img = make_test_image(color="orange")
        with patch("app.services.evidence_processing_service.analyze_evidence_image"):
            with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_llama_cont):
                res = client.post(
                    f"/api/v1/public/verifications/{token}/evidence-requests/{req_id}/fulfill",
                    files={"file": ("extra.jpg", img, "image/jpeg")},
                )

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["reasoning_action"] == "CONTINUE_WORKFLOW"
        assert res.json()["next_step_key"] == "customer_explanation"


# ===========================================================================
# 6. Context Hash Invalidation & Cache Tests
# ===========================================================================

class TestContextHashInvalidation:
    """Verify context hash changes when adaptive requests are created or fulfilled."""

    def test_context_hash_changes_on_fulfillment_invalidating_cache(self, client: TestClient, db_session: Session):
        """24. New request or fulfillment updates context hash, invalidating prior cached reasoning."""
        _, auth = register_and_auth(client, "adapt24@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A24")
        session = db_session.get(VerificationSession, sess_data["id"])

        # Initial context hash
        ctx1 = reasoning_context_service.build_reasoning_context(session, [], [])
        hash1 = reasoning_context_service.calculate_context_hash(ctx1)

        # Create an evidence request
        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Test cache invalidation",
        )
        ctx2 = reasoning_context_service.build_reasoning_context(session, [], [], [req])
        hash2 = reasoning_context_service.calculate_context_hash(ctx2)
        assert hash1 != hash2, "Context hash must change when evidence request is created"

        # Fulfill request
        evidence_request_service.fulfill_request(db_session, req)
        ctx3 = reasoning_context_service.build_reasoning_context(session, [], [], [req])
        hash3 = reasoning_context_service.calculate_context_hash(ctx3)
        assert hash2 != hash3, "Context hash must change when evidence request is fulfilled"


# ===========================================================================
# 7. Fail-Safe Resilience & Graceful Degradation Tests
# ===========================================================================

class TestFailSafeResilience:
    """Ensure AI errors during adaptive fulfillment do not crash or corrupt session."""

    def test_gemini_failure_during_fulfillment_failsafe(self, client: TestClient, db_session: Session):
        """25. Gemini Vision failure during fulfillment does not fail fulfillment (evidence saved, session valid)."""
        _, auth = register_and_auth(client, "adapt25@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A25")
        session = db_session.get(VerificationSession, sess_data["id"])

        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Test Gemini failure",
        )

        img = make_test_image(color="pink")
        with patch("app.services.evidence_processing_service.analyze_evidence_image", side_effect=RuntimeError("Gemini quota exceeded")):
            with patch("app.services.adaptive_verification_service.run_adaptive_reasoning_cycle", return_value=(None, None)):
                res = client.post(
                    f"/api/v1/public/verifications/{token}/evidence-requests/{req.id}/fulfill",
                    files={"file": ("fail_gemini.jpg", img, "image/jpeg")},
                )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["request"]["status"] == "FULFILLED"
        assert data["evidence"]["status"] == "READY_FOR_ANALYSIS"

        # Session remains IN_PROGRESS
        sess_check = client.get(f"/api/v1/verifications/{session.id}", headers={"Authorization": auth}).json()
        assert sess_check["status"] == "IN_PROGRESS"

    def test_ollama_failure_during_fulfillment_failsafe(self, client: TestClient, db_session: Session):
        """26. Ollama failure during fulfillment does not fail fulfillment (evidence saved, request fulfilled)."""
        _, auth = register_and_auth(client, "adapt26@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A26")
        session = db_session.get(VerificationSession, sess_data["id"])

        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Test Ollama failure",
        )

        img = make_test_image(color="brown")
        with patch("app.services.evidence_processing_service.analyze_evidence_image"):
            with patch("app.services.adaptive_verification_service.run_adaptive_reasoning_cycle", side_effect=RuntimeError("Ollama daemon unreachable")):
                res = client.post(
                    f"/api/v1/public/verifications/{token}/evidence-requests/{req.id}/fulfill",
                    files={"file": ("fail_ollama.jpg", img, "image/jpeg")},
                )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["request"]["status"] == "FULFILLED"
        assert data["reasoning_action"] is None

        # Session remains IN_PROGRESS
        sess_check = client.get(f"/api/v1/verifications/{session.id}", headers={"Authorization": auth}).json()
        assert sess_check["status"] == "IN_PROGRESS"

    def test_audit_trail_evidence_request_events(self, client: TestClient, db_session: Session):
        """27. VerificationEvent trail records EVIDENCE_REQUEST_CREATED and EVIDENCE_REQUEST_FULFILLED."""
        _, auth = register_and_auth(client, "adapt27@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A27")
        session = db_session.get(VerificationSession, sess_data["id"])

        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Audit trail test",
        )
        evidence_request_service.fulfill_request(db_session, req)

        events = db_session.execute(
            select(VerificationEvent)
            .where(VerificationEvent.session_id == session.id)
            .order_by(VerificationEvent.created_at.asc())
        ).scalars().all()

        types = [e.event_type for e in events]
        assert VerificationEventType.EVIDENCE_REQUEST_CREATED.value in types
        assert VerificationEventType.EVIDENCE_REQUEST_FULFILLED.value in types

    def test_cancel_evidence_request_lifecycle(self, client: TestClient, db_session: Session):
        """28. Cancelling an evidence request transitions status to CANCELLED and logs audit event."""
        _, auth = register_and_auth(client, "adapt28@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A28")
        session = db_session.get(VerificationSession, sess_data["id"])

        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Will be cancelled",
        )
        cancelled_req = evidence_request_service.cancel_request(db_session, req, reason="Customer provided alternate proof")
        assert cancelled_req.status == EvidenceRequestStatus.CANCELLED.value

        events = db_session.execute(
            select(VerificationEvent)
            .where(
                VerificationEvent.session_id == session.id,
                VerificationEvent.event_type == VerificationEventType.EVIDENCE_REQUEST_CANCELLED.value,
            )
        ).scalars().all()
        assert len(events) >= 1
        assert events[0].metadata_json["request_id"] == req.id

    def test_customer_token_cannot_access_merchant_evidence_requests(self, client: TestClient, db_session: Session):
        """29. Customer public tokens cannot access merchant evidence requests routes."""
        _, auth = register_and_auth(client, "adapt29@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A29")

        # Passing customer token to merchant endpoint fails authentication (401)
        res = client.get(
            f"/api/v1/verifications/{sess_data['id']}/evidence-requests",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_adaptive_cycle_cutoff_degradation_in_reasoning_endpoint(self, client: TestClient, db_session: Session):
        """30. POST /verifications/{id}/reason suppresses EvidenceRequest when limit (3) is reached."""
        _, auth = register_and_auth(client, "adapt30@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A30")
        session = db_session.get(VerificationSession, sess_data["id"])

        # Pre-create 3 fulfilled requests
        for i in range(settings.MAX_ADAPTIVE_FOLLOWUPS):
            r = evidence_request_service.create_evidence_request(
                db=db_session,
                session=session,
                step_key="damage_photo",
                requested_evidence_type="CUSTOMER_IMAGE",
                reason=f"Existing {i+1}",
            )
            evidence_request_service.fulfill_request(db_session, r)

        mock_llama = ReasoningResult(
            action=ReasoningAction.REQUEST_MORE_EVIDENCE,
            reasoning_summary="Attempting 4th request beyond limit.",
            confidence=0.7,
            next_step_key="serial_number_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="4th request",
        )

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_llama):
            res = client.post(
                f"/api/v1/verifications/{sess_data['id']}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        # Check that no 4th request was added
        all_reqs = evidence_request_service.list_session_requests(db_session, session.id)
        assert len(all_reqs) == settings.MAX_ADAPTIVE_FOLLOWUPS

    def test_customer_fulfill_with_invalid_image_type_rejected(self, client: TestClient, db_session: Session):
        """31. Submitting non-image data (text file) to image fulfillment endpoint returns 400."""
        _, auth = register_and_auth(client, "adapt31@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A31")
        session = db_session.get(VerificationSession, sess_data["id"])

        req = evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="Image expected",
        )

        bad_bytes = b"This is plain text, not an image"
        res = client.post(
            f"/api/v1/public/verifications/{token}/evidence-requests/{req.id}/fulfill",
            files={"file": ("fake.jpg", bad_bytes, "image/jpeg")},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_adaptive_evidence_request_relationship_on_session(self, client: TestClient, db_session: Session):
        """32. VerificationSession.evidence_requests ORM relationship works as expected."""
        _, auth = register_and_auth(client, "adapt32@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-A32")
        session = db_session.get(VerificationSession, sess_data["id"])

        evidence_request_service.create_evidence_request(
            db=db_session,
            session=session,
            step_key="damage_photo",
            requested_evidence_type="CUSTOMER_IMAGE",
            reason="ORM test",
        )

        db_session.refresh(session)
        assert len(session.evidence_requests) == 1
        assert session.evidence_requests[0].workflow_step_key == "damage_photo"
        assert session.evidence_requests[0].session.id == session.id

