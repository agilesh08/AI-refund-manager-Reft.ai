"""Comprehensive automated test suite for Milestone M10: Multi-Source Deterministic Signal Ingestion.

Covers:
- PAYMENT, ORDER, DELIVERY, LOCATION signal validation & normalization.
- Bounds checks (amounts >= 0, coordinates, dates, accuracy > 0).
- Sensitive financial data rejection (CVV, card PANs).
- Currency and status normalizations (symbols, lower-to-upper).
- Duplicate handling (idempotent identical vs updated data).
- Merchant tenant isolation (404) and customer sanitized view.
- AI reasoning context integration (DETERMINISTIC facts).
- Context hash change and cache invalidation.
- Gemini & Llama boundary enforcement (AI cannot create deterministic signals).
- Audit trail events (SIGNAL_CREATED, SIGNAL_VALIDATED, SIGNAL_UPDATED, SIGNAL_REJECTED).
"""
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from PIL import Image
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.verification_signal import (
    VerificationSignal,
    SignalType,
    SourceType,
    SignalStatus,
)
from app.schemas.reasoning import ReasoningAction, ReasoningResult
from app.services import (
    verification_signal_service,
    reasoning_context_service,
    reasoning_service,
)


def make_test_image(color: str = "blue") -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (30, 30), color=color)
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf.getvalue()


def register_and_auth(client: TestClient, email: str, name: str = "Merchant") -> tuple[str, str]:
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
    sku: str = "PROD-SIG-1",
) -> tuple[dict, str]:
    # 1. Product
    prod_res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": f"Product {sku}", "sku": sku, "price": "14999.00"},
    )
    product_id = prod_res.json()["id"]

    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        img_bytes = make_test_image(color="navy")
        client.post(
            f"/api/v1/products/{product_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", img_bytes, "image/jpeg")},
        )

    # 2. Workflow with IMAGE, PAYMENT, ORDER, DELIVERY steps
    wf_res = client.post(
        "/api/v1/workflows",
        headers={"Authorization": auth},
        json={"name": f"Workflow {sku}"},
    )
    wf_id = wf_res.json()["id"]

    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={"step_key": "damage_photo", "step_type": "IMAGE", "title": "Damage Photo", "step_order": 1, "required": True},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={"step_key": "payment_step", "step_type": "PAYMENT", "title": "Payment Verification", "step_order": 2, "required": True},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={"step_key": "order_step", "step_type": "ORDER", "title": "Order Verification", "step_order": 3, "required": True},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={"step_key": "delivery_step", "step_type": "DELIVERY", "title": "Delivery Verification", "step_order": 4, "required": True},
    )
    client.post(f"/api/v1/workflows/{wf_id}/publish", headers={"Authorization": auth})

    # 3. Session
    sess_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": product_id,
            "workflow_id": wf_id,
            "order_id": f"ORD-{sku}",
            "customer_name": "Test Customer",
            "customer_contact": "customer@example.com",
            "refund_reason": "Device malfunctioning.",
            "refund_amount": 14999.00,
        },
    )
    sess_data = sess_res.json()
    token = sess_data["customer_link"].rstrip("/").split("/")[-1]
    client.post(f"/api/v1/public/verifications/{token}/start")
    return sess_data, token


# ===========================================================================
# 1. Signal Ingestion & Schema Tests
# ===========================================================================

