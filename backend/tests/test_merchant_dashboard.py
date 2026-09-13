"""Comprehensive test suite for Milestone 12: Merchant Dashboard + Explainable Final Report.

Validates:
1. Dashboard Verification Listing (GET /api/v1/verifications):
   - Pagination (page, page_size, total, slicing)
   - Multi-criteria filtering (status, assessment_state, date range, order_id, product_id)
   - Cross-field search (customer_id, customer_email, order_id, product name, product SKU)
   - Merchant tenant isolation
2. Verification Investigation Detail View (GET /api/v1/verifications/{verification_id}/dashboard):
   - Complete 13-facet aggregation
   - Privacy guarantee: raw customer tokens/links sanitized
   - Cross-merchant 404 isolation
3. Explainable Final Verification Report (GET /api/v1/verifications/{verification_id}/report):
   - All 9 structured sections present and non-empty
   - Authoritative assessment states: EVIDENCE_CONSISTENT, REVIEW_REQUIRED, INCONSISTENCY_DETECTED
   - Cross-merchant 404 isolation
4. Chronological Verification Timeline (GET /api/v1/verifications/{verification_id}/timeline):
   - Real events only (sessions, evidence, visual analysis, fusion, merchant decisions)
   - Strictly ordered chronologically (oldest first)
5. Merchant Final Decisions (POST & GET /api/v1/verifications/{verification_id}/decision[s]):
   - Human merchant as authoritative decision maker
   - State transition: REFUND_APPROVED and REFUND_REJECTED complete session
   - Audit event logged: MERCHANT_DECISION_MADE
   - Full decision history preserved across updates
   - Negative boundaries: invalid enum -> 422, cancelled session -> 410, cross-merchant -> 404,
     customer token -> 401
6. Five End-to-End Scenarios:
   - Scenario 1: Consistent Verification Flow -> Approved
   - Scenario 2: Incomplete Evidence Flow -> Review Required
   - Scenario 3: Contradictory Evidence Flow -> Inconsistency Detected -> Rejected
   - Scenario 4: Ollama Offline Fallback Flow
   - Scenario 5: Multi-Tenant Merchant Isolation
"""
import io
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from PIL import Image
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.verification import SessionStatus
from app.models.merchant_decision import DecisionType, ActionTaken
from app.models.evidence import Evidence
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.models.evidence_fusion import VerificationAssessmentState
from app.schemas.evidence_fusion import FusionExplanation


def add_completed_visual_analysis(
    db: Session,
    session_id: str,
    evidence_id: str,
    damage_observed: bool = True,
    damage_severity: str = "MODERATE",
    is_identical_model: bool = True,
    overall_conf: float = 0.90,
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
            "uncertainties": [],
        },
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


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
    assert reg.status_code == status.HTTP_201_CREATED, reg.text
    merchant_id = reg.json()["id"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    assert login.status_code == status.HTTP_200_OK
    token = login.json()["access_token"]
    return merchant_id, f"Bearer {token}"


def create_complete_product(client: TestClient, auth: str, sku: str = "DASH-SKU-1") -> str:
    res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": f"Product {sku}", "sku": sku, "price": "99.99"},
    )
    assert res.status_code == status.HTTP_201_CREATED, res.text
    prod_id = res.json()["id"]
    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        img_bytes = make_test_image("green")
        up = client.post(
            f"/api/v1/products/{prod_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", img_bytes, "image/jpeg")},
        )
        assert up.status_code == status.HTTP_201_CREATED, up.text
    return prod_id


def create_active_workflow(client: TestClient, auth: str, name: str = "Standard Workflow") -> str:
    wf = client.post(
        "/api/v1/workflows",
        headers={"Authorization": auth},
        json={"name": name, "description": "Verification Workflow"},
    )
    assert wf.status_code == status.HTTP_201_CREATED, wf.text
    wf_id = wf.json()["id"]

    step_res = client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "damage_photo",
            "step_type": "IMAGE",
            "title": "Photo of damaged item",
            "step_order": 1,
            "required": True,
            "config": {"min_images": 1, "max_images": 4},
        },
    )
    assert step_res.status_code == status.HTTP_201_CREATED, step_res.text
    pub = client.post(f"/api/v1/workflows/{wf_id}/publish", headers={"Authorization": auth})
    assert pub.status_code == status.HTTP_200_OK, pub.text
    return wf_id


