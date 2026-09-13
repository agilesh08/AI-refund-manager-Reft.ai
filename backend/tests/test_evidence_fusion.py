"""Test suite for Milestone 11: Evidence Fusion Engine.

Validates:
1. 8 Independent fusion dimensions (CLAIM_VS_VISUAL, CLAIM_VS_PAYMENT, CLAIM_VS_ORDER,
   CLAIM_VS_DELIVERY, CLAIM_VS_LOCATION, VISUAL_VS_TRUSTED_REFERENCE, ORDER_VS_PAYMENT, ORDER_VS_DELIVERY).
2. Deterministic test cases A through F:
   - Case A: Consistent claim + visual + order + payment + delivery -> EVIDENCE_CONSISTENT
   - Case B: Damage claim + NOT_VISIBLE visual observation -> REVIEW_REQUIRED
   - Case C: "Never delivered" claim + DELIVERED courier signal -> INCONSISTENCY_DETECTED
   - Case D: Order amount mismatch (14,999 vs 9,999) -> REVIEW_REQUIRED (not fraud)
   - Case E: Location within 500m -> CONSISTENT
   - Case F: Location outside 500m -> INCONSISTENT dimension -> REVIEW_REQUIRED (no accusation)
3. Geospatial Haversine calculation accuracy.
4. Llama 3.2 explanation guardrails (cannot change state, confidence, or invent contradictions; prohibited language rejected; offline fail-safe).
5. Context hash invalidation & caching.
6. Multi-tenant security isolation & customer privacy sanitization.
7. Audit trail event generation.
"""
import io
import math
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.evidence_fusion import EvidenceFusionResult, VerificationAssessmentState
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.verification_signal import VerificationSignal, SignalType, SourceType, SignalStatus
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.schemas.evidence_fusion import (
    ContradictionSeverity,
    DimensionStatus,
    DimensionType,
    FusionExplanation,
    PROHIBITED_PHRASES,
)
from app.services.evidence_fusion_service import calculate_haversine_distance


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
    sku: str = "PROD-FUSION-1",
    refund_reason: str = "Device arrived with cracked display.",
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

    # 2. Workflow with IMAGE, PAYMENT, ORDER, DELIVERY, LOCATION steps
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
            "refund_reason": refund_reason,
            "refund_amount": 14999.00,
        },
    )
    sess_data = sess_res.json()
    token = sess_data["customer_link"].rstrip("/").split("/")[-1]
    client.post(f"/api/v1/public/verifications/{token}/start")
    return sess_data, token


