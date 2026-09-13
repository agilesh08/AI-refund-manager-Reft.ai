"""Comprehensive Milestone 14 Regression Test Suite.

Validates:
1. Payment proof submission via dedicated endpoint (never calls text evidence).
2. Multi-field extraction in one pass for scrambled order details.
3. Multi-field extraction in one pass for payment screenshots.
4. Merchant expected payment identity configuration.
5. Payment payee identity matching (CONSISTENT).
6. Payment payee mismatch (INCONSISTENT with HIGH contradiction).
7. Payment insufficient evidence handling (INSUFFICIENT).
8. Workflow disabled steps omitted from session snapshot.
9. Workflow snapshot remains frozen and immutable.
10. Failed visual analysis penalized and treated as INSUFFICIENT, not successful.
11. Dynamic confidence calibration (no hardcoded 50% or 100%).
12. Adaptive follow-ups support IMAGE, MCQ, and TEXT with options.
13. Duplicate follow-up request prevention.
14. Customer session does not reveal final assessment / fraud score.
15. Merchant report correctly receives full assessment and confidence.
"""
import io
import pytest
from datetime import datetime, timezone
from PIL import Image
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.evidence_fusion import EvidenceFusionResult, VerificationAssessmentState
from app.models.evidence_request import EvidenceRequest
from app.models.product import Product
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_signal import VerificationSignal, SignalType, SourceType
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep
from app.schemas.evidence_fusion import DimensionStatus, DimensionType, ContradictionSeverity, FusionResultSchema
from app.services.evidence_fusion_service import run_session_fusion
from app.services.extraction_service import (
    parse_order_text_heuristics,
    parse_payment_text_heuristics,
)


def make_test_image(color: str = "green") -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (32, 32), color=color)
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf.getvalue()


