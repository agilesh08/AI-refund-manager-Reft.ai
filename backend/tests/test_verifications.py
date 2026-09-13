"""Automated unit and integration tests for Milestone 5: Verification Sessions & Public Customer Links."""
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_verification_token
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.workflow import WorkflowStatus


def make_test_image(color: str = "blue") -> bytes:
    """Generate in-memory image bytes for test uploads."""
    buf = io.BytesIO()
    img = Image.new("RGB", (20, 20), color=color)
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf.getvalue()


def register_and_auth(client: TestClient, email: str, name: str = "Test Store") -> tuple[str, str]:
    """Helper to register and login a merchant, returning (merchant_id, auth_header)."""
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


def create_complete_product(client: TestClient, auth: str, sku: str = "COMP-001") -> str:
    """Create product and upload all 4 canonical reference angles (FRONT, BACK, LEFT, RIGHT)."""
    prod_res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Reference Product", "sku": sku, "price": "99.99"},
    )
    product_id = prod_res.json()["id"]

    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        client.post(
            f"/api/v1/products/{product_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", make_test_image(), "image/jpeg")},
        )
    return product_id


def create_incomplete_product(client: TestClient, auth: str, sku: str = "INCOMP-001") -> str:
    """Create product with only 2 reference angles."""
    prod_res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Incomplete Product", "sku": sku, "price": "49.99"},
    )
    product_id = prod_res.json()["id"]

    for angle in ["FRONT", "BACK"]:
        client.post(
            f"/api/v1/products/{product_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", make_test_image(), "image/jpeg")},
        )
    return product_id


def create_active_workflow(client: TestClient, auth: str, name: str = "Active Flow") -> str:
    """Create a workflow with valid step and publish it to ACTIVE status."""
    wf_res = client.post(
        "/api/v1/workflows",
        headers={"Authorization": auth},
        json={"name": name, "description": "Workflow for test sessions"},
    )
    assert wf_res.status_code == status.HTTP_201_CREATED
    workflow_id = wf_res.json()["id"]

    # Add a valid MCQ step
    step_res = client.post(
        f"/api/v1/workflows/{workflow_id}/steps",
        headers={"Authorization": auth},
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
    assert step_res.status_code == status.HTTP_201_CREATED

    # Publish workflow
    pub_res = client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={"Authorization": auth},
    )
    assert pub_res.status_code == status.HTTP_200_OK
    return workflow_id


def create_draft_workflow(client: TestClient, auth: str, name: str = "Draft Flow") -> str:
    """Create a draft workflow without publishing."""
    wf_res = client.post(
        "/api/v1/workflows",
        headers={"Authorization": auth},
        json={"name": name, "description": "Draft workflow"},
    )
    assert wf_res.status_code == status.HTTP_201_CREATED
    workflow_id = wf_res.json()["id"]

    step_res = client.post(
        f"/api/v1/workflows/{workflow_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "step_one",
            "step_type": "TEXT",
            "title": "Describe issue",
            "step_order": 1,
            "required": True,
            "config": {"min_length": 5, "max_length": 500},
        },
    )
    assert step_res.status_code == status.HTTP_201_CREATED
    return workflow_id


# ===========================================================================
# Merchant Verification Session Creation Tests
# ===========================================================================

def test_create_verification_session_success(client: TestClient, db_session: Session):
    """Test successful verification session creation with complete product and active workflow."""
    _, auth = register_and_auth(client, "merchant_create@test.com", "Acme Store")
    prod_id = create_complete_product(client, auth, "PROD-SUCCESS-01")
    wf_id = create_active_workflow(client, auth, "Return Policy Standard")

    payload = {
        "product_id": prod_id,
        "workflow_id": wf_id,
        "order_id": "ORD-2026-9901",
        "customer_name": "Alice Johnson",
        "customer_contact": "alice@example.com",
        "refund_reason": "Item arrived broken in box",
        "refund_amount": "89.50",
    }
    response = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json=payload,
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()

    # Check structure
    assert data["order_id"] == "ORD-2026-9901"
    assert data["customer_name"] == "Alice Johnson"
    assert data["refund_amount"] == "89.50"
    assert data["status"] == "CREATED"
    assert data["workflow_version"] == 1
    assert data["verification_id"].startswith("VR-")

    # One-time customer link must be present
    assert data["customer_link"] is not None
    assert settings.CUSTOMER_VERIFICATION_BASE_URL.rstrip('/') in data["customer_link"]

    # Verify security: raw token must NOT be in DB, only SHA-256 hash
    raw_token = data["customer_link"].split("/")[-1]
    expected_hash = hash_verification_token(raw_token)

    db_entry = db_session.execute(
        select(VerificationSession).where(VerificationSession.verification_id == data["verification_id"])
    ).scalar_one()

    assert db_entry.customer_token_hash == expected_hash
    assert db_entry.customer_token_hash != raw_token

    # Verify audit event logged
    events = list(db_session.execute(
        select(VerificationEvent).where(VerificationEvent.verification_id == data["verification_id"])
    ).scalars().all())
    assert len(events) == 1
    assert events[0].event_type == VerificationEventType.SESSION_CREATED.value