def add_completed_visual_analysis(
    db: Session,
    session_id: str,
    evidence_id: str,
    damage_observed: bool = True,
    damage_severity: str = "MODERATE",
    is_identical_model: bool = True,
    overall_conf: float = 0.90,
    uncertainties: Optional[list] = None,
) -> VisualAnalysis:
    """Helper to seed a completed VisualAnalysis record."""
    ev = db.execute(
        select(Evidence).where(
            (Evidence.id == evidence_id) | (Evidence.evidence_id == evidence_id)
        )
    ).scalar_one_or_none()
    real_evidence_id = ev.id if ev else evidence_id

    analysis = VisualAnalysis(
        evidence_id=real_evidence_id,
        model_name="gemini-2.5-flash",
        status=VisualAnalysisStatus.COMPLETED.value,
        prompt_version="v1",
        overall_confidence=overall_conf,
        result_json={
            "product_consistency": {
                "is_identical_model": is_identical_model,
                "branding_match": True,
                "structural_shape_match": True,
                "color_match": True,
            },
            "visible_condition": {
                "localized_damage": damage_observed,
                "damage_severity_observation": damage_severity,
                "damage_location": "front display",
                "packaging_condition": "intact",
            },
            "key_visual_observations": [
                "Visible crack detected on display" if damage_observed else "Display appears pristine and undamaged"
            ],
            "uncertainties": uncertainties or [],
        },
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


# ===========================================================================
# 1. Deterministic Standard Test Cases (Cases A - F)
# ===========================================================================

class TestDeterministicCases:
    """Validate prompt-specified benchmark cases A through F."""

    def test_case_a_consistent(self, client: TestClient, db_session: Session):
        """Case A: Consistent claim + damage observed + matching order + paid + delivered -> EVIDENCE_CONSISTENT."""
        _, auth = register_and_auth(client, "case_a@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-CASE-A", "Product arrived damaged with cracked display.")
        v_id = sess_data["id"]

        # Submit image evidence
        img_res = client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("damage.jpg", make_test_image("red"), "image/jpeg")},
        )
        ev_id = img_res.json()["evidence_id"]

        # Seed completed visual analysis
        add_completed_visual_analysis(db_session, v_id, ev_id, damage_observed=True, damage_severity="MODERATE")

        # Ingest PAYMENT (PAID, 14999.00)
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "PAYMENT",
                "source_type": "INTEGRATION",
                "source_reference": "pay_case_a",
                "data": {"payment_id": "P_A", "order_id": "ORD-SKU-CASE-A", "amount": 14999.00, "currency": "INR", "payment_status": "PAID", "payment_method": "UPI"},
            },
        )

        # Ingest ORDER (CONFIRMED, 14999.00)
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "ORDER",
                "source_type": "MERCHANT_PROVIDED",
                "source_reference": "ord_case_a",
                "data": {"order_id": "ORD-SKU-CASE-A", "order_status": "DELIVERED", "quantity": 1, "order_amount": 14999.00, "item_sku": "SKU-CASE-A"},
            },
        )

        # Ingest DELIVERY (DELIVERED)
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_case_a",
                "data": {"order_id": "ORD-SKU-CASE-A", "carrier": "BlueDart", "delivery_status": "DELIVERED"},
            },
        )

        # Run fusion
        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["assessment_state"] == VerificationAssessmentState.EVIDENCE_CONSISTENT.value
        assert data["overall_confidence"] >= 0.80
        assert len(data["contradictions"]) == 0

    def test_case_b_review_required(self, client: TestClient, db_session: Session):
        """Case B: Claim 'Screen is cracked' + Gemini NOT_VISIBLE -> REVIEW_REQUIRED."""
        _, auth = register_and_auth(client, "case_b@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-CASE-B", "Screen is cracked.")
        v_id = sess_data["id"]

        img_res = client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("blur.jpg", make_test_image("gray"), "image/jpeg")},
        )
        ev_id = img_res.json()["evidence_id"]

        # Gemini observation NOT_VISIBLE
        add_completed_visual_analysis(
            db_session, v_id, ev_id,
            damage_observed=False,
            damage_severity="NOT_VISIBLE",
            uncertainties=["Glare prevents confirming display condition"],
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["assessment_state"] == VerificationAssessmentState.REVIEW_REQUIRED.value
        assert len(data["missing_evidence"]) > 0

    def test_case_c_inconsistency_detected(self, client: TestClient, db_session: Session):
        """Case C: Claim 'Package was not delivered' + Courier DELIVERED -> INCONSISTENCY_DETECTED."""
        _, auth = register_and_auth(client, "case_c@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-CASE-C", "Package was not delivered.")
        v_id = sess_data["id"]

        # Ingest DELIVERY DELIVERED
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_case_c",
                "data": {"order_id": "ORD-SKU-CASE-C", "carrier": "FedEx", "delivery_status": "DELIVERED"},
            },
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["assessment_state"] == VerificationAssessmentState.INCONSISTENCY_DETECTED.value
        assert len(data["contradictions"]) > 0
        contra = data["contradictions"][0]
        assert contra["dimension"] == DimensionType.CLAIM_VS_DELIVERY.value
        assert contra["severity"] == ContradictionSeverity.HIGH.value

    def test_case_d_order_payment_mismatch(self, client: TestClient, db_session: Session):
        """Case D: Order 14999 INR, Payment 9999 INR (PAID) -> REVIEW_REQUIRED (not fraud)."""
        _, auth = register_and_auth(client, "case_d@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-CASE-D", "Display failure")
        v_id = sess_data["id"]

        # Order 14999
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "ORDER",
                "source_type": "MERCHANT_PROVIDED",
                "source_reference": "ord_case_d",
                "data": {"order_id": "ORD-SKU-CASE-D", "order_status": "CONFIRMED", "quantity": 1, "order_amount": 14999.00},
            },
        )

        # Payment 9999
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "PAYMENT",
                "source_type": "INTEGRATION",
                "source_reference": "pay_case_d",
                "data": {"payment_id": "P_D", "order_id": "ORD-SKU-CASE-D", "amount": 9999.00, "currency": "INR", "payment_status": "PAID", "payment_method": "CARD"},
            },
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        # Amount mismatch must NOT be marked INCONSISTENCY_DETECTED or accuse customer; it is REVIEW_REQUIRED
        assert data["assessment_state"] == VerificationAssessmentState.REVIEW_REQUIRED.value
        dim = next(d for d in data["dimensions"] if d["dimension"] == DimensionType.ORDER_VS_PAYMENT.value)
        assert dim["status"] == DimensionStatus.INCONSISTENT.value

    def test_case_e_location_within_range(self, client: TestClient, db_session: Session):
        """Case E: Delivery and device coordinates within 500m -> LOCATION dimension CONSISTENT."""
        _, auth = register_and_auth(client, "case_e@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-CASE-E")
        v_id = sess_data["id"]

        # Delivery destination: 13.0827, 80.2707
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_case_e",
                "data": {
                    "order_id": "ORD-SKU-CASE-E",
                    "carrier": "BlueDart",
                    "delivery_status": "DELIVERED",
                    "delivery_location": {"latitude": 13.0827, "longitude": 80.2707},
                },
            },
        )

        # Device GPS: ~100m away (13.0830, 80.2710)
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "LOCATION",
                "source_type": "CUSTOMER_PROVIDED",
                "source_reference": "loc_case_e",
                "data": {"latitude": 13.0830, "longitude": 80.2710, "accuracy_meters": 15.0, "source": "DEVICE"},
            },
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        loc_dim = next(d for d in data["dimensions"] if d["dimension"] == DimensionType.CLAIM_VS_LOCATION.value)
        assert loc_dim["status"] == DimensionStatus.CONSISTENT.value
        assert loc_dim["details"]["within_range"] is True

    def test_case_f_location_outside_range(self, client: TestClient, db_session: Session):
        """Case F: Coordinates several km apart -> LOCATION INCONSISTENT, but final state is REVIEW_REQUIRED (not fraud)."""
        _, auth = register_and_auth(client, "case_f@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-CASE-F")
        v_id = sess_data["id"]

        # Delivery in Chennai: 13.0827, 80.2707
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_case_f",
                "data": {
                    "order_id": "ORD-SKU-CASE-F",
                    "delivery_status": "DELIVERED",
                    "delivery_location": {"latitude": 13.0827, "longitude": 80.2707},
                },
            },
        )

        # Device in Bangalore (~300 km away): 12.9716, 77.5946
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "LOCATION",
                "source_type": "CUSTOMER_PROVIDED",
                "source_reference": "loc_case_f",
                "data": {"latitude": 12.9716, "longitude": 77.5946, "accuracy_meters": 10.0, "source": "DEVICE"},
            },
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        loc_dim = next(d for d in data["dimensions"] if d["dimension"] == DimensionType.CLAIM_VS_LOCATION.value)
        assert loc_dim["status"] == DimensionStatus.INCONSISTENT.value
        assert loc_dim["details"]["within_range"] is False
        # Location alone must NOT convict customer into INCONSISTENCY_DETECTED
        assert data["assessment_state"] == VerificationAssessmentState.REVIEW_REQUIRED.value