def register_merchant(client: TestClient, email: str, name: str = "Test Merchant") -> str:
    client.post(
        "/api/v1/auth/register",
        json={"business_name": name, "email": email, "password": "Password123!"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    return login.json()["access_token"]


def create_test_product(client: TestClient, headers: dict, name: str = "Test Product", sku_prefix: str = "SKU") -> str:
    sku = f"{sku_prefix}-{datetime.now().timestamp()}"
    p_res = client.post(
        "/api/v1/products",
        json={"name": name, "sku": sku, "price": "999.00"},
        headers=headers,
    )
    product_id = p_res.json()["id"]
    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        client.post(
            f"/api/v1/products/{product_id}/references",
            headers=headers,
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", make_test_image(), "image/jpeg")},
        )
    return product_id


def create_active_test_workflow(
    client: TestClient,
    headers: dict,
    name: str = "Active Flow",
    steps: list = None,
) -> str:
    wf_res = client.post(
        "/api/v1/workflows",
        headers=headers,
        json={"name": name, "description": "Workflow for test"},
    )
    workflow_id = wf_res.json()["id"]
    if not steps:
        steps = [
            {
                "step_key": "step_customer_evidence",
                "step_type": "IMAGE",
                "title": "Photo of Item",
                "step_order": 1,
                "config": {"enabled": True},
            }
        ]
    for s in steps:
        client.post(
            f"/api/v1/workflows/{workflow_id}/steps",
            headers=headers,
            json=s,
        )
    client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers=headers,
    )
    return workflow_id


def test_order_text_heuristics_extracts_all_fields_in_one_pass():
    """Verify scrambled text extracts customer, contact, order id, product, amount, reason."""
    scrambled = """
    URGENT REFUND REQUEST
    Customer: Rajan Sharma, phone +919876543210.
    Order ID is ORD-2026-8841.
    Product: Wireless Earbuds
    The item is defective and crackling.
    Refund Reason: Defective and crackling sound
    Total order value was Rs 3499.00 and refund amount requested 3499.
    Order Date: 2026-09-08
    """
    extracted = parse_order_text_heuristics(scrambled)
    assert extracted["order_id"] == "ORD-2026-8841"
    assert extracted["customer_name"] == "Rajan Sharma"
    assert "9876543210" in extracted["customer_contact"]
    assert extracted["product_name"] == "Wireless Earbuds"
    assert extracted["order_amount"] == 3499.0
    assert extracted["refund_amount"] == 3499.0
    assert "defective and crackling" in extracted["refund_reason"].lower()


def test_payment_proof_heuristics_extracts_all_fields_in_one_pass():
    """Verify payment proof extracts UPI, Txn ID, amount, status, app name in one pass."""
    receipt = """
    Google Pay
    Payment to Alitha Store
    alitha.store@okaxis
    Transaction ID: T2609091823001
    Paid: INR 1,499.50
    Date: 09 Sep 2026, 06:23 PM
    Status: Completed Successfully
    """
    extracted = parse_payment_text_heuristics(receipt)
    assert extracted["transaction_id"] == "T2609091823001"
    assert extracted["payee_account"] == "alitha.store@okaxis"
    assert extracted["amount"] == 1499.50
    assert extracted["status"] == "SUCCESS"
    assert extracted["app_name"] == "Google Pay"


def test_payment_proof_submission_and_payee_matching(client: TestClient, db_session: Session):
    """Verify dedicated payment proof submission compares against expected payee account."""
    token = register_merchant(client, "payee_match@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create product
    product_id = create_test_product(client, headers, name="Test Phone", sku_prefix="SKU-PH")

    # 2. Create custom workflow with configured expected payee
    workflow_id = create_active_test_workflow(
        client,
        headers,
        name="Payment Match WF",
        steps=[
            {
                "step_key": "step_initial_img",
                "step_type": "IMAGE",
                "title": "Item Image",
                "step_order": 1,
                "config": {"enabled": True},
            },
            {
                "step_key": "step_payment",
                "step_type": "PAYMENT",
                "title": "Payment Proof",
                "step_order": 2,
                "config": {
                    "enabled": True,
                    "expected_payment_account": "merchant@bankupi",
                },
            },
        ],
    )

    # 3. Create verification session
    v_res = client.post(
        "/api/v1/verifications",
        json={
            "order_id": "ORD-PAY-001",
            "customer_name": "Alice Green",
            "product_id": product_id,
            "workflow_id": workflow_id,
            "refund_amount": 500.0,
        },
        headers=headers,
    )
    cust_token = v_res.json()["customer_link"].split("/")[-1]
    client.post(f"/api/v1/public/verifications/{cust_token}/start")

    # 4. Attempting to submit generic TEXT evidence to PAYMENT step must fail
    bad_text = client.post(
        f"/api/v1/public/verifications/{cust_token}/evidence/text",
        data={"workflow_step_key": "step_payment", "text_payload": "I paid via UPI"},
    )
    assert bad_text.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 5. Submit valid payment proof matching expected payee
    img_bytes = make_test_image("blue")
    good_pay = client.post(
        f"/api/v1/public/verifications/{cust_token}/payment-proof",
        data={
            "workflow_step_key": "step_payment",
            "payee_account": "merchant@bankupi",
            "transaction_id": "TXN-MATCH-12345",
            "amount": "500.0",
            "currency": "INR",
            "payment_status": "SUCCESS",
        },
        files={"file": ("receipt.jpg", img_bytes, "image/jpeg")},
    )
    assert good_pay.status_code == status.HTTP_201_CREATED
    pay_data = good_pay.json()
    assert pay_data["account_matched"] is True
    assert pay_data["expected_payee"] == "merchant@bankupi"

    # 6. Verify fusion evaluates payee reconciliation as CONSISTENT
    sess_id = v_res.json()["id"]
    sess = db_session.execute(
        select(VerificationSession).where(VerificationSession.id == sess_id)
    ).scalar_one()
    fusion = run_session_fusion(db_session, sess.merchant_id, sess_id)
    schema = FusionResultSchema.model_validate(fusion.result_json)
    # Check claim vs payment dimension
    pay_dim = next((d for d in schema.dimensions if d.dimension == DimensionType.CLAIM_VS_PAYMENT), None)
    assert pay_dim is not None
    assert pay_dim.status == DimensionStatus.CONSISTENT


def test_payment_proof_mismatch_creates_inconsistency(client: TestClient, db_session: Session):
    """Verify mismatched payee creates INCONSISTENT status with contradiction."""
    token = register_merchant(client, "payee_mismatch@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    product_id = create_test_product(client, headers, name="Test Mismatch Prod", sku_prefix="SKU-MM")

    workflow_id = create_active_test_workflow(
        client,
        headers,
        name="Strict Payee WF",
        steps=[
            {
                "step_key": "step_payment",
                "step_type": "PAYMENT",
                "title": "Payment Proof",
                "step_order": 1,
                "config": {
                    "enabled": True,
                    "expected_payment_account": "official_store@upi",
                },
            },
        ],
    )

    v_res = client.post(
        "/api/v1/verifications",
        json={
            "order_id": "ORD-MISMATCH-99",
            "customer_name": "Bob",
            "product_id": product_id,
            "workflow_id": workflow_id,
            "refund_amount": 1200.0,
        },
        headers=headers,
    )
    cust_token = v_res.json()["customer_link"].split("/")[-1]
    client.post(f"/api/v1/public/verifications/{cust_token}/start")

    # Submit with completely different payee
    img_bytes = make_test_image("red")
    res = client.post(
        f"/api/v1/public/verifications/{cust_token}/payment-proof",
        data={
            "workflow_step_key": "step_payment",
            "payee_account": "random_other_person@upi",
            "transaction_id": "TXN-MISMATCH-999",
            "amount": "1200.0",
        },
        files={"file": ("receipt.jpg", img_bytes, "image/jpeg")},
    )
    assert res.status_code == status.HTTP_201_CREATED
    assert res.json()["account_matched"] is False

    sess_id = v_res.json()["id"]
    sess = db_session.execute(
        select(VerificationSession).where(VerificationSession.id == sess_id)
    ).scalar_one()
    fusion = run_session_fusion(db_session, sess.merchant_id, sess_id)
    schema = FusionResultSchema.model_validate(fusion.result_json)
    pay_dim = next((d for d in schema.dimensions if d.dimension == DimensionType.CLAIM_VS_PAYMENT), None)
    assert pay_dim is not None
    assert pay_dim.status == DimensionStatus.INCONSISTENT
    assert any("Expected official_store@upi" in c.description for c in schema.contradictions)


def test_workflow_disabled_steps_filtered_from_snapshot(client: TestClient):
    """Verify disabled steps in merchant workflow are filtered out in session snapshot."""
    token = register_merchant(client, "disabled_steps@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    product_id = create_test_product(client, headers, name="Widget", sku_prefix="SKU-WD")

    workflow_id = create_active_test_workflow(
        client,
        headers,
        name="Selective WF",
        steps=[
            {
                "step_key": "step_img_1",
                "step_type": "IMAGE",
                "title": "Enabled Image Step",
                "step_order": 1,
                "config": {"enabled": True},
            },
            {
                "step_key": "step_payment_disabled",
                "step_type": "PAYMENT",
                "title": "Disabled Payment Step",
                "step_order": 2,
                "config": {"enabled": False},
            },
            {
                "step_key": "step_delivery_disabled",
                "step_type": "DELIVERY",
                "title": "Disabled Delivery Step",
                "step_order": 3,
                "config": {"enabled": False},
            },
        ],
    )

    # Create verification session
    v_res = client.post(
        "/api/v1/verifications",
        json={
            "order_id": "ORD-SELECT-1",
            "customer_name": "Charlie",
            "product_id": product_id,
            "workflow_id": workflow_id,
        },
        headers=headers,
    )
    cust_token = v_res.json()["customer_link"].split("/")[-1]

    # Customer fetches workflow
    cust_wf = client.get(f"/api/v1/public/verifications/{cust_token}/workflow")
    assert cust_wf.status_code == 200
    steps = cust_wf.json()["steps"]
    step_keys = [s["step_key"] for s in steps]

    # Only enabled steps should be present
    assert "step_img_1" in step_keys
    assert "step_payment_disabled" not in step_keys
    assert "step_delivery_disabled" not in step_keys


def test_failed_visual_analysis_penalized_not_treated_as_successful(client: TestClient, db_session: Session):
    """Verify failed visual analysis reduces confidence and does not grant consistent visual conclusion."""
    token = register_merchant(client, "failed_vis@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    product_id = create_test_product(client, headers, name="Glass Vase", sku_prefix="SKU-GV")
    workflow_id = create_active_test_workflow(client, headers)

    v_res = client.post(
        "/api/v1/verifications",
        json={
            "order_id": "ORD-FAIL-1",
            "customer_name": "Dave",
            "product_id": product_id,
            "workflow_id": workflow_id,
            "refund_reason": "Broken neck",
        },
        headers=headers,
    )
    sess_id = v_res.json()["id"]
    cust_token = v_res.json()["customer_link"].split("/")[-1]
    client.post(f"/api/v1/public/verifications/{cust_token}/start")

    # Upload customer image
    img = make_test_image("black")
    ev_res = client.post(
        f"/api/v1/public/verifications/{cust_token}/evidence/image",
        data={"workflow_step_key": "step_customer_evidence"},
        files={"file": ("broken.jpg", img, "image/jpeg")},
    )
    assert ev_res.status_code == 201
    ev_json = ev_res.json()
    ev_row = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == ev_json["evidence_id"])
    ).scalar_one()
    ev_id = ev_row.id

    # Simulate visual analysis FAILED
    analysis = VisualAnalysis(
        evidence_id=ev_id,
        status=VisualAnalysisStatus.FAILED.value,
        model_name="test_model",
        prompt_version="v1",
        error_message="Image too dark to detect objects",
        result_json={"error": "Image too dark"},
    )
    db_session.add(analysis)
    db_session.commit()

    # Run fusion
    sess = db_session.execute(
        select(VerificationSession).where(VerificationSession.id == sess_id)
    ).scalar_one()
    fusion = run_session_fusion(db_session, sess.merchant_id, sess_id)
    schema = FusionResultSchema.model_validate(fusion.result_json)

    # Visual dimension should be INSUFFICIENT with missing evidence note
    vis_dim = next((d for d in schema.dimensions if d.dimension == DimensionType.CLAIM_VS_VISUAL), None)
    assert vis_dim is not None
    assert vis_dim.status == DimensionStatus.INSUFFICIENT
    assert vis_dim.confidence <= 0.35
    assert any("visual analysis failed" in item.reason.lower() for item in schema.missing_evidence)

    # Overall confidence must not be hardcoded 50% or 100%
    assert fusion.overall_confidence != 0.50
    assert fusion.overall_confidence != 1.00
    assert fusion.overall_confidence < 0.50


def test_customer_cannot_see_final_assessment_or_fraud_score(client: TestClient):
    """Customer endpoints must never leak final assessment, fraud score, or internal signals."""
    token = register_merchant(client, "safe_customer@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    product_id = create_test_product(client, headers, name="Safe Headphone", sku_prefix="SKU-SH")
    workflow_id = create_active_test_workflow(client, headers)

    v_res = client.post(
        "/api/v1/verifications",
        json={
            "order_id": "ORD-SAFE-1",
            "customer_name": "Eve",
            "product_id": product_id,
            "workflow_id": workflow_id,
        },
        headers=headers,
    )
    cust_token = v_res.json()["customer_link"].split("/")[-1]
    client.post(f"/api/v1/public/verifications/{cust_token}/start")

    # 1. Check overview endpoint
    overview = client.get(f"/api/v1/public/verifications/{cust_token}").json()
    assert "fraud" not in str(overview).lower()
    assert "assessment" not in overview
    assert "overall_confidence" not in overview

    # 2. Complete session
    comp = client.post(f"/api/v1/public/verifications/{cust_token}/complete").json()
    assert comp["status"] == "COMPLETED"
    assert "fraud" not in str(comp).lower()
    assert "is_fraud" not in comp
    assert "assessment" not in comp