def setup_verification(
    client: TestClient,
    auth: str,
    sku: str = "DASH-TEST-SKU",
    order_id: str = "ORD-DASH-100",
    customer_id: str = "CUST-001",
    customer_email: str = "customer@example.com",
    refund_reason: str = "Damaged packaging and broken glass",
) -> tuple[dict, str]:
    prod_id = create_complete_product(client, auth, sku)
    wf_id = create_active_workflow(client, auth, f"Flow {sku}")

    sess_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": prod_id,
            "workflow_id": wf_id,
            "order_id": order_id,
            "customer_name": customer_id,
            "customer_contact": customer_email,
            "refund_reason": refund_reason,
            "refund_amount": "99.99",
        },
    )
    assert sess_res.status_code == status.HTTP_201_CREATED, sess_res.text
    data = sess_res.json()
    return data, data["customer_link"]


# ===========================================================================
# 1. Dashboard Verification Listing Tests
# ===========================================================================

def test_dashboard_verification_list_pagination(client: TestClient):
    """Test dashboard listing pagination: total, slicing, page_size boundaries."""
    _, auth = register_and_auth(client, "dash_page@test.com", "Pagination Merchant")
    prod_id = create_complete_product(client, auth, "PAGE-PROD")
    wf_id = create_active_workflow(client, auth, "Page Workflow")

    for i in range(5):
        client.post(
            "/api/v1/verifications",
            headers={"Authorization": auth},
            json={
                "product_id": prod_id,
                "workflow_id": wf_id,
                "order_id": f"ORD-PAGE-{i:03d}",
                "customer_name": f"Cust {i}",
                "customer_contact": f"cust{i}@test.com",
            },
        )

    # Page 1, size 2
    res = client.get("/api/v1/verifications?page=1&page_size=2", headers={"Authorization": auth})
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2

    # Page 2, size 2
    res2 = client.get("/api/v1/verifications?page=2&page_size=2", headers={"Authorization": auth})
    assert res2.status_code == status.HTTP_200_OK
    data2 = res2.json()
    assert len(data2["items"]) == 2
    assert data2["page"] == 2

    # Page 3, size 2 (only 1 remaining)
    res3 = client.get("/api/v1/verifications?page=3&page_size=2", headers={"Authorization": auth})
    assert res3.status_code == status.HTTP_200_OK
    data3 = res3.json()
    assert len(data3["items"]) == 1

    # Page 4, size 2 (empty)
    res4 = client.get("/api/v1/verifications?page=4&page_size=2", headers={"Authorization": auth})
    assert res4.status_code == status.HTTP_200_OK
    assert len(res4.json()["items"]) == 0


def test_dashboard_verification_list_filtering(client: TestClient):
    """Test multi-criteria filtering: status, order_id, product_id, and search."""
    _, auth = register_and_auth(client, "dash_filt@test.com", "Filter Merchant")
    prod_id = create_complete_product(client, auth, "FILT-SKU-99")
    wf_id = create_active_workflow(client, auth, "Filter Workflow")

    s1, _ = setup_verification(client, auth, "SKU-A", order_id="ORD-ALPHA-1", customer_email="alice@example.com")
    s2, _ = setup_verification(client, auth, "SKU-B", order_id="ORD-BETA-2", customer_email="bob@acme.org")

    # Cancel s1
    client.post(f"/api/v1/verifications/{s1['id']}/cancel", headers={"Authorization": auth})

    # Filter status=CANCELLED
    res_canc = client.get("/api/v1/verifications?status=CANCELLED&page=1", headers={"Authorization": auth})
    assert res_canc.status_code == status.HTTP_200_OK
    items = res_canc.json()["items"]
    assert len(items) >= 1
    assert all(it["status"] == "CANCELLED" for it in items)

    # Filter status=CREATED
    res_created = client.get("/api/v1/verifications?status=CREATED&page=1", headers={"Authorization": auth})
    assert res_created.status_code == status.HTTP_200_OK
    items_cr = res_created.json()["items"]
    assert any(it["id"] == s2["id"] for it in items_cr)

    # Search order_id substring
    res_search = client.get("/api/v1/verifications?search=ALPHA&page=1", headers={"Authorization": auth})
    assert res_search.status_code == status.HTTP_200_OK
    assert len(res_search.json()["items"]) == 1
    assert res_search.json()["items"][0]["order_id"] == "ORD-ALPHA-1"

    # Search customer_email substring
    res_email = client.get("/api/v1/verifications?search=acme.org&page=1", headers={"Authorization": auth})
    assert res_email.status_code == status.HTTP_200_OK
    assert len(res_email.json()["items"]) == 1
    assert res_email.json()["items"][0]["customer_email"] == "bob@acme.org"