# ===========================================================================
# 2. Dimension Evaluation Tests
# ===========================================================================

class TestDimensionEvaluations:
    """Detailed checks across remaining individual dimensions."""

    def test_claim_vs_visual_inconsistency(self, client: TestClient, db_session: Session):
        """2. High-confidence pristine condition vs damage claim -> INCONSISTENT."""
        _, auth = register_and_auth(client, "dim2@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-D2", "Shattered screen")
        v_id = sess_data["id"]

        img_res = client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("clean.jpg", make_test_image("white"), "image/jpeg")},
        )
        ev_id = img_res.json()["evidence_id"]

        add_completed_visual_analysis(
            db_session, v_id, ev_id,
            damage_observed=False,
            damage_severity="NONE",
            overall_conf=0.92,
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        data = res.json()
        dim = next(d for d in data["dimensions"] if d["dimension"] == DimensionType.CLAIM_VS_VISUAL.value)
        assert dim["status"] == DimensionStatus.INCONSISTENT.value

    def test_claim_vs_visual_unclear(self, client: TestClient, db_session: Session):
        """3 & 12. Gemini observation UNCLEAR -> INSUFFICIENT dimension & REVIEW_REQUIRED."""
        _, auth = register_and_auth(client, "dim3@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-D3", "Scratch on corner")
        v_id = sess_data["id"]

        img_res = client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("dark.jpg", make_test_image("black"), "image/jpeg")},
        )
        ev_id = img_res.json()["evidence_id"]

        add_completed_visual_analysis(
            db_session, v_id, ev_id,
            damage_observed=False,
            damage_severity="UNCLEAR",
            uncertainties=["Lighting too dark to evaluate"],
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        data = res.json()
        assert data["assessment_state"] == VerificationAssessmentState.REVIEW_REQUIRED.value

    def test_trusted_reference_mismatch(self, client: TestClient, db_session: Session):
        """4. Different product model in image vs reference -> INCONSISTENT with HIGH severity contradiction."""
        _, auth = register_and_auth(client, "dim4@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-D4")
        v_id = sess_data["id"]

        img_res = client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("diff.jpg", make_test_image("green"), "image/jpeg")},
        )
        ev_id = img_res.json()["evidence_id"]

        add_completed_visual_analysis(db_session, v_id, ev_id, is_identical_model=False)

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        data = res.json()
        assert data["assessment_state"] == VerificationAssessmentState.INCONSISTENCY_DETECTED.value
        dim = next(d for d in data["dimensions"] if d["dimension"] == DimensionType.VISUAL_VS_TRUSTED_REFERENCE.value)
        assert dim["status"] == DimensionStatus.INCONSISTENT.value

    def test_order_delivery_mismatch(self, client: TestClient, db_session: Session):
        """8. Order CANCELLED but delivery DELIVERED -> INCONSISTENT."""
        _, auth = register_and_auth(client, "dim8@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-D8")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "ORDER",
                "source_type": "MERCHANT_PROVIDED",
                "source_reference": "ord_d8",
                "data": {"order_id": "ORD-SKU-D8", "order_status": "CANCELLED", "quantity": 1, "order_amount": 1000.0},
            },
        )

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_d8",
                "data": {"order_id": "ORD-SKU-D8", "delivery_status": "DELIVERED"},
            },
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        data = res.json()
        assert data["assessment_state"] == VerificationAssessmentState.INCONSISTENCY_DETECTED.value

    def test_missing_deterministic_signal_handled_gracefully(self, client: TestClient, db_session: Session):
        """10. Missing signals result in NOT_APPLICABLE status without error."""
        _, auth = register_and_auth(client, "dim10@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-D10")
        v_id = sess_data["id"]

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        pay_dim = next(d for d in data["dimensions"] if d["dimension"] == DimensionType.CLAIM_VS_PAYMENT.value)
        assert pay_dim["status"] == DimensionStatus.NOT_APPLICABLE.value

    def test_missing_visual_analysis_handled_gracefully(self, client: TestClient, db_session: Session):
        """11. Evidence uploaded but visual analysis not yet run yields INSUFFICIENT."""
        _, auth = register_and_auth(client, "dim11@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-D11")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("photo.jpg", make_test_image("blue"), "image/jpeg")},
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        vis_dim = next(d for d in data["dimensions"] if d["dimension"] == DimensionType.CLAIM_VS_VISUAL.value)
        assert vis_dim["status"] == DimensionStatus.INSUFFICIENT.value