def test_create_session_fails_with_incomplete_product(client: TestClient):
    """Test session creation fails with HTTP 422 if product lacks 4 reference angles."""
    _, auth = register_and_auth(client, "incomp@test.com")
    prod_id = create_incomplete_product(client, auth, "INCOMP-FAIL-01")
    wf_id = create_active_workflow(client, auth, "Active Flow")

    response = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": prod_id,
            "workflow_id": wf_id,
            "order_id": "ORD-1234",
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "incomplete" in response.json()["detail"].lower()
    assert "LEFT" in response.json()["detail"] or "RIGHT" in response.json()["detail"]


def test_create_session_fails_with_draft_workflow(client: TestClient):
    """Test session creation fails with HTTP 422 if workflow is in DRAFT status."""
    _, auth = register_and_auth(client, "draft_wf@test.com")
    prod_id = create_complete_product(client, auth, "PROD-DRAFT-WF")
    wf_id = create_draft_workflow(client, auth, "Draft Flow")

    response = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": prod_id,
            "workflow_id": wf_id,
            "order_id": "ORD-5678",
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "ACTIVE" in response.json()["detail"]


def test_create_session_fails_with_archived_workflow(client: TestClient):
    """Test session creation fails with HTTP 422 if workflow is ARCHIVED."""
    _, auth = register_and_auth(client, "archived_wf@test.com")
    prod_id = create_complete_product(client, auth, "PROD-ARCH-WF")
    wf_id = create_active_workflow(client, auth, "Archived Flow")

    # Archive the workflow
    client.post(f"/api/v1/workflows/{wf_id}/archive", headers={"Authorization": auth})

    response = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": prod_id,
            "workflow_id": wf_id,
            "order_id": "ORD-9999",
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "ARCHIVED" in response.json()["detail"]


def test_merchant_isolation_for_product_and_workflow(client: TestClient):
    """Test merchant cannot initiate verification with another merchant's product or workflow."""
    _, auth_a = register_and_auth(client, "merchant_a@test.com", "Merchant A")
    _, auth_b = register_and_auth(client, "merchant_b@test.com", "Merchant B")

    prod_a = create_complete_product(client, auth_a, "PROD-A")
    wf_a = create_active_workflow(client, auth_a, "Flow A")

    prod_b = create_complete_product(client, auth_b, "PROD-B")
    wf_b = create_active_workflow(client, auth_b, "Flow B")

    # Merchant B tries to use Merchant A's product -> 404
    res1 = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth_b},
        json={"product_id": prod_a, "workflow_id": wf_b, "order_id": "ORD-B"},
    )
    assert res1.status_code == status.HTTP_404_NOT_FOUND

    # Merchant B tries to use Merchant A's workflow -> 404
    res2 = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth_b},
        json={"product_id": prod_b, "workflow_id": wf_a, "order_id": "ORD-B"},
    )
    assert res2.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# Merchant Session Management Tests (List, Get, Cancel)
# ===========================================================================

def test_list_sessions_and_token_omission(client: TestClient):
    """Test listing verification sessions omits raw customer link."""
    _, auth = register_and_auth(client, "list_sess@test.com")
    prod_id = create_complete_product(client, auth, "PROD-LIST")
    wf_id = create_active_workflow(client, auth, "Flow List")

    # Create two sessions
    client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={"product_id": prod_id, "workflow_id": wf_id, "order_id": "ORD-L1"},
    )
    client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={"product_id": prod_id, "workflow_id": wf_id, "order_id": "ORD-L2"},
    )

    list_res = client.get("/api/v1/verifications", headers={"Authorization": auth})
    assert list_res.status_code == status.HTTP_200_OK
    items = list_res.json()
    assert len(items) == 2
    for item in items:
        # customer_link is None in list view for security
        assert item["customer_link"] is None