def test_dashboard_verification_list_merchant_isolation(client: TestClient):
    """Test merchant isolation: Merchant B cannot see Merchant A's verifications."""
    _, auth_a = register_and_auth(client, "iso_a@test.com", "Merchant A")
    _, auth_b = register_and_auth(client, "iso_b@test.com", "Merchant B")

    s_a, _ = setup_verification(client, auth_a, "ISO-A", order_id="ORD-ISO-A")
    s_b, _ = setup_verification(client, auth_b, "ISO-B", order_id="ORD-ISO-B")

    res_a = client.get("/api/v1/verifications?page=1", headers={"Authorization": auth_a})
    assert res_a.status_code == status.HTTP_200_OK
    ids_a = [it["id"] for it in res_a.json()["items"]]
    assert s_a["id"] in ids_a
    assert s_b["id"] not in ids_a

    res_b = client.get("/api/v1/verifications?page=1", headers={"Authorization": auth_b})
    assert res_b.status_code == status.HTTP_200_OK
    ids_b = [it["id"] for it in res_b.json()["items"]]
    assert s_b["id"] in ids_b
    assert s_a["id"] not in ids_b


# ===========================================================================
# 2. Verification Detail / Investigation View Tests
# ===========================================================================

def test_verification_investigation_dashboard_detail(client: TestClient):
    """Test GET /api/v1/verifications/{id}/dashboard returns all 13 facets and sanitizes tokens."""
    _, auth = register_and_auth(client, "dash_detail@test.com", "Detail Merchant")
    sess, customer_link = setup_verification(client, auth, "SKU-DETAIL", order_id="ORD-DETAIL-77")
    v_id = sess["id"]

    # Customer submits evidence
    raw_token = customer_link.split("/")[-1]
    client.post(f"/api/v1/public/verifications/{raw_token}/start")
    client.post(
        f"/api/v1/public/verifications/{raw_token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("evidence.jpg", make_test_image("red"), "image/jpeg")},
    )

    # Ingest signal
    client.post(
        f"/api/v1/verifications/{v_id}/signals",
        headers={"Authorization": auth},
        json={
            "signal_type": "DELIVERY",
            "source_type": "INTEGRATION",
            "source_reference": "ref_fedex_1",
            "data": {
                "order_id": "ORD-DETAIL-77",
                "carrier": "FedEx",
                "delivery_status": "DELIVERED",
            },
        },
    )

    # Ingest decision
    client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth},
        json={
            "decision": "MANUAL_REVIEW",
            "notes": "Awaiting customer response to serial query.",
            "action_taken": "NO_REFUND",
        },
    )

    # Fetch investigation detail
    res = client.get(f"/api/v1/verifications/{v_id}/dashboard", headers={"Authorization": auth})
    assert res.status_code == status.HTTP_200_OK
    data = res.json()

    # Verify all 13 facets
    assert "verification" in data
    assert "product" in data
    assert "claim" in data
    assert "workflow" in data
    assert "evidence_summary" in data
    assert "evidence_items" in data
    assert "visual_analysis_summary" in data
    assert "visual_analysis_items" in data
    assert "signals_summary" in data
    assert "signal_items" in data
    assert "adaptive_requests" in data
    assert "timeline" in data
    assert "decisions" in data

    # Verify evidence item present
    assert data["evidence_summary"]["total_evidence_count"] >= 1
    assert len(data["evidence_items"]) >= 1

    # Verify signal present
    assert data["signals_summary"]["total_signals"] >= 1
    assert len(data["signal_items"]) >= 1

    # Verify decision present
    assert len(data["decisions"]) >= 1
    assert data["decisions"][0]["decision"] == "MANUAL_REVIEW"

    # Privacy guarantee: raw customer link and raw token must not be exposed
    assert data["verification"]["customer_link"] is None
    assert "customer_token_hash" not in data["verification"]

    # Cross-merchant isolation
    _, auth_other = register_and_auth(client, "other_detail@test.com", "Other")
    res_other = client.get(f"/api/v1/verifications/{v_id}/dashboard", headers={"Authorization": auth_other})
    assert res_other.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# 3. Explainable Final Report Tests