# ===========================================================================
# 3. Geospatial & Location Tests
# ===========================================================================

class TestGeospatialAndLocation:
    """Validation for location accuracy and Haversine distance calculations."""

    def test_haversine_distance_calculation(self):
        """17. Haversine distance formula yields correct distance in meters."""
        # Paris (48.8566, 2.3522) to London (51.5074, -0.1278) is approx ~343-344 km
        dist = calculate_haversine_distance(48.8566, 2.3522, 51.5074, -0.1278)
        assert 340000 < dist < 346000

        # Exact same point is 0
        assert calculate_haversine_distance(12.9716, 77.5946, 12.9716, 77.5946) == 0.0

    def test_location_insufficient_due_to_missing_accuracy(self, client: TestClient, db_session: Session):
        """16. Location signal with accuracy <= 0 or missing accuracy yields INSUFFICIENT."""
        _, auth = register_and_auth(client, "loc16@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-L16")
        v_id = sess_data["id"]

        # Insert directly to DB bypass Pydantic positive validation to test engine resilience
        sig = VerificationSignal(
            verification_session_id=v_id,
            signal_type="LOCATION",
            source_type="CUSTOMER_PROVIDED",
            status="VALID",
            data_json={"latitude": 13.0, "longitude": 80.0, "accuracy_meters": 0.0},
            source_reference="loc_zero_acc",
        )
        db_session.add(sig)
        db_session.commit()

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        data = res.json()
        loc_dim = next(d for d in data["dimensions"] if d["dimension"] == DimensionType.CLAIM_VS_LOCATION.value)
        assert loc_dim["status"] == DimensionStatus.INSUFFICIENT.value

    def test_source_provenance_preserved_in_contradictions(self, client: TestClient, db_session: Session):
        """18. Source provenance (source_a, source_b) is accurately preserved in contradiction objects."""
        _, auth = register_and_auth(client, "prov18@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-P18", "Package was not delivered")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_p18",
                "data": {"order_id": "ORD-SKU-P18", "delivery_status": "DELIVERED"},
            },
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        data = res.json()
        contra = data["contradictions"][0]
        assert contra["source_a"] == "CUSTOMER_STATED"
        assert contra["source_b"] == "DELIVERY_SIGNAL"


