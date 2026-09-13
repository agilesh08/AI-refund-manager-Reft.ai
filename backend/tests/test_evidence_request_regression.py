"""Regression tests for EvidenceRequest attribute access, product completeness, and extraction."""
import pytest
from unittest.mock import MagicMock
from app.models.evidence_request import EvidenceRequest
from app.schemas.evidence_request import EvidenceRequestResponse, CustomerEvidenceRequestResponse
from app.schemas.product import ProductReferenceStatusResponse
from app.services.extraction_service import parse_order_text_heuristics, parse_payment_text_heuristics


def test_evidence_request_model_step_key_property():
    """Verify EvidenceRequest has step_key property that mirrors workflow_step_key."""
    req = EvidenceRequest(
        id="test-req-1",
        verification_session_id="sess-1",
        workflow_step_key="step_camera_front",
        requested_evidence_type="CUSTOMER_IMAGE",
        reason="Please capture front angle.",
        status="PENDING",
    )
    assert req.workflow_step_key == "step_camera_front"
    assert req.step_key == "step_camera_front"


def test_evidence_request_schemas_step_key_and_workflow_step_key():
    """Verify schemas accept both step_key and workflow_step_key and stay synchronized."""
    # From dict with workflow_step_key
    resp1 = EvidenceRequestResponse.model_validate({
        "id": "req-1",
        "verification_session_id": "sess-1",
        "workflow_step_key": "step_damage_close_up",
        "requested_evidence_type": "CUSTOMER_IMAGE",
        "reason": "Clear close-up photo needed",
        "status": "PENDING",
        "created_at": "2026-09-09T10:00:00Z",
    })
    assert resp1.workflow_step_key == "step_damage_close_up"
    assert resp1.step_key == "step_damage_close_up"

    # From dict with step_key
    resp2 = EvidenceRequestResponse.model_validate({
        "id": "req-2",
        "verification_session_id": "sess-1",
        "step_key": "step_damage_close_up",
        "requested_evidence_type": "CUSTOMER_IMAGE",
        "reason": "Clear close-up photo needed",
        "status": "PENDING",
        "created_at": "2026-09-09T10:00:00Z",
    })
    assert resp2.workflow_step_key == "step_damage_close_up"
    assert resp2.step_key == "step_damage_close_up"


def test_product_reference_completeness_schema_fields():
    """Verify ProductReferenceStatusResponse includes is_complete, existing_count, required_count."""
    comp = ProductReferenceStatusResponse(
        product_id="prod-123",
        reference_status={"front": True, "back": True, "left": True, "right": True},
        complete=True,
        is_complete=True,
        existing_count=4,
        required_count=4,
    )
    assert comp.is_complete is True
    assert comp.complete is True
    assert comp.existing_count == 4
    assert comp.required_count == 4

    comp_incomplete = ProductReferenceStatusResponse(
        product_id="prod-123",
        reference_status={"front": True, "back": True, "left": False, "right": False},
        complete=False,
        is_complete=False,
        existing_count=2,
        required_count=4,
    )
    assert comp_incomplete.is_complete is False
    assert comp_incomplete.existing_count == 2


def test_order_text_heuristics_parsing():
    """Verify regex heuristics parse order text accurately."""
    sample_text = """
    Order ID: ORD-2026-9921
    Customer: Raj Patel
    Contact: 9876543210
    Product: Noise-Cancelling Headphones
    Total Amount: ₹2,499.00
    Date: 09 Sep 2026
    """
    res = parse_order_text_heuristics(sample_text)
    assert res["order_id"] == "ORD-2026-9921"
    assert res["customer_name"] == "Raj Patel"
    assert res["customer_contact"] == "9876543210"
    assert res["product_name"] == "Noise-Cancelling Headphones"
    assert res["order_amount"] == 2499.0
    assert "09 Sep 2026" in res["order_date"]


def test_payment_text_heuristics_parsing():
    """Verify regex heuristics parse payment proof text accurately."""
    sample_text = """
    Paid to Alitha Store
    UPI ID: alitha.store@upi
    Transaction ID: 123456789012
    Amount: ₹149.99
    Date: 09 Sep 2026
    Status: Successful
    Google Pay
    """
    res = parse_payment_text_heuristics(sample_text)
    assert res["transaction_id"] == "123456789012"
    assert "alitha.store@upi" in [res["payee_account"], res["upi_id"]]
    assert res["amount"] == 149.99
    assert res["status"] == "SUCCESS"
    assert res["app_name"] == "Google Pay"