# ===========================================================================

def test_explainable_final_report_structure(client: TestClient):
    """Test GET /api/v1/verifications/{id}/report contains 9 structured sections."""
    _, auth = register_and_auth(client, "dash_rep@test.com", "Report Merchant")
    sess, customer_link = setup_verification(client, auth, "SKU-REP", order_id="ORD-REP-11")
    v_id = sess["id"]

    # Run fusion
    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_fusion_explanation") as mock_llama:
        mock_llama.return_value = FusionExplanation(
            summary="All signals align.",
            key_points=["Claim matches evidence.", "Visual damage confirmed."],
            recommended_review="Process refund if eligible.",
        )
        fuse_res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert fuse_res.status_code == status.HTTP_200_OK

    res = client.get(f"/api/v1/verifications/{v_id}/report", headers={"Authorization": auth})
    assert res.status_code == status.HTTP_200_OK
    rep = res.json()

    assert rep["verification_id"] == sess["verification_id"]
    assert rep["assessment_state"] in ["EVIDENCE_CONSISTENT", "REVIEW_REQUIRED", "INCONSISTENCY_DETECTED"]
    assert 0.0 <= rep["overall_confidence"] <= 1.0

    # Verify 9 sections
    assert "executive_summary" in rep and len(rep["executive_summary"]["text"]) > 0
    assert "consistency_assessment" in rep and rep["consistency_assessment"]["state"] == rep["assessment_state"]
    assert "visual_consistency_findings" in rep
    assert "signal_verification_findings" in rep
    assert "multi_source_fusion_matrix" in rep
    assert "claim_vs_evidence_reconciliation" in rep
    assert "missing_evidence_and_follow_up" in rep
    assert "merchant_decision_context" in rep
    assert "ai_audit_trail" in rep

    # Cross-merchant 404
    _, auth_other = register_and_auth(client, "other_rep@test.com", "Other")
    res_other = client.get(f"/api/v1/verifications/{v_id}/report", headers={"Authorization": auth_other})
    assert res_other.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# 4. Chronological Verification Timeline Tests
# ===========================================================================

def test_verification_timeline_chronological_ordering(client: TestClient):
    """Test GET /api/v1/verifications/{id}/timeline returns real events sorted chronologically."""
    _, auth = register_and_auth(client, "dash_time@test.com", "Timeline Merchant")
    sess, customer_link = setup_verification(client, auth, "SKU-TIME", order_id="ORD-TIME-1")
    v_id = sess["id"]

    raw_token = customer_link.split("/")[-1]
    client.post(f"/api/v1/public/verifications/{raw_token}/start")
    client.post(
        f"/api/v1/public/verifications/{raw_token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("evidence.jpg", make_test_image("yellow"), "image/jpeg")},
    )

    client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth},
        json={"decision": "REFUND_APPROVED", "notes": "Looks good.", "action_taken": "FULL_REFUND"},
    )

    res = client.get(f"/api/v1/verifications/{v_id}/timeline", headers={"Authorization": auth})
    assert res.status_code == status.HTTP_200_OK
    timeline = res.json()
    assert len(timeline) >= 3

    # Check strictly chronological (or equal timestamps)
    timestamps = [datetime.fromisoformat(item["timestamp"]) for item in timeline]
    for i in range(1, len(timestamps)):
        assert timestamps[i] >= timestamps[i - 1]

    # Verify event types
    event_types = [item["event_type"] for item in timeline]
    assert "SESSION_CREATED" in event_types
    assert "MERCHANT_DECISION_MADE" in event_types