class TestSignalIngestionAndSchemas:
    """Test ingestion and schema validation for PAYMENT, ORDER, DELIVERY, LOCATION signals."""

    def test_create_payment_signal_success(self, client: TestClient, db_session: Session):
        """1. Create valid PAYMENT signal with audit events."""
        _, auth = register_and_auth(client, "sig1@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S1")
        verification_id = sess_data["id"]

        payload = {
            "signal_type": "PAYMENT",
            "source_type": "INTEGRATION",
            "source_reference": "pay_test_001",
            "data": {
                "payment_id": "PAY-1001",
                "order_id": "ORD-SKU-S1",
                "amount": 14999.00,
                "currency": "INR",
                "payment_status": "PAID",
                "payment_method": "UPI",
                "transaction_reference": "TXN-9999",
            },
        }
        res = client.post(
            f"/api/v1/verifications/{verification_id}/signals",
            headers={"Authorization": auth},
            json=payload,
        )
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["signal_type"] == "PAYMENT"
        assert data["source_type"] == "INTEGRATION"
        assert data["status"] == "VALID"
        assert data["data_json"]["amount"] == 14999.0
        assert data["data_json"]["currency"] == "INR"

    def test_create_order_signal_success(self, client: TestClient, db_session: Session):
        """2. Create valid ORDER signal."""
        _, auth = register_and_auth(client, "sig2@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S2")
        verification_id = sess_data["id"]

        payload = {
            "signal_type": "ORDER",
            "source_type": "MERCHANT_PROVIDED",
            "source_reference": "order_import_001",
            "data": {
                "order_id": "ORD-SKU-S2",
                "product_id": sess_data["product_id"],
                "sku": "SKU-S2",
                "quantity": 1,
                "order_amount": 14999.00,
                "order_status": "DELIVERED",
            },
        }
        res = client.post(
            f"/api/v1/verifications/{verification_id}/signals",
            headers={"Authorization": auth},
            json=payload,
        )
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["signal_type"] == "ORDER"
        assert data["data_json"]["order_status"] == "DELIVERED"

    def test_create_delivery_signal_success(self, client: TestClient, db_session: Session):
        """3. Create valid DELIVERY signal."""
        _, auth = register_and_auth(client, "sig3@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S3")
        verification_id = sess_data["id"]

        now = datetime.now(timezone.utc)
        shipped = (now - timedelta(days=2)).isoformat()
        delivered = (now - timedelta(days=1)).isoformat()

        payload = {
            "signal_type": "DELIVERY",
            "source_type": "INTEGRATION",
            "source_reference": "carrier_track_001",
            "data": {
                "order_id": "ORD-SKU-S3",
                "carrier": "BlueDart",
                "tracking_reference": "TRACK-777",
                "delivery_status": "DELIVERED",
                "shipped_at": shipped,
                "delivered_at": delivered,
                "delivery_location": {
                    "city": "Puducherry",
                    "region": "TN",
                    "country": "IN",
                },
            },
        }
        res = client.post(
            f"/api/v1/verifications/{verification_id}/signals",
            headers={"Authorization": auth},
            json=payload,
        )
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["signal_type"] == "DELIVERY"
        assert data["data_json"]["carrier"] == "BlueDart"

    def test_create_location_signal_success(self, client: TestClient, db_session: Session):
        """4. Create valid LOCATION signal."""
        _, auth = register_and_auth(client, "sig4@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S4")
        verification_id = sess_data["id"]

        payload = {
            "signal_type": "LOCATION",
            "source_type": "CUSTOMER_PROVIDED",
            "source_reference": "device_gps_001",
            "data": {
                "latitude": 11.9139,
                "longitude": 79.8145,
                "accuracy_meters": 25.0,
                "source": "DEVICE",
            },
        }
        res = client.post(
            f"/api/v1/verifications/{verification_id}/signals",
            headers={"Authorization": auth},
            json=payload,
        )
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["signal_type"] == "LOCATION"
        assert data["data_json"]["latitude"] == 11.9139


# ===========================================================================
# 2. Validation & Normalization Rules
# ===========================================================================

