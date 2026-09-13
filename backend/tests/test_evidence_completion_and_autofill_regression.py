
"""Regression tests for customer evidence completion, SQLite auto-migration, and order autofill heuristics."""
from datetime import timedelta
from decimal import Decimal
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, _migrate_sqlite_columns
from app.core.security import generate_verification_token, hash_verification_token
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.workflow import Workflow, WorkflowStatus
from app.models.verification import VerificationSession, SessionStatus, utc_now
from app.models.evidence_request import EvidenceRequest, EvidenceRequestStatus
from app.services.evidence_request_service import (
    list_session_requests,
    create_evidence_request,
    get_pending_request,
)
from app.services.public_verification_service import (
    analyze_customer_session,
    complete_customer_session,
)
from app.services.extraction_service import (
    parse_order_text_heuristics,
    extract_order_details,
)


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Provide an isolated SQLite database fixture for regression testing."""
    db_file = tmp_path / "test_reg.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_list_session_requests_empty(sqlite_test_db):
    """Test that list_session_requests returns empty list when no requests exist."""
    res = list_session_requests(sqlite_test_db, "nonexistent_session_id")
    assert res == []
    assert list_session_requests(sqlite_test_db, "") == []
    assert list_session_requests(sqlite_test_db, None) == []


def test_list_session_requests_with_data(sqlite_test_db):
    """Test that list_session_requests returns existing requests with options_json."""
    merchant = Merchant(
        id="m_test_1",
        email="merchant@test.com",
        business_name="Test Store",
        password_hash="fake",
    )
    sqlite_test_db.add(merchant)
    product = Product(
        id="p_test_1",
        merchant_id=merchant.id,
        name="Test Item",
        sku="TEST-SKU-1",
        price=Decimal("100.00"),
    )
    sqlite_test_db.add(product)
    workflow = Workflow(
        id="wf_test_1",
        merchant_id=merchant.id,
        name="Flow 1",
        status=WorkflowStatus.ACTIVE.value,
        is_active=True,
    )
    sqlite_test_db.add(workflow)
    sqlite_test_db.flush()

    raw_token = generate_verification_token()
    token_hash = hash_verification_token(raw_token)
    session = VerificationSession(
        id="sess_test_1",
        merchant_id=merchant.id,
        product_id=product.id,
        workflow_id=workflow.id,
        workflow_version=1,
        order_id="ORD-101",
        verification_id="VR-2026-TEST01",
        customer_token_hash=token_hash,
        expires_at=utc_now() + timedelta(days=1),
        workflow_snapshot_json={"steps": [{"step_key": "step_front", "step_type": "IMAGE"}]},
        status=SessionStatus.IN_PROGRESS.value,
    )
    sqlite_test_db.add(session)
    sqlite_test_db.flush()

    req = EvidenceRequest(
        id="req_test_1",
        verification_session_id=session.id,
        workflow_step_key="step_front",
        requested_evidence_type="CUSTOMER_IMAGE",
        reason="Front angle needed",
        options_json=["Front", "Side"],
        status=EvidenceRequestStatus.PENDING.value,
    )
    sqlite_test_db.add(req)
    sqlite_test_db.commit()

    results = list_session_requests(sqlite_test_db, session.id)
    assert len(results) == 1
    assert results[0].id == "req_test_1"
    assert results[0].options_json == ["Front", "Side"]
    assert results[0].workflow_step_key == "step_front"


def test_customer_proceed_flow_no_followup(sqlite_test_db):
    """Verify customer proceeding with no follow-up returns READY_FOR_REVIEW and completes cleanly."""
    merchant = Merchant(
        id="m_test_2",
        email="m2@test.com",
        business_name="Store 2",
        password_hash="fake",
    )
    sqlite_test_db.add(merchant)
    product = Product(
        id="p_test_2",
        merchant_id=merchant.id,
        name="Shoes",
        sku="SHOE-1",
        price=Decimal("250.00"),
    )
    sqlite_test_db.add(product)
    workflow = Workflow(
        id="wf_test_2",
        merchant_id=merchant.id,
        name="Flow 2",
        status=WorkflowStatus.ACTIVE.value,
        is_active=True,
    )
    sqlite_test_db.add(workflow)
    sqlite_test_db.flush()

    raw_token = generate_verification_token()
    token_hash = hash_verification_token(raw_token)

    session = VerificationSession(
        id="sess_test_2",
        merchant_id=merchant.id,
        product_id=product.id,
        workflow_id=workflow.id,
        workflow_version=1,
        order_id="ORD-102",
        verification_id="VR-2026-TEST02",
        customer_token_hash=token_hash,
        expires_at=utc_now() + timedelta(days=1),
        workflow_snapshot_json={"steps": [{"step_key": "step_image_1", "step_type": "IMAGE"}]},
        status=SessionStatus.IN_PROGRESS.value,
    )
    sqlite_test_db.add(session)
    sqlite_test_db.commit()

    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_fusion_explanation", return_value=None):
        # Step 1: analyze returns READY_FOR_REVIEW since no follow-up requests exist
        analysis_res = analyze_customer_session(sqlite_test_db, raw_token)
        assert analysis_res["status"] == "READY_FOR_REVIEW"
        assert "successfully analyzed" in analysis_res["message"]

        # Step 2: complete marks session COMPLETED
        completion_res = complete_customer_session(sqlite_test_db, raw_token)
        assert completion_res.status == SessionStatus.COMPLETED.value
        assert session.status == SessionStatus.COMPLETED.value


def test_customer_proceed_flow_with_followup(sqlite_test_db):
    """Verify customer proceeding with an existing pending request returns FOLLOWUP_REQUIRED."""
    merchant = Merchant(
        id="m_test_3",
        email="m3@test.com",
        business_name="Store 3",
        password_hash="fake",
    )
    sqlite_test_db.add(merchant)
    product = Product(
        id="p_test_3",
        merchant_id=merchant.id,
        name="Watch",
        sku="WATCH-1",
        price=Decimal("450.00"),
    )
    sqlite_test_db.add(product)
    workflow = Workflow(
        id="wf_test_3",
        merchant_id=merchant.id,
        name="Flow 3",
        status=WorkflowStatus.ACTIVE.value,
        is_active=True,
    )
    sqlite_test_db.add(workflow)
    sqlite_test_db.flush()

    raw_token = generate_verification_token()
    token_hash = hash_verification_token(raw_token)

    session = VerificationSession(
        id="sess_test_3",
        merchant_id=merchant.id,
        product_id=product.id,
        workflow_id=workflow.id,
        workflow_version=1,
        order_id="ORD-103",
        verification_id="VR-2026-TEST03",
        customer_token_hash=token_hash,
        expires_at=utc_now() + timedelta(days=1),
        workflow_snapshot_json={"steps": [{"step_key": "step_image_1", "step_type": "IMAGE"}]},
        status=SessionStatus.IN_PROGRESS.value,
    )
    sqlite_test_db.add(session)
    sqlite_test_db.flush()

    req = EvidenceRequest(
        id="req_followup_1",
        verification_session_id=session.id,
        workflow_step_key="step_image_1",
        requested_evidence_type="CUSTOMER_IMAGE",
        reason="Please provide a clearer photo of the watch clasp.",
        status=EvidenceRequestStatus.PENDING.value,
    )
    sqlite_test_db.add(req)
    sqlite_test_db.commit()

    analysis_res = analyze_customer_session(sqlite_test_db, raw_token)
    assert analysis_res["status"] == "FOLLOWUP_REQUIRED"
    assert analysis_res["request"]["id"] == "req_followup_1"
    assert "watch clasp" in analysis_res["message"]


def test_parse_order_text_heuristics_clean():
    """Verify clean order text extracts all standard fields."""
    sample = "Order ID: ORD-2026-5544\nCustomer Name: Alice Wonder\nEmail: alice.wonder@example.com\nProduct Name: Wireless Bluetooth Speaker\nOrder Amount: 3,499.00\nRefund Reason: Item speaker grille is cracked upon opening\nDate: 11 Sep 2026"
    res = parse_order_text_heuristics(sample)
    assert res["order_id"] == "ORD-2026-5544"
    assert res["customer_name"] == "Alice Wonder"
    assert res["customer_contact"] == "alice.wonder@example.com"
    assert res["customer_email"] == "alice.wonder@example.com"
    assert res["product_name"] == "Wireless Bluetooth Speaker"
    assert res["order_amount"] == 3499.0
    assert "cracked upon opening" in res["refund_reason"]
    assert "11 Sep 2026" in res["order_date"]


def test_parse_order_text_heuristics_product_name_does_not_mask_customer_name():
    """Verify 'Product Name:' is NEVER extracted as the customer name."""
    sample = "Order Number: ORD-998877\nProduct Name: Ultra HD 4K Action Camera\nCustomer Name: Michael Chang\nEmail Address: michael.chang@test.io\nPrice: 8,999.00\nReason: Missing waterproof case"
    res = parse_order_text_heuristics(sample)
    assert res["customer_name"] == "Michael Chang"
    assert res["product_name"] == "Ultra HD 4K Action Camera"
    assert res["customer_contact"] == "michael.chang@test.io"
    assert res["order_amount"] == 8999.0


def test_parse_order_text_heuristics_order_id_digits_do_not_override_email():
    """Verify a 10-digit number inside an Order ID or SKU does not override customer email."""
    sample = "Order ID: ORD-9876543210\nName: Sara Connor\nEmail: sara.connor@sky.net\nProduct: Tactical Boots\nAmount: 4500"
    res = parse_order_text_heuristics(sample)
    assert res["order_id"] == "ORD-9876543210"
    assert res["customer_name"] == "Sara Connor"
    assert res["customer_contact"] == "sara.connor@sky.net"
    assert res["customer_email"] == "sara.connor@sky.net"


def test_parse_order_text_heuristics_scrambled_labels():
    """Verify heuristics parse fields even when labels and lines are in scrambled order."""
    sample = "Refund Reason: Screen flicker and battery drain\nTotal: 12999\nDate: 05 Aug 2026\nBuyer: David Beckham\nContact: david.beckham@galaxy.com\nOrder # ORD-SCRAMBLE-77\nTitle: Smart Fitness Tracker"
    res = parse_order_text_heuristics(sample)
    assert res["order_id"] == "ORD-SCRAMBLE-77"
    assert res["customer_name"] == "David Beckham"
    assert res["customer_contact"] == "david.beckham@galaxy.com"
    assert res["product_name"] == "Smart Fitness Tracker"
    assert res["order_amount"] == 12999.0
    assert "Screen flicker" in res["refund_reason"]


def test_extract_order_details_field_alias_mapping():
    """Verify extract_order_details normalizes LLM field aliases properly."""
    mock_llm_json = {
        "orderId": "ORD-ALIAS-123",
        "name": "Emily Watson",
        "email": "emily.watson@drama.co.uk",
        "item": "Vintage Ceramic Mug",
        "defect": "Handle was chipped during shipping",
        "price": 650.0,
        "date": "10 Sep 2026",
    }
    with patch("app.services.extraction_service.settings.GEMINI_API_KEY", "fake_key"):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_response = MagicMock()
            import json
            mock_response.text = json.dumps(mock_llm_json)
            mock_client.models.generate_content.return_value = mock_response

            extracted = extract_order_details(text="Some unformatted receipt text")
            assert extracted["order_id"] == "ORD-ALIAS-123"
            assert extracted["customer_name"] == "Emily Watson"
            assert extracted["customer_contact"] == "emily.watson@drama.co.uk"
            assert extracted["product_name"] == "Vintage Ceramic Mug"
            assert extracted["refund_reason"] == "Handle was chipped during shipping"
            assert extracted["order_amount"] == 650.0