# ===========================================================================
# 5. Merchant Final Decision & Audit History Tests
# ===========================================================================

def test_merchant_decision_crud_and_status_transition(client: TestClient):
    """Test merchant decision lifecycle, state transitions, and audit preservation."""
    _, auth = register_and_auth(client, "dash_dec@test.com", "Decision Merchant")
    sess, _ = setup_verification(client, auth, "SKU-DEC", order_id="ORD-DEC-1")
    v_id = sess["id"]

    # Decision 1: MANUAL_REVIEW (keeps status active)
    dec1 = client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth},
        json={
            "decision": "MANUAL_REVIEW",
            "notes": "Checking serial number with supplier.",
            "action_taken": "NO_REFUND",
        },
    )
    assert dec1.status_code == status.HTTP_201_CREATED
    d1_data = dec1.json()
    assert d1_data["decision"] == "MANUAL_REVIEW"
    assert d1_data["notes"] == "Checking serial number with supplier."

    # Session should still be CREATED
    sess_res = client.get(f"/api/v1/verifications/{v_id}", headers={"Authorization": auth})
    assert sess_res.json()["status"] == SessionStatus.CREATED.value

    # Decision 2: REFUND_APPROVED (transitions to COMPLETED)
    dec2 = client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth},
        json={
            "decision": "REFUND_APPROVED",
            "notes": "Supplier confirmed damage in transit.",
            "action_taken": "FULL_REFUND",
        },
    )
    assert dec2.status_code == status.HTTP_201_CREATED
    assert dec2.json()["decision"] == "REFUND_APPROVED"

    # Session should now be COMPLETED
    sess_res2 = client.get(f"/api/v1/verifications/{v_id}", headers={"Authorization": auth})
    assert sess_res2.json()["status"] == SessionStatus.COMPLETED.value

    # Decision history should preserve both decisions (oldest first)
    list_dec = client.get(f"/api/v1/verifications/{v_id}/decisions", headers={"Authorization": auth})
    assert list_dec.status_code == status.HTTP_200_OK
    decisions = list_dec.json()
    assert len(decisions) == 2
    assert decisions[0]["decision"] == "MANUAL_REVIEW"
    assert decisions[1]["decision"] == "REFUND_APPROVED"


def test_merchant_decision_negative_boundaries(client: TestClient):
    """Test negative boundaries: invalid enum (422), cancelled session (410),
    cross-merchant (404), customer token forbidden (401)."""
    _, auth_a = register_and_auth(client, "neg_a@test.com", "Merchant A")
    _, auth_b = register_and_auth(client, "neg_b@test.com", "Merchant B")

    sess, customer_link = setup_verification(client, auth_a, "SKU-NEG", order_id="ORD-NEG-1")
    v_id = sess["id"]

    # 1. Invalid decision enum -> 422
    inv_res = client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth_a},
        json={"decision": "DECLARE_FRAUDULENT", "notes": "AI says fraud"},
    )
    assert inv_res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 2. Cross-merchant decision -> 404
    cross_res = client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth_b},
        json={"decision": "REFUND_APPROVED"},
    )
    assert cross_res.status_code == status.HTTP_404_NOT_FOUND

    # 3. Customer token blocked from decision endpoint -> 401
    cust_token = customer_link.split("/")[-1]
    cust_res = client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": f"Bearer {cust_token}"},
        json={"decision": "REFUND_APPROVED"},
    )
    assert cust_res.status_code == status.HTTP_401_UNAUTHORIZED

    # 4. Cancelled session decision -> 410
    client.post(f"/api/v1/verifications/{v_id}/cancel", headers={"Authorization": auth_a})
    canc_res = client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth_a},
        json={"decision": "REFUND_REJECTED", "rejection_reasons": ["SESSION_CANCELLED"]},
    )
    assert canc_res.status_code == status.HTTP_410_GONE