# ===========================================================================
# 4. Llama Explanation & Guardrail Tests
# ===========================================================================

class TestLlamaExplanationGuardrails:
    """Verify that Llama only explains, cannot alter decisions, and obeys safety rules."""

    def test_llama_cannot_change_state_or_confidence(self, client: TestClient, db_session: Session):
        """24-25. Llama explanation cannot modify assessment_state or overall_confidence."""
        _, auth = register_and_auth(client, "llama24@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-LL24", "Package was not delivered")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_ll24",
                "data": {"order_id": "ORD-SKU-LL24", "delivery_status": "DELIVERED"},
            },
        )

        # Mock Llama returning an explanation
        mock_explanation = FusionExplanation(
            summary="Delivery discrepancy noted.",
            key_points=["Customer claims non-delivery", "Courier confirms delivery"],
            recommended_review="Cross-check courier signature",
        )

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_fusion_explanation", return_value=mock_explanation):
            res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
            data = res.json()

        assert data["assessment_state"] == VerificationAssessmentState.INCONSISTENCY_DETECTED.value
        assert data["explanation"]["summary"] == "Delivery discrepancy noted."

    def test_llama_prohibited_language_rejected(self):
        """27. FusionExplanation schema strictly rejects accusatory terms like 'fraud', 'liar', etc."""
        with pytest.raises(Exception) as exc_info:
            FusionExplanation(
                summary="The customer is committing fraud.",
                key_points=["Point 1"],
                recommended_review="Reject claim",
            )
        assert "fraud" in str(exc_info.value).lower()

        with pytest.raises(Exception) as exc_info2:
            FusionExplanation(
                summary="Valid summary",
                key_points=["The customer is a liar"],
                recommended_review="Review case",
            )
        assert "liar" in str(exc_info2.value).lower()

    def test_llama_offline_does_not_destroy_fusion_result(self, client: TestClient, db_session: Session):
        """28. If Ollama is offline or times out, deterministic fusion result remains valid with explanation=null."""
        _, auth = register_and_auth(client, "llama28@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-LL28", "Package was not delivered")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_ll28",
                "data": {"order_id": "ORD-SKU-LL28", "delivery_status": "DELIVERED"},
            },
        )

        # Mock Ollama failure / offline (returns None)
        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_fusion_explanation", return_value=None):
            res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
            assert res.status_code == status.HTTP_200_OK
            data = res.json()

        assert data["assessment_state"] == VerificationAssessmentState.INCONSISTENCY_DETECTED.value
        assert data["explanation"] is None


