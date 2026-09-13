"""Regression tests ensuring merchant authentication and tenant isolation for GET /api/v1/verifications.

Validates:
1. Authenticated merchant requests to GET /api/v1/verifications consistently return 200 OK
   with the merchant's sessions instead of 401 Unauthorized.
2. Requests without Authorization header return 401 Unauthorized with exact detail message.
3. Requests with invalid / malformed JWT return 401 Unauthorized.
4. Cross-merchant tenant isolation: Merchant A's sessions are never visible to Merchant B.
"""
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.models.product import Product
from app.models.workflow import Workflow, WorkflowStatus
from app.models.verification import VerificationSession, SessionStatus
from app.core.security import create_access_token


def register_and_auth(client: TestClient, email: str, name: str = "Merchant") -> tuple[str, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"business_name": name, "email": email, "password": "Password123!"},
    )
    assert reg.status_code == status.HTTP_201_CREATED, reg.text
    merchant_id = reg.json()["id"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    assert login.status_code == status.HTTP_200_OK
    token = login.json()["access_token"]
    return merchant_id, f"Bearer {token}"


def test_get_verifications_authenticated_returns_sessions(
    client: TestClient,
    db_session: Session,
):
    """Verify authenticated merchant with valid JWT gets 200 OK and their verification sessions."""
    m_id, auth_header = register_and_auth(client, "merchant_auth_test@example.com", "Auth Test Merchant")

    # Create dummy product and workflow in DB
    prod = Product(
        merchant_id=m_id,
        name="Auth Test Widget",
        sku="SKU-AUTH-001",
        price=49.99,
    )
    wf = Workflow(
        merchant_id=m_id,
        name="Default Flow",
        status=WorkflowStatus.ACTIVE.value,
    )
    db_session.add_all([prod, wf])
    db_session.commit()

    expiry = datetime.now(timezone.utc) + timedelta(days=7)

    # Create two verification sessions for this merchant
    session1 = VerificationSession(
        verification_id=f"VR-2026-{uuid.uuid4().hex[:8].upper()}",
        merchant_id=m_id,
        product_id=prod.id,
        workflow_id=wf.id,
        workflow_snapshot_json={"steps": []},
        customer_token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        expires_at=expiry,
        order_id="ORD-TEST-AUTH-001",
        customer_name="Test Customer A",
        status=SessionStatus.CREATED.value,
    )
    session2 = VerificationSession(
        verification_id=f"VR-2026-{uuid.uuid4().hex[:8].upper()}",
        merchant_id=m_id,
        product_id=prod.id,
        workflow_id=wf.id,
        workflow_snapshot_json={"steps": []},
        customer_token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        expires_at=expiry,
        order_id="ORD-TEST-AUTH-002",
        customer_name="Test Customer B",
        status=SessionStatus.IN_PROGRESS.value,
    )
    db_session.add_all([session1, session2])
    db_session.commit()

    # Call GET /api/v1/verifications with valid auth headers
    headers = {"Authorization": auth_header}
    response = client.get("/api/v1/verifications?page=1&page_size=20", headers=headers)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 2

    order_ids = [item["order_id"] for item in data["items"]]
    assert "ORD-TEST-AUTH-001" in order_ids
    assert "ORD-TEST-AUTH-002" in order_ids


def test_get_verifications_unauthenticated_returns_401(client: TestClient):
    """Verify requesting GET /api/v1/verifications without Authorization header returns 401."""
    response = client.get("/api/v1/verifications?page=1&page_size=20")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "detail" in response.json()
    assert response.json()["detail"] == "Authentication credentials were not provided"


def test_get_verifications_invalid_token_returns_401(client: TestClient):
    """Verify requesting GET /api/v1/verifications with an invalid Bearer token returns 401."""
    headers = {"Authorization": "Bearer invalid.garbage.token"}
    response = client.get("/api/v1/verifications?page=1&page_size=20", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid or expired authentication token"


def test_cross_merchant_tenant_isolation(
    client: TestClient,
    db_session: Session,
):
    """Verify Merchant A cannot view sessions belonging to Merchant B."""
    m_a_id, auth_a = register_and_auth(client, "merchant_iso_a@example.com", "Merchant Alpha")
    m_b_id, auth_b = register_and_auth(client, "merchant_iso_b@example.com", "Merchant Beta")

    # Create dummy products and workflows
    prod_a = Product(merchant_id=m_a_id, name="Prod A", sku="SKU-A", price=10.0)
    wf_a = Workflow(merchant_id=m_a_id, name="Flow A", status=WorkflowStatus.ACTIVE.value)
    prod_b = Product(merchant_id=m_b_id, name="Prod B", sku="SKU-B", price=20.0)
    wf_b = Workflow(merchant_id=m_b_id, name="Flow B", status=WorkflowStatus.ACTIVE.value)
    db_session.add_all([prod_a, wf_a, prod_b, wf_b])
    db_session.commit()

    expiry = datetime.now(timezone.utc) + timedelta(days=7)

    # Create verification session for Merchant B
    session_b = VerificationSession(
        verification_id=f"VR-2026-{uuid.uuid4().hex[:8].upper()}",
        merchant_id=m_b_id,
        product_id=prod_b.id,
        workflow_id=wf_b.id,
        workflow_snapshot_json={"steps": []},
        customer_token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        expires_at=expiry,
        order_id="ORD-MERCHANT-B-SECRET",
        customer_name="Merchant B Secret Customer",
        status=SessionStatus.CREATED.value,
    )
    # Create verification session for Merchant A
    session_a = VerificationSession(
        verification_id=f"VR-2026-{uuid.uuid4().hex[:8].upper()}",
        merchant_id=m_a_id,
        product_id=prod_a.id,
        workflow_id=wf_a.id,
        workflow_snapshot_json={"steps": []},
        customer_token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        expires_at=expiry,
        order_id="ORD-MERCHANT-A-PUBLIC",
        customer_name="Merchant A Customer",
        status=SessionStatus.CREATED.value,
    )
    db_session.add_all([session_b, session_a])
    db_session.commit()

    # Merchant A makes authenticated request
    headers_a = {"Authorization": auth_a}
    resp_a = client.get("/api/v1/verifications?page=1&page_size=20", headers=headers_a)
    assert resp_a.status_code == status.HTTP_200_OK
    items_a = resp_a.json()["items"]
    order_ids_a = [i["order_id"] for i in items_a]
    assert "ORD-MERCHANT-A-PUBLIC" in order_ids_a
    assert "ORD-MERCHANT-B-SECRET" not in order_ids_a

    # Merchant B makes authenticated request
    headers_b = {"Authorization": auth_b}
    resp_b = client.get("/api/v1/verifications?page=1&page_size=20", headers=headers_b)
    assert resp_b.status_code == status.HTTP_200_OK
    items_b = resp_b.json()["items"]
    order_ids_b = [i["order_id"] for i in items_b]
    assert "ORD-MERCHANT-B-SECRET" in order_ids_b
    assert "ORD-MERCHANT-A-PUBLIC" not in order_ids_b