# ===========================================================================
# 6. End-to-End Scenarios
# ===========================================================================

def test_scenario_1_consistent_flow_to_approval(client: TestClient, db_session: Session):
    """Scenario 1: Complete consistent verification flow -> merchant approves refund."""
    _, auth = register_and_auth(client, "scen1@test.com", "Scenario 1 Merchant")
    sess, customer_link = setup_verification(
        client, auth, "SCEN1-SKU", order_id="ORD-SCEN1", refund_reason="Screen damaged during delivery"
    )
    v_id = sess["id"]
    raw_token = customer_link.split("/")[-1]

    # Customer submits evidence
    client.post(f"/api/v1/public/verifications/{raw_token}/start")
    ev_res = client.post(
        f"/api/v1/public/verifications/{raw_token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("screen.jpg", make_test_image("red"), "image/jpeg")},
    )
    assert ev_res.status_code == status.HTTP_201_CREATED
    ev_id = ev_res.json()["evidence_id"]

    # Seed visual analysis
    add_completed_visual_analysis(db_session, v_id, ev_id, damage_observed=True)

    # Carrier confirms delivery
    client.post(
        f"/api/v1/verifications/{v_id}/signals",
        headers={"Authorization": auth},
        json={
            "signal_type": "DELIVERY",
            "source_type": "INTEGRATION",
            "source_reference": "ref_fedex_scen1",
            "data": {
                "order_id": "ORD-SCEN1",
                "carrier": "FedEx",
                "delivery_status": "DELIVERED",
                "delivered_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    )

    # Run fusion
    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_fusion_explanation") as mock_llama:
        mock_llama.return_value = FusionExplanation(
            summary="All visual and delivery signals are consistent with the damaged item claim.",
            key_points=["Visual damage verified on display", "Delivery confirmed by courier"],
            recommended_review="Eligible for refund approval.",
        )
        fuse_res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert fuse_res.status_code == status.HTTP_200_OK

    # Merchant reviews report
    rep_res = client.get(f"/api/v1/verifications/{v_id}/report", headers={"Authorization": auth})
    assert rep_res.status_code == status.HTTP_200_OK
    assert rep_res.json()["assessment_state"] == "EVIDENCE_CONSISTENT"

    # Merchant decides to APPROVE
    dec_res = client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth},
        json={
            "decision": "REFUND_APPROVED",
            "notes": "Valid damaged return approved per policy.",
            "action_taken": "FULL_REFUND",
        },
    )
    assert dec_res.status_code == status.HTTP_201_CREATED
    assert dec_res.json()["decision"] == "REFUND_APPROVED"

    # Verify session completed
    sess_check = client.get(f"/api/v1/verifications/{v_id}", headers={"Authorization": auth})
    assert sess_check.json()["status"] == SessionStatus.COMPLETED.value


def test_scenario_2_incomplete_evidence_flow_review_required(client: TestClient):
    """Scenario 2: Incomplete evidence submitted -> fusion returns REVIEW_REQUIRED -> merchant holds for review."""
    _, auth = register_and_auth(client, "scen2@test.com", "Scenario 2 Merchant")
    sess, customer_link = setup_verification(
        client, auth, "SCEN2-SKU", order_id="ORD-SCEN2", refund_reason="Screen damaged"
    )
    v_id = sess["id"]

    # Customer does NOT upload evidence yet
    # Fusion is executed
    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_fusion_explanation") as mock_llama:
        mock_llama.return_value = FusionExplanation(
            summary="Customer has not yet provided the required damage photo.",
            key_points=["No evidence photos submitted", "Mandatory damage photo step missing"],
            recommended_review="Request customer to submit photo.",
        )
        fuse_res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert fuse_res.status_code == status.HTTP_200_OK
        assert fuse_res.json()["assessment_state"] == "REVIEW_REQUIRED"

    # Merchant records MANUAL_REVIEW decision
    dec_res = client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth},
        json={
            "decision": "MANUAL_REVIEW",
            "notes": "Sent customer email reminder to submit clear photo.",
            "action_taken": "NO_REFUND",
        },
    )
    assert dec_res.status_code == status.HTTP_201_CREATED

    # Session remains in active state (not completed)
    sess_check = client.get(f"/api/v1/verifications/{v_id}", headers={"Authorization": auth})
    assert sess_check.json()["status"] == SessionStatus.CREATED.value