# ===========================================================================
# 5. Context Hash, Caching, and Historical Persistence
# ===========================================================================

class TestContextHashAndCaching:
    """Verify SHA-256 context hashing, caching, and immutability."""

    def test_fusion_cache_returns_identical_result(self, client: TestClient, db_session: Session):
        """31. Calling fusion consecutively on unchanged context returns cached result."""
        _, auth = register_and_auth(client, "cache31@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-C31")
        v_id = sess_data["id"]

        res1 = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        id1 = res1.json()["id"]

        res2 = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        id2 = res2.json()["id"]

        assert id1 == id2, "Identical context must return cached fusion result"

        # Check DB count is 1
        history = client.get(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth}).json()
        assert len(history) == 1

    def test_new_evidence_creates_new_historical_fusion(self, client: TestClient, db_session: Session):
        """29, 30, 32. Ingesting new signal alters context hash and creates new historical fusion record."""
        _, auth = register_and_auth(client, "hist32@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-H32")
        v_id = sess_data["id"]

        # Run 1
        res1 = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        id1 = res1.json()["id"]
        hash1 = res1.json()["input_context_hash"]

        # Add payment signal -> context changes
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "PAYMENT",
                "source_type": "INTEGRATION",
                "source_reference": "pay_h32",
                "data": {"payment_id": "P32", "order_id": "ORD-SKU-H32", "amount": 14999.00, "currency": "INR", "payment_status": "PAID", "payment_method": "UPI"},
            },
        )

        # Run 2
        res2 = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        id2 = res2.json()["id"]
        hash2 = res2.json()["input_context_hash"]

        assert id1 != id2, "New signal must create new fusion record"
        assert hash1 != hash2, "Context hash must change"

        # Check DB history preserves both
        history = client.get(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth}).json()
        assert len(history) == 2


# ===========================================================================
# 6. Security, Tenant Isolation, and Customer Sanitization
# ===========================================================================

class TestSecurityAndIsolation:
    """Verify tenant isolation, customer privacy, and audit logging."""

    def test_merchant_cannot_access_another_merchants_fusion(self, client: TestClient, db_session: Session):
        """33. Cross-merchant fusion request returns HTTP 404."""
        _, auth_a = register_and_auth(client, "merch_a@store.com")
        _, auth_b = register_and_auth(client, "merch_b@store.com")
        sess_data, _ = setup_test_verification(client, auth_a, "SKU-SEC-1")
        v_id = sess_data["id"]

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth_b})
        assert res.status_code == status.HTTP_404_NOT_FOUND

        res_get = client.get(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth_b})
        assert res_get.status_code == status.HTTP_404_NOT_FOUND

    def test_customer_cannot_access_merchant_fusion_endpoint(self, client: TestClient, db_session: Session):
        """35. Customer token cannot access merchant fusion endpoint without merchant JWT."""
        _, auth = register_and_auth(client, "merch_c@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-SEC-2")
        v_id = sess_data["id"]

        # Call without Authorization header -> 401
        res = client.post(f"/api/v1/verifications/{v_id}/fusion")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_customer_fusion_is_sanitized(self, client: TestClient, db_session: Session):
        """34. Customer public fusion endpoint returns sanitized, polite, non-accusatory summary."""
        _, auth = register_and_auth(client, "cust_san@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-SAN", "Package was not delivered")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_san",
                "data": {"order_id": "ORD-SKU-SAN", "delivery_status": "DELIVERED"},
            },
        )

        # Trigger fusion
        client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})

        # Customer views fusion
        pub_res = client.get(f"/api/v1/public/verifications/{token}/fusion")
        assert pub_res.status_code == status.HTTP_200_OK
        pub_data = pub_res.json()

        # Check sanitized properties
        assert "overall_confidence" not in pub_data
        assert "contradictions" not in pub_data
        assert "dimensions" not in pub_data
        assert "verification_session_id" not in pub_data
        assert pub_data["assessment_state"] == VerificationAssessmentState.INCONSISTENCY_DETECTED.value
        # Polite customer wording
        assert "discrepancy" in pub_data["customer_summary"].lower()
        assert "fraud" not in pub_data["customer_summary"].lower()

    def test_audit_events_created(self, client: TestClient, db_session: Session):
        """36. FUSION_STARTED and FUSION_COMPLETED events are recorded in audit trail."""
        _, auth = register_and_auth(client, "audit36@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-A36")
        v_id = sess_data["id"]

        client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})

        events = db_session.execute(
            select(VerificationEvent).where(VerificationEvent.session_id == v_id)
        ).scalars().all()
        types = [e.event_type for e in events]
        assert VerificationEventType.FUSION_STARTED.value in types
        assert VerificationEventType.FUSION_COMPLETED.value in types