def test_get_session_by_identifier_and_merchant_isolation(client: TestClient):
    """Test retrieving session by verification_id and verify isolation."""
    _, auth_a = register_and_auth(client, "m_a@test.com")
    _, auth_b = register_and_auth(client, "m_b@test.com")

    prod_id = create_complete_product(client, auth_a, "PROD-GET")
    wf_id = create_active_workflow(client, auth_a, "Flow Get")

    create_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth_a},
        json={"product_id": prod_id, "workflow_id": wf_id, "order_id": "ORD-GET-1"},
    )
    v_id = create_res.json()["verification_id"]
    db_id = create_res.json()["id"]

    # Merchant A can get by verification_id
    get_v = client.get(f"/api/v1/verifications/{v_id}", headers={"Authorization": auth_a})
    assert get_v.status_code == status.HTTP_200_OK
    assert get_v.json()["order_id"] == "ORD-GET-1"

    # Merchant A can get by database id
    get_db = client.get(f"/api/v1/verifications/{db_id}", headers={"Authorization": auth_a})
    assert get_db.status_code == status.HTTP_200_OK

    # Merchant B cannot access Merchant A's session -> 404
    get_other = client.get(f"/api/v1/verifications/{v_id}", headers={"Authorization": auth_b})
    assert get_other.status_code == status.HTTP_404_NOT_FOUND


def test_cancel_session_and_audit_log(client: TestClient, db_session: Session):
    """Test merchant can cancel session, which logs audit event and blocks re-cancellation."""
    _, auth = register_and_auth(client, "cancel_test@test.com")
    prod_id = create_complete_product(client, auth, "PROD-CANCEL")
    wf_id = create_active_workflow(client, auth, "Flow Cancel")

    create_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={"product_id": prod_id, "workflow_id": wf_id, "order_id": "ORD-CANCEL-1"},
    )
    v_id = create_res.json()["verification_id"]

    # Cancel session
    cancel_res = client.post(
        f"/api/v1/verifications/{v_id}/cancel",
        headers={"Authorization": auth},
    )
    assert cancel_res.status_code == status.HTTP_200_OK
    assert cancel_res.json()["status"] == "CANCELLED"

    # Cancelling again fails with 400
    cancel_again = client.post(
        f"/api/v1/verifications/{v_id}/cancel",
        headers={"Authorization": auth},
    )
    assert cancel_again.status_code == status.HTTP_400_BAD_REQUEST

    # Verify audit event
    events = list(db_session.execute(
        select(VerificationEvent)
        .where(
            VerificationEvent.verification_id == v_id,
            VerificationEvent.event_type == VerificationEventType.SESSION_CANCELLED.value,
        )
    ).scalars().all())
    assert len(events) == 1


# ===========================================================================
# Public Customer Verification Flow Tests
# ===========================================================================

def test_public_customer_overview_and_privacy_guarantee(client: TestClient):
    """Test public endpoint returns sanitized info and never exposes merchant email, hash, or IDs."""
    _, auth = register_and_auth(client, "secret_owner@acme.com", "Acme Retail Co")
    prod_id = create_complete_product(client, auth, "PROD-PUB-1")
    wf_id = create_active_workflow(client, auth, "Return Inspection Flow")

    create_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": prod_id,
            "workflow_id": wf_id,
            "order_id": "ORD-PUB-100",
            "customer_name": "John Doe",
            "refund_reason": "Scratched frame",
        },
    )
    raw_token = create_res.json()["customer_link"].split("/")[-1]

    # Public GET /api/v1/public/verifications/{token}
    pub_res = client.get(f"/api/v1/public/verifications/{raw_token}")
    assert pub_res.status_code == status.HTTP_200_OK
    pub_data = pub_res.json()

    assert pub_data["verification_id"] == create_res.json()["verification_id"]
    assert pub_data["merchant"]["business_name"] == "Acme Retail Co"
    assert pub_data["product"]["name"] == "Reference Product"
    assert pub_data["workflow"]["name"] == "Return Inspection Flow"
    assert pub_data["status"] == "CREATED"

    # Strict privacy verification
    assert "email" not in str(pub_data)
    assert "secret_owner@acme.com" not in str(pub_data)
    assert "customer_token_hash" not in pub_data
    assert "password" not in str(pub_data)
    assert "password_hash" not in str(pub_data)


def test_public_customer_start_workflow(client: TestClient, db_session: Session):
    """Test customer starting verification transitions session to IN_PROGRESS idempotently."""
    _, auth = register_and_auth(client, "start_flow@test.com", "Start Flow Merchant")
    prod_id = create_complete_product(client, auth, "PROD-START")
    wf_id = create_active_workflow(client, auth, "Start Workflow")

    create_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={"product_id": prod_id, "workflow_id": wf_id, "order_id": "ORD-START-1"},
    )
    raw_token = create_res.json()["customer_link"].split("/")[-1]
    v_id = create_res.json()["verification_id"]

    # Customer starts verification
    start_res = client.post(f"/api/v1/public/verifications/{raw_token}/start")
    assert start_res.status_code == status.HTTP_200_OK
    data = start_res.json()
    assert data["status"] == "IN_PROGRESS"
    started_at_1 = data["started_at"]
    assert started_at_1 is not None

    # Idempotent re-start
    start_res_2 = client.post(f"/api/v1/public/verifications/{raw_token}/start")
    assert start_res_2.status_code == status.HTTP_200_OK
    assert start_res_2.json()["started_at"] == started_at_1

    # Audit event verified
    events = list(db_session.execute(
        select(VerificationEvent)
        .where(
            VerificationEvent.verification_id == v_id,
            VerificationEvent.event_type == VerificationEventType.SESSION_STARTED.value,
        )
    ).scalars().all())
    assert len(events) == 1