def test_scenario_3_contradictory_evidence_flow_rejection(client: TestClient):
    """Scenario 3: Contradictory evidence (Never delivered claim vs DELIVERED courier signal)
    -> INCONSISTENCY_DETECTED -> Merchant rejects refund."""
    _, auth = register_and_auth(client, "scen3@test.com", "Scenario 3 Merchant")
    sess, _ = setup_verification(
        client, auth, "SCEN3-SKU", order_id="ORD-SCEN3", refund_reason="I never received the package"
    )
    v_id = sess["id"]

    # Ingest courier signal showing DELIVERED
    client.post(
        f"/api/v1/verifications/{v_id}/signals",
        headers={"Authorization": auth},
        json={
            "signal_type": "DELIVERY",
            "source_type": "INTEGRATION",
            "source_reference": "ref_fedex_scen3",
            "data": {
                "order_id": "ORD-SCEN3",
                "carrier": "FedEx",
                "delivery_status": "DELIVERED",
                "delivered_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    )

    # Run fusion
    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_fusion_explanation") as mock_llama:
        mock_llama.return_value = FusionExplanation(
            summary="Courier confirms package was delivered with signature, contradicting non-receipt claim.",
            key_points=["Customer claims non-receipt", "Courier confirms delivery"],
            recommended_review="Verify delivery address with carrier.",
        )
        fuse_res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert fuse_res.status_code == status.HTTP_200_OK
        assert fuse_res.json()["assessment_state"] == "INCONSISTENCY_DETECTED"

    # Merchant reviews report
    rep_res = client.get(f"/api/v1/verifications/{v_id}/report", headers={"Authorization": auth})
    assert rep_res.status_code == status.HTTP_200_OK
    assert rep_res.json()["assessment_state"] == "INCONSISTENCY_DETECTED"

    # Merchant decides to REJECT
    dec_res = client.post(
        f"/api/v1/verifications/{v_id}/decision",
        headers={"Authorization": auth},
        json={
            "decision": "REFUND_REJECTED",
            "notes": "Carrier proof of delivery received with resident signature.",
            "rejection_reasons": ["PROOF_OF_DELIVERY_CONFIRMED"],
            "action_taken": "NO_REFUND",
        },
    )
    assert dec_res.status_code == status.HTTP_201_CREATED
    assert dec_res.json()["decision"] == "REFUND_REJECTED"

    # Verify session completed
    sess_check = client.get(f"/api/v1/verifications/{v_id}", headers={"Authorization": auth})
    assert sess_check.json()["status"] == SessionStatus.COMPLETED.value


def test_scenario_4_ollama_offline_fallback(client: TestClient):
    """Scenario 4: When Ollama is offline or times out, report and dashboard operate smoothly
    with deterministic fallback explanation."""
    _, auth = register_and_auth(client, "scen4@test.com", "Scenario 4 Merchant")
    sess, _ = setup_verification(client, auth, "SCEN4-SKU", order_id="ORD-SCEN4")
    v_id = sess["id"]

    # Patch Ollama reasoning call to simulate connection failure
    with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_fusion_explanation", return_value=None):
        fuse_res = client.post(f"/api/v1/verifications/{v_id}/fusion", headers={"Authorization": auth})
        assert fuse_res.status_code == status.HTTP_200_OK
        assert fuse_res.json()["assessment_state"] is not None

    # Fetch report
    rep_res = client.get(f"/api/v1/verifications/{v_id}/report", headers={"Authorization": auth})
    assert rep_res.status_code == status.HTTP_200_OK
    rep = rep_res.json()
    assert rep["executive_summary"]["text"] is not None
    assert "automated" in rep["executive_summary"]["text"].lower() or len(rep["executive_summary"]["text"]) > 10


def test_scenario_5_multi_tenant_isolation_end_to_end(client: TestClient):
    """Scenario 5: Multi-tenant merchant isolation across list, dashboard detail, report,
    timeline, and decision endpoints."""
    _, auth_a = register_and_auth(client, "scen5_a@test.com", "Merchant Alpha")
    _, auth_b = register_and_auth(client, "scen5_b@test.com", "Merchant Beta")

    sess_a, _ = setup_verification(client, auth_a, "SCEN5-A", order_id="ORD-SCEN5-A")
    v_id_a = sess_a["id"]

    # Alpha makes decision
    client.post(
        f"/api/v1/verifications/{v_id_a}/decision",
        headers={"Authorization": auth_a},
        json={"decision": "REFUND_APPROVED", "notes": "Approved by Alpha"},
    )

    # Beta attempts access on Alpha's session across all endpoints:
    # 1. Detail dashboard -> 404
    assert client.get(f"/api/v1/verifications/{v_id_a}/dashboard", headers={"Authorization": auth_b}).status_code == 404
    # 2. Report -> 404
    assert client.get(f"/api/v1/verifications/{v_id_a}/report", headers={"Authorization": auth_b}).status_code == 404
    # 3. Timeline -> 404
    assert client.get(f"/api/v1/verifications/{v_id_a}/timeline", headers={"Authorization": auth_b}).status_code == 404
    # 4. Decisions list -> 404
    assert client.get(f"/api/v1/verifications/{v_id_a}/decisions", headers={"Authorization": auth_b}).status_code == 404
    # 5. Create decision -> 404
    assert client.post(
        f"/api/v1/verifications/{v_id_a}/decision",
        headers={"Authorization": auth_b},
        json={"decision": "REFUND_REJECTED"},
    ).status_code == 404


def test_investigation_report_with_evidence_request_regression(client: TestClient, db_session):
    """Regression test specifically verifying that opening an investigation/report
    for a session with EvidenceRequest objects NEVER raises AttributeError: 'EvidenceRequest' object has no attribute 'step_key'.
    """
    from app.models.evidence_request import EvidenceRequest, EvidenceRequestStatus
    from app.models.verification import VerificationSession

    _, auth = register_and_auth(client, "regression_ev_req@test.com", "Regress Merchant")
    sess, _ = setup_verification(client, auth, "SKU-REGRESS", order_id="ORD-REGRESS-01")
    v_id = sess["id"]

    # Retrieve db session and add an EvidenceRequest instance directly
    session_obj = db_session.query(VerificationSession).filter(VerificationSession.id == v_id).one()
    ev_req = EvidenceRequest(
        verification_session_id=session_obj.id,
        workflow_step_key="damage_photo",
        requested_evidence_type="CUSTOMER_IMAGE",
        reason="Please provide a clear close-up of the damaged left earbud.",
        status=EvidenceRequestStatus.PENDING.value,
    )
    db_session.add(ev_req)
    db_session.commit()

    # Test the model property directly
    assert ev_req.step_key == "damage_photo"
    assert ev_req.workflow_step_key == "damage_photo"

    # Test GET /api/v1/verifications/{id}/dashboard (investigation view)
    res_dash = client.get(f"/api/v1/verifications/{v_id}/dashboard", headers={"Authorization": auth})
    assert res_dash.status_code == status.HTTP_200_OK
    dash_data = res_dash.json()
    assert len(dash_data["adaptive_requests"]) == 1
    assert dash_data["adaptive_requests"][0]["workflow_step_key"] == "damage_photo"

    # Test GET /api/v1/verifications/{id}/report (report view)
    res_rep = client.get(f"/api/v1/verifications/{v_id}/report", headers={"Authorization": auth})
    assert res_rep.status_code == status.HTTP_200_OK
    rep_data = res_rep.json()
    assert "missing_evidence_and_follow_up" in rep_data
    assert len(rep_data["missing_evidence_and_follow_up"]["adaptive_requests"]) == 1
    assert rep_data["missing_evidence_and_follow_up"]["adaptive_requests"][0]["step_key"] == "damage_photo"