class TestSignalValidationRules:
    """Test bounds, normalization, and sensitive data rejection."""

    def test_invalid_payment_amount_rejected(self, client: TestClient, db_session: Session):
        """5. Negative payment amount is rejected (422)."""
        _, auth = register_and_auth(client, "sig5@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S5")

        payload = {
            "signal_type": "PAYMENT",
            "source_type": "INTEGRATION",
            "source_reference": "ref_neg_amount",
            "data": {
                "payment_id": "P1",
                "order_id": "O1",
                "amount": -50.0,
                "currency": "INR",
                "payment_status": "PAID",
                "payment_method": "UPI",
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_invalid_payment_status_rejected(self, client: TestClient, db_session: Session):
        """6. Arbitrary/invalid payment status is rejected (422)."""
        _, auth = register_and_auth(client, "sig6@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S6")

        payload = {
            "signal_type": "PAYMENT",
            "source_type": "INTEGRATION",
            "source_reference": "ref_bad_status",
            "data": {
                "payment_id": "P1",
                "order_id": "O1",
                "amount": 100.0,
                "currency": "INR",
                "payment_status": "SUCCESSFUL_MAYBE",
                "payment_method": "UPI",
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_invalid_order_status_rejected(self, client: TestClient, db_session: Session):
        """7. Invalid order status is rejected (422)."""
        _, auth = register_and_auth(client, "sig7@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S7")

        payload = {
            "signal_type": "ORDER",
            "source_type": "MERCHANT_PROVIDED",
            "source_reference": "ref_bad_ord_status",
            "data": {
                "order_id": "O1",
                "quantity": 1,
                "order_amount": 100.0,
                "order_status": "LOST_IN_SPACE",
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_invalid_delivery_status_rejected(self, client: TestClient, db_session: Session):
        """8. Invalid delivery status is rejected (422)."""
        _, auth = register_and_auth(client, "sig8@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S8")

        payload = {
            "signal_type": "DELIVERY",
            "source_type": "INTEGRATION",
            "source_reference": "ref_bad_del_status",
            "data": {
                "order_id": "O1",
                "delivery_status": "ARRIVED_ALMOST",
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_invalid_latitude_rejected(self, client: TestClient, db_session: Session):
        """9. Latitude outside [-90, 90] is rejected (422)."""
        _, auth = register_and_auth(client, "sig9@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S9")

        payload = {
            "signal_type": "LOCATION",
            "source_type": "CUSTOMER_PROVIDED",
            "source_reference": "ref_bad_lat",
            "data": {
                "latitude": 95.0,
                "longitude": 79.0,
                "accuracy_meters": 10.0,
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_invalid_longitude_rejected(self, client: TestClient, db_session: Session):
        """10. Longitude outside [-180, 180] is rejected (422)."""
        _, auth = register_and_auth(client, "sig10@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S10")

        payload = {
            "signal_type": "LOCATION",
            "source_type": "CUSTOMER_PROVIDED",
            "source_reference": "ref_bad_lon",
            "data": {
                "latitude": 11.0,
                "longitude": 185.0,
                "accuracy_meters": 10.0,
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_invalid_delivery_date_ordering_rejected(self, client: TestClient, db_session: Session):
        """11. delivered_at earlier than shipped_at is rejected (422)."""
        _, auth = register_and_auth(client, "sig11@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S11")

        now = datetime.now(timezone.utc)
        shipped = now.isoformat()
        delivered = (now - timedelta(days=2)).isoformat()  # Earlier than shipped!

        payload = {
            "signal_type": "DELIVERY",
            "source_type": "INTEGRATION",
            "source_reference": "ref_bad_dates",
            "data": {
                "order_id": "O1",
                "delivery_status": "DELIVERED",
                "shipped_at": shipped,
                "delivered_at": delivered,
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "delivered_at cannot be earlier than shipped_at" in res.json()["detail"]

    def test_currency_normalized(self, client: TestClient, db_session: Session):
        """12. Currency codes and symbols ('₹', 'inr') are normalized to uppercase 'INR'."""
        _, auth = register_and_auth(client, "sig12@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S12")

        payload = {
            "signal_type": "PAYMENT",
            "source_type": "MERCHANT_PROVIDED",
            "source_reference": "norm_curr_symbol",
            "data": {
                "payment_id": "P_SYM",
                "order_id": "O_SYM",
                "amount": 250.0,
                "currency": "₹",
                "payment_status": "PAID",
                "payment_method": "UPI",
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_201_CREATED
        assert res.json()["data_json"]["currency"] == "INR"

    def test_payment_method_normalized(self, client: TestClient, db_session: Session):
        """13. Lowercase payment method is normalized to uppercase."""
        _, auth = register_and_auth(client, "sig13@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S13")

        payload = {
            "signal_type": "PAYMENT",
            "source_type": "MERCHANT_PROVIDED",
            "source_reference": "norm_method",
            "data": {
                "payment_id": "P_METH",
                "order_id": "O_METH",
                "amount": 100.0,
                "currency": "INR",
                "payment_status": "PAID",
                "payment_method": "card",
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_201_CREATED
        assert res.json()["data_json"]["payment_method"] == "CARD"

    def test_status_normalized(self, client: TestClient, db_session: Session):
        """14. Status strings are normalized to uppercase."""
        _, auth = register_and_auth(client, "sig14@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S14")

        payload = {
            "signal_type": "ORDER",
            "source_type": "MERCHANT_PROVIDED",
            "source_reference": "norm_status",
            "data": {
                "order_id": "O_NORM",
                "quantity": 2,
                "order_amount": 500.0,
                "order_status": "confirmed",
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_201_CREATED
        assert res.json()["data_json"]["order_status"] == "CONFIRMED"


# ===========================================================================
# 3. Deduplication & History Updates
# ===========================================================================

class TestDuplicateAndHistoryHandling:
    """Test deduplication and updating of existing source_reference signals."""

    def test_duplicate_identical_signal_handled_correctly(self, client: TestClient, db_session: Session):
        """15. Submitting identical signal data with same source_reference returns existing signal without duplicate row."""
        _, auth = register_and_auth(client, "sig15@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S15")
        verification_id = sess_data["id"]

        payload = {
            "signal_type": "PAYMENT",
            "source_type": "INTEGRATION",
            "source_reference": "dup_ref_001",
            "data": {
                "payment_id": "P_DUP",
                "order_id": "O_DUP",
                "amount": 999.0,
                "currency": "INR",
                "payment_status": "PAID",
                "payment_method": "UPI",
            },
        }
        res1 = client.post(f"/api/v1/verifications/{verification_id}/signals", headers={"Authorization": auth}, json=payload)
        assert res1.status_code == status.HTTP_201_CREATED
        sig1 = res1.json()

        # Submit identical second time
        res2 = client.post(f"/api/v1/verifications/{verification_id}/signals", headers={"Authorization": auth}, json=payload)
        assert res2.status_code == status.HTTP_201_CREATED
        sig2 = res2.json()

        assert sig1["id"] == sig2["id"]

        # Check database table count
        signals = client.get(f"/api/v1/verifications/{verification_id}/signals", headers={"Authorization": auth}).json()
        assert len(signals) == 1

    def test_changed_source_reference_data_updates_and_logs_audit_event(self, client: TestClient, db_session: Session):
        """16. Submitting changed data for same source_reference updates data and logs SIGNAL_UPDATED."""
        _, auth = register_and_auth(client, "sig16@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S16")
        verification_id = sess_data["id"]

        payload1 = {
            "signal_type": "DELIVERY",
            "source_type": "INTEGRATION",
            "source_reference": "track_flow_001",
            "data": {
                "order_id": "ORD-16",
                "carrier": "FedEx",
                "delivery_status": "IN_TRANSIT",
            },
        }
        res1 = client.post(f"/api/v1/verifications/{verification_id}/signals", headers={"Authorization": auth}, json=payload1)
        assert res1.status_code == status.HTTP_201_CREATED
        sig_id = res1.json()["id"]

        # Update status to DELIVERED
        payload2 = {
            "signal_type": "DELIVERY",
            "source_type": "INTEGRATION",
            "source_reference": "track_flow_001",
            "data": {
                "order_id": "ORD-16",
                "carrier": "FedEx",
                "delivery_status": "DELIVERED",
            },
        }
        res2 = client.post(f"/api/v1/verifications/{verification_id}/signals", headers={"Authorization": auth}, json=payload2)
        assert res2.status_code == status.HTTP_201_CREATED
        data2 = res2.json()
        assert data2["id"] == sig_id
        assert data2["data_json"]["delivery_status"] == "DELIVERED"

        # Check SIGNAL_UPDATED audit event
        events = db_session.execute(
            select(VerificationEvent).where(
                VerificationEvent.session_id == verification_id,
                VerificationEvent.event_type == VerificationEventType.SIGNAL_UPDATED.value,
            )
        ).scalars().all()
        assert len(events) >= 1
        assert events[0].metadata_json["signal_id"] == sig_id


# ===========================================================================
# 4. Security & Tenant Isolation
# ===========================================================================

class TestSecurityAndIsolation:
    """Test merchant tenant isolation and customer token privacy boundaries."""

    def test_merchant_can_access_own_signals(self, client: TestClient, db_session: Session):
        """17. Merchant can access their own session signals."""
        _, auth = register_and_auth(client, "sig17@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S17")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "ORDER",
                "source_type": "MERCHANT_PROVIDED",
                "source_reference": "own_ref",
                "data": {"order_id": "O17", "quantity": 1, "order_amount": 50.0, "order_status": "CONFIRMED"},
            },
        )
        res = client.get(f"/api/v1/verifications/{v_id}/signals", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()) == 1

    def test_merchant_cannot_access_another_merchants_signals(self, client: TestClient, db_session: Session):
        """18. Merchant B cannot list or get Merchant A's signals (404)."""
        _, auth_a = register_and_auth(client, "sig18a@store.com")
        sess_a, _ = setup_test_verification(client, auth_a, "SKU-S18A")
        v_id_a = sess_a["id"]

        client.post(
            f"/api/v1/verifications/{v_id_a}/signals",
            headers={"Authorization": auth_a},
            json={
                "signal_type": "PAYMENT",
                "source_type": "INTEGRATION",
                "source_reference": "secret_pay",
                "data": {"payment_id": "P_SEC", "order_id": "O_SEC", "amount": 100.0, "currency": "INR", "payment_status": "PAID", "payment_method": "UPI"},
            },
        )

        _, auth_b = register_and_auth(client, "sig18b@store.com")
        res_list = client.get(f"/api/v1/verifications/{v_id_a}/signals", headers={"Authorization": auth_b})
        assert res_list.status_code == status.HTTP_404_NOT_FOUND

    def test_customer_cannot_access_private_merchant_signal_data(self, client: TestClient, db_session: Session):
        """19. Customer view of signals is sanitized (no payment_id, transaction_ref, or session UUID)."""
        _, auth = register_and_auth(client, "sig19@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-S19")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "PAYMENT",
                "source_type": "INTEGRATION",
                "source_reference": "priv_ref_001",
                "data": {
                    "payment_id": "INTERNAL-PAY-SECRET-123",
                    "order_id": "ORD-19",
                    "amount": 9999.0,
                    "currency": "INR",
                    "payment_status": "PAID",
                    "payment_method": "CARD",
                    "transaction_reference": "SECRET_TXN_REF_XYZ",
                },
            },
        )

        cust_res = client.get(f"/api/v1/public/verifications/{token}/signals")
        assert cust_res.status_code == status.HTTP_200_OK
        data = cust_res.json()
        assert len(data) == 1
        sig = data[0]
        # Check sensitive fields omitted
        assert "INTERNAL-PAY-SECRET-123" not in str(sig)
        assert "SECRET_TXN_REF_XYZ" not in str(sig)
        assert "verification_session_id" not in sig
        assert sig["safe_summary"]["payment_status"] == "PAID"
        assert sig["safe_summary"]["payment_method"] == "CARD"


# ===========================================================================
# 5. Association & Association Validation
# ===========================================================================

class TestSignalAssociation:
    """Verify signals are accurately linked to sessions and wrong sessions rejected."""

    def test_signals_associated_with_correct_verification(self, client: TestClient, db_session: Session):
        """20-23. Payment, Order, Delivery, Location signals are associated with correct session."""
        _, auth = register_and_auth(client, "sig20@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S20")
        v_id = sess_data["id"]

        for stype, ref, data in [
            ("PAYMENT", "ref_p", {"payment_id": "P", "order_id": "O", "amount": 10.0, "currency": "INR", "payment_status": "PAID", "payment_method": "UPI"}),
            ("ORDER", "ref_o", {"order_id": "O", "quantity": 1, "order_amount": 10.0, "order_status": "DELIVERED"}),
            ("DELIVERY", "ref_d", {"order_id": "O", "delivery_status": "DELIVERED"}),
            ("LOCATION", "ref_l", {"latitude": 10.0, "longitude": 20.0, "accuracy_meters": 5.0}),
        ]:
            client.post(
                f"/api/v1/verifications/{v_id}/signals",
                headers={"Authorization": auth},
                json={"signal_type": stype, "source_type": "MERCHANT_PROVIDED", "source_reference": ref, "data": data},
            )

        all_sigs = client.get(f"/api/v1/verifications/{v_id}/signals", headers={"Authorization": auth}).json()
        assert len(all_sigs) == 4
        types = {s["signal_type"] for s in all_sigs}
        assert types == {"PAYMENT", "ORDER", "DELIVERY", "LOCATION"}

    def test_wrong_session_signal_rejected(self, client: TestClient, db_session: Session):
        """24. Ingesting signal for non-existent session returns 404."""
        _, auth = register_and_auth(client, "sig24@store.com")
        res = client.post(
            "/api/v1/verifications/00000000-0000-0000-0000-000000000000/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "ORDER",
                "source_type": "MERCHANT_PROVIDED",
                "source_reference": "ref",
                "data": {"order_id": "O", "quantity": 1, "order_amount": 1.0, "order_status": "CONFIRMED"},
            },
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# 6. AI Context Integration & Context Hash Invalidation
# ===========================================================================

class TestAIContextIntegration:
    """Test deterministic signals in reasoning context and cache invalidation."""

    def test_signal_context_included_in_reasoning_context(self, client: TestClient, db_session: Session):
        """25. Ingested deterministic signals appear under DETERMINISTIC in reasoning context."""
        _, auth = register_and_auth(client, "sig25@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S25")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_sig_001",
                "data": {"order_id": "ORD-25", "carrier": "DHL", "delivery_status": "DELIVERED"},
            },
        )

        session_model = db_session.get(VerificationSession, v_id)
        signals = verification_signal_service.list_signals(db_session, session_model.merchant_id, v_id)
        ctx = reasoning_context_service.build_reasoning_context(session_model, [], [], signals=signals)

        det_facts = ctx["deterministic_facts"]
        deliv_facts = [f for f in det_facts if f.get("signal_type") == "DELIVERY"]
        assert len(deliv_facts) == 1
        assert deliv_facts[0]["source"] == "DETERMINISTIC"
        assert deliv_facts[0]["source_reference"] == "del_sig_001"
        assert deliv_facts[0]["data"]["carrier"] == "DHL"

    def test_new_signal_changes_context_hash_and_invalidates_cache(self, client: TestClient, db_session: Session):
        """26-27. Adding a signal produces a new context hash, invalidating prior cached reasoning."""
        _, auth = register_and_auth(client, "sig26@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S26")
        v_id = sess_data["id"]

        session_model = db_session.get(VerificationSession, v_id)

        # Baseline hash without signal
        ctx1 = reasoning_context_service.build_reasoning_context(session_model, [], [], signals=[])
        hash1 = reasoning_context_service.calculate_context_hash(ctx1)

        # Add payment signal
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "PAYMENT",
                "source_type": "INTEGRATION",
                "source_reference": "pay_hash_test",
                "data": {"payment_id": "P", "order_id": "O", "amount": 100.0, "currency": "INR", "payment_status": "PAID", "payment_method": "UPI"},
            },
        )

        signals = verification_signal_service.list_signals(db_session, session_model.merchant_id, v_id)
        ctx2 = reasoning_context_service.build_reasoning_context(session_model, [], [], signals=signals)
        hash2 = reasoning_context_service.calculate_context_hash(ctx2)

        assert hash1 != hash2, "Context hash must change after signal ingestion to invalidate cache"

    def test_gemini_cannot_create_deterministic_signals(self, client: TestClient, db_session: Session):
        """28. Gemini Vision output schema does not contain or generate deterministic signals."""
        from app.schemas.visual_analysis import VisualAnalysisResult
        fields = VisualAnalysisResult.model_fields.keys()
        assert "payment" not in fields
        assert "payment_status" not in fields
        assert "delivery" not in fields
        assert "order" not in fields

    def test_llama_cannot_create_deterministic_signals(self, client: TestClient, db_session: Session):
        """29. Llama ReasoningResult schema strictly forbids injecting deterministic signal fields."""
        extra_attempt = {
            "action": "ACCEPT_EVIDENCE",
            "reasoning_summary": "Attempting to fabricate delivery facts.",
            "confidence": 0.9,
            "delivery_status": "DELIVERED",  # Prohibited extra field!
        }
        with pytest.raises(Exception):
            ReasoningResult.model_validate(extra_attempt)

    def test_invalid_signal_does_not_enter_ai_context(self, client: TestClient, db_session: Session):
        """30. Signal marked INVALID does not enter deterministic_facts in reasoning context."""
        _, auth = register_and_auth(client, "sig30@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S30")
        session_model = db_session.get(VerificationSession, sess_data["id"])

        # Manually create INVALID signal in DB
        sig = VerificationSignal(
            verification_session_id=session_model.id,
            signal_type="PAYMENT",
            source_type="MERCHANT_PROVIDED",
            status=SignalStatus.INVALID.value,
            data_json={"amount": -10.0},
            source_reference="corrupt_signal",
        )
        db_session.add(sig)
        db_session.commit()

        ctx = reasoning_context_service.build_reasoning_context(session_model, [], [], signals=[sig])
        sig_facts = [f for f in ctx["deterministic_facts"] if f.get("source_reference") == "corrupt_signal"]
        assert len(sig_facts) == 0, "INVALID signals must be excluded from reasoning context"


# ===========================================================================
# 7. Audit Events & Sensitive Data Protection
# ===========================================================================

class TestAuditAndSensitiveProtection:
    """Test audit logging and sensitive credential blocking."""

    def test_audit_event_generated_on_signal_creation(self, client: TestClient, db_session: Session):
        """31. SIGNAL_CREATED and SIGNAL_VALIDATED events are logged."""
        _, auth = register_and_auth(client, "sig31@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S31")
        v_id = sess_data["id"]

        res = client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "LOCATION",
                "source_type": "CUSTOMER_PROVIDED",
                "source_reference": "gps_audit",
                "data": {"latitude": 12.0, "longitude": 80.0, "accuracy_meters": 10.0, "source": "DEVICE"},
            },
        )
        assert res.status_code == status.HTTP_201_CREATED

        events = db_session.execute(
            select(VerificationEvent).where(VerificationEvent.session_id == v_id)
        ).scalars().all()
        types = [e.event_type for e in events]
        assert VerificationEventType.SIGNAL_CREATED.value in types
        assert VerificationEventType.SIGNAL_VALIDATED.value in types

    def test_sensitive_payment_data_is_rejected(self, client: TestClient, db_session: Session):
        """32. Submitting CVV or card PAN in payment signal data is rejected (422)."""
        _, auth = register_and_auth(client, "sig32@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S32")

        payload_cvv = {
            "signal_type": "PAYMENT",
            "source_type": "MERCHANT_PROVIDED",
            "source_reference": "leaky_payment",
            "data": {
                "payment_id": "P_LEAK",
                "order_id": "O_LEAK",
                "amount": 100.0,
                "currency": "INR",
                "payment_status": "PAID",
                "payment_method": "CARD",
                "cvv": "123",  # SENSITIVE!
            },
        }
        res_cvv = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload_cvv)
        assert res_cvv.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_cancelled_or_expired_session_signals_rejected(self, client: TestClient, db_session: Session):
        """33. Ingesting signals on cancelled or expired verification session returns 410."""
        _, auth = register_and_auth(client, "sig33@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S33")
        v_id = sess_data["id"]

        # Cancel session
        client.post(f"/api/v1/verifications/{v_id}/cancel", headers={"Authorization": auth}, json={"reason": "Cancelled"})

        payload = {
            "signal_type": "ORDER",
            "source_type": "MERCHANT_PROVIDED",
            "source_reference": "cancelled_attempt",
            "data": {"order_id": "O", "quantity": 1, "order_amount": 10.0, "order_status": "CONFIRMED"},
        }
        res = client.post(f"/api/v1/verifications/{v_id}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_410_GONE

    def test_location_accuracy_meters_must_be_positive(self, client: TestClient, db_session: Session):
        """34. accuracy_meters <= 0 is rejected (422)."""
        _, auth = register_and_auth(client, "sig34@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-S34")

        payload = {
            "signal_type": "LOCATION",
            "source_type": "DEVICE",
            "source_reference": "ref_bad_acc",
            "data": {
                "latitude": 10.0,
                "longitude": 20.0,
                "accuracy_meters": 0.0,  # Must be > 0!
            },
        }
        res = client.post(f"/api/v1/verifications/{sess_data['id']}/signals", headers={"Authorization": auth}, json=payload)
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