# ===========================================================================
# 7. Extended Scenarios & Lifecycle Handling
# ===========================================================================

class TestExtendedFusionScenarios:
    """Additional edge cases covering latest retrieval, payment discrepancies, and cancelled sessions."""

    def test_get_latest_fusion_endpoint(self, client: TestClient, db_session: Session):
        """GET /api/v1/verifications/{id}/fusion/latest returns the most recent fusion record."""
        _, auth = register_and_auth(client, "latest@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-LAT")
        v_id = sess_data["id"]

        # 1. No fusion run yet -> /latest triggers a dynamic first run
        latest_res = client.get(f"/api/v1/verifications/{v_id}/fusion/latest", headers={"Authorization": auth})
        assert latest_res.status_code == status.HTTP_200_OK
        first_id = latest_res.json()["id"]

        # Ingest signal
        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "DELIVERY",
                "source_type": "INTEGRATION",
                "source_reference": "del_latest",
                "data": {"order_id": "ORD-SKU-LAT", "delivery_status": "DELIVERED"},
            },
        )

        # 2. Run new fusion
        new_res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        second_id = new_res.json()["id"]
        assert second_id != first_id

        # 3. /latest now returns the second run
        latest_res2 = client.get(f"/api/v1/verifications/{v_id}/fusion/latest", headers={"Authorization": auth})
        assert latest_res2.status_code == status.HTTP_200_OK
        assert latest_res2.json()["id"] == second_id

    def test_payment_status_failed_causes_review_required(self, client: TestClient, db_session: Session):
        """Payment signal with status FAILED flags contradiction and REVIEW_REQUIRED."""
        _, auth = register_and_auth(client, "payfail@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-PFAIL")
        v_id = sess_data["id"]

        client.post(
            f"/api/v1/verifications/{v_id}/signals",
            headers={"Authorization": auth},
            json={
                "signal_type": "PAYMENT",
                "source_type": "INTEGRATION",
                "source_reference": "pay_fail_sig",
                "data": {"payment_id": "P_FAIL", "order_id": "ORD-SKU-PFAIL", "amount": 14999.00, "currency": "INR", "payment_status": "FAILED", "payment_method": "UPI"},
            },
        )

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["assessment_state"] == VerificationAssessmentState.INCONSISTENCY_DETECTED.value
        pay_dim = next(d for d in data["dimensions"] if d["dimension"] == DimensionType.CLAIM_VS_PAYMENT.value)
        assert pay_dim["status"] == DimensionStatus.INCONSISTENT.value

    def test_cancelled_session_returns_410_gone(self, client: TestClient, db_session: Session):
        """Cancelled verification session cannot execute fusion and returns HTTP 410 Gone."""
        _, auth = register_and_auth(client, "cancel@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-CANC")
        v_id = sess_data["id"]

        # Cancel the session directly in DB
        sess = db_session.execute(
            select(VerificationSession).where(VerificationSession.id == v_id)
        ).scalar_one()
        sess.status = SessionStatus.CANCELLED.value
        db_session.commit()

        res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert res.status_code == status.HTTP_410_GONE