def test_public_customer_workflow_snapshot_frozen(client: TestClient):
    """Test customer receives the frozen workflow snapshot even if merchant modifies or archives workflow later."""
    _, auth = register_and_auth(client, "freeze_test@test.com", "Freeze Merchant")
    prod_id = create_complete_product(client, auth, "PROD-FREEZE")
    wf_id = create_active_workflow(client, auth, "Original Workflow")

    # Create session
    create_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={"product_id": prod_id, "workflow_id": wf_id, "order_id": "ORD-FREEZE-1"},
    )
    raw_token = create_res.json()["customer_link"].split("/")[-1]

    # Merchant archives the workflow after session creation
    client.post(f"/api/v1/workflows/{wf_id}/archive", headers={"Authorization": auth})

    # Customer can still retrieve workflow definition from frozen snapshot
    wf_res = client.get(f"/api/v1/public/verifications/{raw_token}/workflow")
    assert wf_res.status_code == status.HTTP_200_OK
    wf_data = wf_res.json()
    assert wf_data["workflow_name"] == "Original Workflow"
    assert wf_data["workflow_version"] == 1
    assert len(wf_data["steps"]) == 1
    assert wf_data["steps"][0]["step_key"] == "damage_reason"


def test_public_access_invalid_token(client: TestClient):
    """Test non-existent customer token returns HTTP 404."""
    response = client.get("/api/v1/public/verifications/completely-invalid-token-12345")
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_public_access_cancelled_session_returns_410(client: TestClient):
    """Test accessing a cancelled verification session returns HTTP 410 Gone on all customer routes."""
    _, auth = register_and_auth(client, "cancelled_public@test.com")
    prod_id = create_complete_product(client, auth, "PROD-C-PUB")
    wf_id = create_active_workflow(client, auth, "Flow C Pub")

    create_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={"product_id": prod_id, "workflow_id": wf_id, "order_id": "ORD-C-PUB"},
    )
    raw_token = create_res.json()["customer_link"].split("/")[-1]
    v_id = create_res.json()["verification_id"]

    # Merchant cancels session
    client.post(f"/api/v1/verifications/{v_id}/cancel", headers={"Authorization": auth})

    # Customer landing page -> 410
    assert client.get(f"/api/v1/public/verifications/{raw_token}").status_code == status.HTTP_410_GONE

    # Customer start -> 410
    assert client.post(f"/api/v1/public/verifications/{raw_token}/start").status_code == status.HTTP_410_GONE

    # Customer workflow -> 410
    assert client.get(f"/api/v1/public/verifications/{raw_token}/workflow").status_code == status.HTTP_410_GONE


def test_public_access_expired_session_returns_410(client: TestClient, db_session: Session):
    """Test accessing an expired verification session transitions status and returns HTTP 410 Gone."""
    _, auth = register_and_auth(client, "expired_public@test.com")
    prod_id = create_complete_product(client, auth, "PROD-EXP-PUB")
    wf_id = create_active_workflow(client, auth, "Flow Exp Pub")

    create_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={"product_id": prod_id, "workflow_id": wf_id, "order_id": "ORD-EXP-PUB"},
    )
    raw_token = create_res.json()["customer_link"].split("/")[-1]
    v_id = create_res.json()["verification_id"]

    # Manually expire the session in the database
    db_entry = db_session.execute(
        select(VerificationSession).where(VerificationSession.verification_id == v_id)
    ).scalar_one()
    db_entry.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    # Customer access -> 410 Gone
    res = client.get(f"/api/v1/public/verifications/{raw_token}")
    assert res.status_code == status.HTTP_410_GONE
    assert "expired" in res.json()["detail"].lower()

    # Session status is updated to EXPIRED in database
    db_session.refresh(db_entry)
    assert db_entry.status == SessionStatus.EXPIRED.value

    # SESSION_EXPIRED audit event recorded
    events = list(db_session.execute(
        select(VerificationEvent)
        .where(
            VerificationEvent.verification_id == v_id,
            VerificationEvent.event_type == VerificationEventType.SESSION_EXPIRED.value,
        )
    ).scalars().all())
    assert len(events) == 1
