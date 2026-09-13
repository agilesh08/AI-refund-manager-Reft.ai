"""Automated unit and integration test suite for Milestone 8: Local AI Reasoning Engine (Ollama + Llama 3.2 3B)."""
import io
import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ai.ollama_reasoning import OllamaReasoningService, LLAMA_REASONING_SYSTEM_INSTRUCTION
from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.product_reference import ReferenceAngle
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.models.reasoning_run import ReasoningRun, ReasoningRunStatus
from app.schemas.reasoning import (
    ReasoningAction,
    ReasoningResult,
    ReasoningRunResponse,
    MissingEvidenceItem,
)
from app.services import reasoning_context_service, reasoning_service


def make_test_image(color: str = "green", fmt: str = "JPEG") -> bytes:
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
    sku: str = "PROD-REASON-1",
) -> tuple[dict, str]:
    """Setup product with 4 angles, active workflow with 2 steps, and started session.
    
    Returns (session_dict, customer_token).
    """
    # 1. Product
    prod_res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": f"Product {sku}", "sku": sku, "price": "299.99"},
    )
    product_id = prod_res.json()["id"]

    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        img_bytes = make_test_image(color="purple")
        client.post(
            f"/api/v1/products/{product_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", img_bytes, "image/jpeg")},
        )

    # 2. Workflow with 2 steps
    wf_res = client.post(
        "/api/v1/workflows",
        headers={"Authorization": auth},
        json={"name": f"Workflow {sku}"},
    )
    wf_id = wf_res.json()["id"]

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

    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "customer_explanation",
            "step_type": "TEXT",
            "title": "Customer Explanation",
            "step_order": 2,
            "required": False,
            "config": {"min_length": 5, "max_length": 500},
        },
    )

    client.post(
        f"/api/v1/workflows/{wf_id}/publish",
        headers={"Authorization": auth},
    )

    # 3. Create verification session
    sess_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": product_id,
            "workflow_id": wf_id,
            "order_id": f"ORD-{sku}",
            "customer_name": "Jane Doe",
            "refund_reason": "Screen is completely cracked upon delivery",
        },
    )
    sess_data = sess_res.json()
    token = sess_data["customer_link"].split("/")[-1]

    # Start session as customer
    client.post(f"/api/v1/public/verifications/{token}/start")

    return sess_data, token


class TestReasoningActionsAndValidation:
    """Test standard reasoning actions and output validation."""

    def test_reasoning_success_continue_workflow(self, client: TestClient, db_session: Session):
        """1. Successful reasoning pass recommending CONTINUE_WORKFLOW with valid next_step_key."""
        _, auth = register_and_auth(client, "reason1@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R1")
        verification_id = sess_data["id"]

        mock_result = {
            "action": "CONTINUE_WORKFLOW",
            "reasoning_summary": "Damage photo is recorded; workflow requires customer explanation next.",
            "confidence": 0.85,
            "next_step_key": "customer_explanation",
            "missing_evidence": [],
            "observations_used": ["damage_photo submitted"],
            "limitations": ["Customer explanation pending"],
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_result):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "COMPLETED"
        assert data["result"]["action"] == "CONTINUE_WORKFLOW"
        assert data["result"]["next_step_key"] == "customer_explanation"
        assert data["result"]["confidence"] == 0.85
        assert len(data["input_context_hash"]) == 64

    def test_reasoning_success_accept_evidence(self, client: TestClient, db_session: Session):
        """2. Successful reasoning with action ACCEPT_EVIDENCE."""
        _, auth = register_and_auth(client, "reason2@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R2")
        verification_id = sess_data["id"]

        mock_result = {
            "action": "ACCEPT_EVIDENCE",
            "reasoning_summary": "Current photo evidence conforms to required specifications.",
            "confidence": 0.90,
            "next_step_key": None,
            "missing_evidence": [],
            "observations_used": ["Visual match observed"],
            "limitations": [],
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_result):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "COMPLETED"
        assert data["result"]["action"] == "ACCEPT_EVIDENCE"

    def test_reasoning_success_request_more_evidence(self, client: TestClient, db_session: Session):
        """3. Successful reasoning with action REQUEST_MORE_EVIDENCE and missing evidence list."""
        _, auth = register_and_auth(client, "reason3@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R3")
        verification_id = sess_data["id"]

        mock_result = {
            "action": "REQUEST_MORE_EVIDENCE",
            "reasoning_summary": "Close-up photo of the crack is needed to evaluate claimed damage.",
            "confidence": 0.75,
            "next_step_key": "damage_photo",
            "missing_evidence": [
                {"evidence_type": "CUSTOMER_IMAGE", "purpose": "Close-up view of screen corner crack"}
            ],
            "observations_used": ["Wide angle photo blurry"],
            "limitations": ["Damage severity not visible"],
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_result):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "COMPLETED"
        assert data["result"]["action"] == "REQUEST_MORE_EVIDENCE"
        assert len(data["result"]["missing_evidence"]) == 1
        assert data["result"]["missing_evidence"][0]["evidence_type"] == "CUSTOMER_IMAGE"

    def test_reasoning_success_complete_verification(self, client: TestClient, db_session: Session):
        """4. Successful reasoning with action COMPLETE_VERIFICATION."""
        _, auth = register_and_auth(client, "reason4@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R4")
        verification_id = sess_data["id"]

        mock_result = {
            "action": "COMPLETE_VERIFICATION",
            "reasoning_summary": "All required workflow steps have been submitted and analyzed.",
            "confidence": 0.95,
            "next_step_key": None,
            "missing_evidence": [],
            "observations_used": ["All steps fulfilled"],
            "limitations": [],
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_result):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "COMPLETED"
        assert data["result"]["action"] == "COMPLETE_VERIFICATION"

    def test_reasoning_structured_json_parsing(self, client: TestClient, db_session: Session):
        """5. Verifies structured JSON parsing and schema normalization from raw Ollama string."""
        raw_json_str = json.dumps({
            "action": "CONTINUE_WORKFLOW",
            "reasoning_summary": "Step 1 complete, moving to step 2.",
            "confidence": 0.8,
            "next_step_key": "customer_explanation",
            "missing_evidence": [],
            "observations_used": ["photo recorded"],
            "limitations": []
        })

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = {
            "message": {"content": raw_json_str}
        }

        with patch.object(OllamaReasoningService, "check_health", return_value=True), \
             patch.object(OllamaReasoningService, "check_model_available", return_value=True), \
             patch("httpx.Client.post", return_value=mock_http_response):
            service = OllamaReasoningService()
            result = service.generate_reasoning({"test": "context"})
            assert result.action == ReasoningAction.CONTINUE_WORKFLOW
            assert result.confidence == 0.8


class TestGuardrailsAndWorkflowAuthority:
    """Test guardrails against invalid actions, invented steps, and workflow snapshot authority."""

    def test_reasoning_invalid_action_rejected(self, client: TestClient, db_session: Session):
        """6. Llama attempts invalid action like FRAUD or REJECT_REFUND -> run status is FAILED."""
        _, auth = register_and_auth(client, "reason6@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R6")
        verification_id = sess_data["id"]

        mock_invalid = {
            "action": "FRAUD_DETECTED",
            "reasoning_summary": "System believes claim needs review.",
            "confidence": 0.99,
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_invalid):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "FAILED"
        assert "validation error" in data["error_message"].lower() or "not in the allowed" in data["error_message"].lower()

    def test_reasoning_invalid_next_step_rejected(self, client: TestClient, db_session: Session):
        """7. Llama suggests an invented step key not in workflow snapshot -> run status is FAILED."""
        _, auth = register_and_auth(client, "reason7@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R7")
        verification_id = sess_data["id"]

        mock_invented_step = {
            "action": "CONTINUE_WORKFLOW",
            "reasoning_summary": "Customer should provide government ID photo.",
            "confidence": 0.8,
            "next_step_key": "government_id_photo",
            "missing_evidence": [],
            "observations_used": [],
            "limitations": [],
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_invented_step):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "FAILED"
        assert "not exist in the session's frozen workflow snapshot" in data["error_message"]

    def test_reasoning_frozen_workflow_snapshot_used(self, client: TestClient, db_session: Session):
        """8. Verifies reasoning context uses the frozen workflow snapshot rather than querying live workflow."""
        _, auth = register_and_auth(client, "reason8@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R8")

        session_model = db_session.execute(
            select(VerificationSession).where(VerificationSession.id == sess_data["id"])
        ).scalar_one()

        ctx = reasoning_context_service.build_reasoning_context(session_model, [], [])
        step_keys = [s["step_key"] for s in ctx["workflow"]["allowed_next_steps"]]
        assert "damage_photo" in step_keys
        assert "customer_explanation" in step_keys

    def test_reasoning_live_workflow_changes_do_not_affect_session(self, client: TestClient, db_session: Session):
        """9. Modifying the live workflow template does NOT alter the session's reasoning context."""
        _, auth = register_and_auth(client, "reason9@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R9")

        # Get workflow ID
        wf_list = client.get("/api/v1/workflows", headers={"Authorization": auth}).json()
        wf_id = wf_list[0]["id"]

        # Add a 3rd step to the live workflow
        client.post(
            f"/api/v1/workflows/{wf_id}/steps",
            headers={"Authorization": auth},
            json={
                "step_key": "unboxing_video",
                "step_type": "VIDEO",
                "title": "Unboxing Video",
                "step_order": 3,
                "required": False,
                "config": {"max_duration_seconds": 60},
            },
        )

        session_model = db_session.execute(
            select(VerificationSession).where(VerificationSession.id == sess_data["id"])
        ).scalar_one()

        ctx = reasoning_context_service.build_reasoning_context(session_model, [], [])
        snapshot_steps = [s["step_key"] for s in ctx["workflow"]["allowed_next_steps"]]
        assert "unboxing_video" not in snapshot_steps
        assert len(snapshot_steps) == 2

    def test_reasoning_terminal_session_rejected(self, client: TestClient, db_session: Session):
        """10. Cancelled session returns 410 when attempting reasoning."""
        _, auth = register_and_auth(client, "reason30@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R30")
        verification_id = sess_data["id"]

        # Cancel the session
        client.post(
            f"/api/v1/verifications/{verification_id}/cancel",
            headers={"Authorization": auth},
            json={"reason": "Customer withdrew refund claim"},
        )

        res = client.post(
            f"/api/v1/verifications/{verification_id}/reason",
            headers={"Authorization": auth},
        )
        assert res.status_code == status.HTTP_410_GONE


class TestContextBuildingAndFactCategorization:
    """Test strict categorization of facts in reasoning context."""

    def test_reasoning_customer_text_labeled_customer_stated(self, client: TestClient, db_session: Session):
        """11. Customer claim and text explanation are strictly labeled CUSTOMER_STATED."""
        _, auth = register_and_auth(client, "reason10@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R10")

        # Submit customer text evidence
        client.post(
            f"/api/v1/public/verifications/{token}/evidence/text",
            json={
                "workflow_step_key": "customer_explanation",
                "text": "The box arrived crushed and the screen was completely shattered.",
            },
        )

        session_model = db_session.execute(
            select(VerificationSession).where(VerificationSession.id == sess_data["id"])
        ).scalar_one()
        ev_items = db_session.execute(
            select(Evidence).where(Evidence.verification_session_id == session_model.id)
        ).scalars().all()

        ctx = reasoning_context_service.build_reasoning_context(session_model, ev_items, [])
        # Both refund_reason and customer text must be CUSTOMER_STATED
        assert len(ctx["customer_statements"]) >= 2
        for item in ctx["customer_statements"]:
            assert item["source"] == "CUSTOMER_STATED"

        statements = [item["statement"] for item in ctx["customer_statements"]]
        assert any("shattered" in s for s in statements)
        assert any("cracked" in s for s in statements)

    def test_reasoning_gemini_observations_labeled_ai_visual_observation(self, client: TestClient, db_session: Session):
        """12. Gemini visual analysis outputs are strictly labeled AI_VISUAL_OBSERVATION."""
        _, auth = register_and_auth(client, "reason11@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R11")

        # Submit image evidence
        img_bytes = make_test_image(color="red")
        ev_res = client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("damage.jpg", img_bytes, "image/jpeg")},
        )
        ev_data = ev_res.json()
        ev_pub_id = ev_data["evidence_id"]

        ev_model = db_session.execute(
            select(Evidence).where(Evidence.evidence_id == ev_pub_id)
        ).scalar_one()

        # Directly insert VisualAnalysis record
        va = VisualAnalysis(
            evidence_id=ev_model.id,
            status=VisualAnalysisStatus.COMPLETED.value,
            model_name="gemini-2.5-flash",
            prompt_version="v1",
            overall_confidence=0.92,
            result_json={
                "product_consistency": {
                    "is_same_product_type": True,
                    "matched_reference_angle": "FRONT",
                    "brand_marking_visible": True,
                    "color_consistency": "CONSISTENT",
                    "shape_consistency": "CONSISTENT",
                },
                "visible_condition": {
                    "claimed_damage_visible": True,
                    "damage_type_detected": "CRACK",
                    "damage_location": "Front glass",
                    "damage_severity_observation": "MODERATE",
                    "packaging_condition": "NOT_VISIBLE",
                },
                "key_visual_observations": ["Visible diagonal fracture on screen"],
                "uncertainties": [],
            },
        )
        db_session.add(va)
        db_session.commit()

        session_model = db_session.execute(
            select(VerificationSession).where(VerificationSession.id == sess_data["id"])
        ).scalar_one()
        ev_items = db_session.execute(
            select(Evidence).where(Evidence.verification_session_id == session_model.id)
        ).scalars().all()

        ctx = reasoning_context_service.build_reasoning_context(session_model, ev_items, [va])
        assert len(ctx["visual_observations"]) == 1
        obs = ctx["visual_observations"][0]
        assert obs["source"] == "AI_VISUAL_OBSERVATION"
        assert obs["confidence"] == 0.92
        assert obs["visible_condition"]["damage_type_detected"] == "CRACK"

    def test_reasoning_deterministic_facts_labeled(self, client: TestClient, db_session: Session):
        """13. Session, product, workflow, and evidence metadata are strictly labeled DETERMINISTIC."""
        _, auth = register_and_auth(client, "reason12@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R12")

        session_model = db_session.execute(
            select(VerificationSession).where(VerificationSession.id == sess_data["id"])
        ).scalar_one()

        ctx = reasoning_context_service.build_reasoning_context(session_model, [], [])
        assert len(ctx["deterministic_facts"]) >= 2
        for fact in ctx["deterministic_facts"]:
            assert fact["source"] == "DETERMINISTIC"

        order_fact = next(f for f in ctx["deterministic_facts"] if f["type"] == "ORDER_SIGNAL")
        assert order_fact["order_id"] == "ORD-SKU-R12"

    def test_reasoning_not_visible_uncertainty_preserved(self, client: TestClient, db_session: Session):
        """14. not_visible damage observation is preserved and not coerced to undamaged or false."""
        _, auth = register_and_auth(client, "reason13@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R13")

        img_bytes = make_test_image(color="blue")
        ev_res = client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("photo.jpg", img_bytes, "image/jpeg")},
        )
        ev_data = ev_res.json()
        ev_pub_id = ev_data["evidence_id"]

        ev_model = db_session.execute(
            select(Evidence).where(Evidence.evidence_id == ev_pub_id)
        ).scalar_one()

        va = VisualAnalysis(
            evidence_id=ev_model.id,
            status=VisualAnalysisStatus.COMPLETED.value,
            model_name="gemini-2.5-flash",
            prompt_version="v1",
            overall_confidence=0.5,
            result_json={
                "product_consistency": {
                    "is_same_product_type": True,
                    "matched_reference_angle": "FRONT",
                    "brand_marking_visible": False,
                    "color_consistency": "CONSISTENT",
                    "shape_consistency": "CONSISTENT",
                },
                "visible_condition": {
                    "claimed_damage_visible": False,
                    "damage_type_detected": "NOT_VISIBLE",
                    "damage_location": "NOT_VISIBLE",
                    "damage_severity_observation": "NOT_VISIBLE",
                    "packaging_condition": "NOT_VISIBLE",
                },
                "key_visual_observations": ["Area obscured or not visible in current angle"],
                "uncertainties": ["Scratch location obstructed"],
            },
        )
        db_session.add(va)
        db_session.commit()

        session_model = db_session.execute(
            select(VerificationSession).where(VerificationSession.id == sess_data["id"])
        ).scalar_one()
        ev_items = db_session.execute(
            select(Evidence).where(Evidence.verification_session_id == session_model.id)
        ).scalars().all()

        ctx = reasoning_context_service.build_reasoning_context(session_model, ev_items, [va])
        img_obs = ctx["visual_observations"][0]
        assert img_obs["visible_condition"]["damage_type_detected"] == "NOT_VISIBLE"
        assert img_obs["visible_condition"]["damage_severity_observation"] == "NOT_VISIBLE"

    def test_reasoning_insufficient_evidence_handling(self, client: TestClient, db_session: Session):
        """15. When zero evidence has been submitted, context shows empty evidence list."""
        _, auth = register_and_auth(client, "reason14@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R14")

        session_model = db_session.execute(
            select(VerificationSession).where(VerificationSession.id == sess_data["id"])
        ).scalar_one()

        ctx = reasoning_context_service.build_reasoning_context(session_model, [], [])
        assert ctx["evidence_submitted"] == []
        assert ctx["workflow"]["current_step"]["step_key"] == "damage_photo"


class TestFailSafeResilience:
    """Test that all AI reasoning failures record FAILED status without affecting session or evidence."""

    def test_reasoning_ollama_unavailable_failsafe(self, client: TestClient, db_session: Session):
        """16. Ollama connection error -> run status is FAILED, session remains IN_PROGRESS."""
        _, auth = register_and_auth(client, "reason15@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R15")
        verification_id = sess_data["id"]

        with patch(
            "app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning",
            side_effect=RuntimeError("Cannot connect to Ollama daemon at http://localhost:11434"),
        ):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "FAILED"
        assert "Cannot connect to Ollama" in data["error_message"]

        # Verification session still IN_PROGRESS
        sess_check = client.get(f"/api/v1/verifications/{verification_id}", headers={"Authorization": auth}).json()
        assert sess_check["status"] == "IN_PROGRESS"

    def test_reasoning_ollama_timeout_failsafe(self, client: TestClient, db_session: Session):
        """17. Ollama timeout -> run status is FAILED, session untouched."""
        _, auth = register_and_auth(client, "reason16@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R16")
        verification_id = sess_data["id"]

        with patch(
            "app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning",
            side_effect=TimeoutError("Ollama inference timed out after 60s"),
        ):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "FAILED"
        assert "timed out" in data["error_message"]

    def test_reasoning_malformed_json_failsafe(self, client: TestClient, db_session: Session):
        """18. Malformed JSON from model -> run status is FAILED."""
        _, auth = register_and_auth(client, "reason17@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R17")
        verification_id = sess_data["id"]

        with patch(
            "app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning",
            side_effect=ValueError("Failed to parse JSON response from Ollama: invalid syntax"),
        ):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "FAILED"
        assert "Failed to parse JSON" in data["error_message"]

    def test_reasoning_schema_validation_failure_failsafe(self, client: TestClient, db_session: Session):
        """19. Ollama output missing required fields -> status is FAILED."""
        _, auth = register_and_auth(client, "reason18@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R18")
        verification_id = sess_data["id"]

        # Missing 'confidence' and 'reasoning_summary'
        incomplete_output = {"action": "CONTINUE_WORKFLOW"}

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=incomplete_output):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "FAILED"
        assert "validation error" in data["error_message"].lower()

    def test_reasoning_prohibited_fraud_phrase_rejected(self, client: TestClient, db_session: Session):
        """20. Reasoning summary containing 'fraudulent customer' is rejected by Pydantic validator."""
        _, auth = register_and_auth(client, "reason19@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R19")
        verification_id = sess_data["id"]

        prohibited_output = {
            "action": "ACCEPT_EVIDENCE",
            "reasoning_summary": "We believe this is a fraudulent customer attempting a return.",
            "confidence": 0.9,
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=prohibited_output):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "FAILED"
        assert "prohibited verdict phrase" in data["error_message"]

    def test_reasoning_prohibited_refund_phrase_rejected(self, client: TestClient, db_session: Session):
        """21. Reasoning summary containing 'refund approved' is rejected by Pydantic validator."""
        _, auth = register_and_auth(client, "reason20@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R20")
        verification_id = sess_data["id"]

        prohibited_output = {
            "action": "COMPLETE_VERIFICATION",
            "reasoning_summary": "All evidence submitted and refund approved for customer.",
            "confidence": 0.9,
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=prohibited_output):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "FAILED"
        assert "prohibited verdict phrase" in data["error_message"]

    def test_reasoning_customer_evidence_status_unchanged_on_failure(self, client: TestClient, db_session: Session):
        """22. Customer evidence retains its status (e.g. READY_FOR_ANALYSIS) when reasoning fails."""
        _, auth = register_and_auth(client, "reason21@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R21")
        verification_id = sess_data["id"]

        img_bytes = make_test_image(color="black")
        ev_res = client.post(
            f"/api/v1/public/verifications/{token}/evidence/image",
            data={"workflow_step_key": "damage_photo"},
            files={"file": ("pic.jpg", img_bytes, "image/jpeg")},
        )
        ev_data = ev_res.json()
        ev_pub_id = ev_data["evidence_id"]

        with patch(
            "app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning",
            side_effect=RuntimeError("Ollama failed"),
        ):
            client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        ev_model = db_session.execute(select(Evidence).where(Evidence.evidence_id == ev_pub_id)).scalar_one()
        assert ev_model.status == EvidenceStatus.READY_FOR_ANALYSIS.value

    def test_reasoning_verification_session_status_unchanged_on_failure(self, client: TestClient, db_session: Session):
        """23. Verification session status remains IN_PROGRESS when reasoning fails."""
        _, auth = register_and_auth(client, "reason22@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R22")
        verification_id = sess_data["id"]

        with patch(
            "app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning",
            side_effect=RuntimeError("Model error"),
        ):
            client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        sess_check = client.get(f"/api/v1/verifications/{verification_id}", headers={"Authorization": auth}).json()
        assert sess_check["status"] == "IN_PROGRESS"


class TestAuditHistoryAndIdempotency:
    """Test audit log persistence, history retrieval, and context hash caching."""

    def test_reasoning_audit_history_preserved(self, client: TestClient, db_session: Session):
        """24. Multiple reasoning runs are recorded in audit history and queryable via GET."""
        _, auth = register_and_auth(client, "reason23@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R23")
        verification_id = sess_data["id"]

        mock_res_1 = {
            "action": "CONTINUE_WORKFLOW",
            "reasoning_summary": "First reasoning pass completed.",
            "confidence": 0.8,
            "next_step_key": "damage_photo",
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_res_1):
            client.post(f"/api/v1/verifications/{verification_id}/reason", headers={"Authorization": auth})

        history_res = client.get(f"/api/v1/verifications/{verification_id}/reasoning", headers={"Authorization": auth})
        assert history_res.status_code == status.HTTP_200_OK
        history = history_res.json()
        assert len(history) == 1
        assert history[0]["status"] == "COMPLETED"

    def test_reasoning_idempotency_cached_result(self, client: TestClient, db_session: Session):
        """25. Identical evidence context returns cached result without calling Ollama service."""
        _, auth = register_and_auth(client, "reason24@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R24")
        verification_id = sess_data["id"]

        mock_result = {
            "action": "CONTINUE_WORKFLOW",
            "reasoning_summary": "Initial evaluation.",
            "confidence": 0.88,
            "next_step_key": "damage_photo",
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", return_value=mock_result) as mock_gen:
            res1 = client.post(f"/api/v1/verifications/{verification_id}/reason", headers={"Authorization": auth})
            assert res1.status_code == status.HTTP_200_OK
            assert mock_gen.call_count == 1

            # Second call with identical context
            res2 = client.post(f"/api/v1/verifications/{verification_id}/reason", headers={"Authorization": auth})
            assert res2.status_code == status.HTTP_200_OK
            # Should NOT have called Ollama a second time
            assert mock_gen.call_count == 1
            assert res1.json()["id"] == res2.json()["id"]

    def test_reasoning_context_hash_deterministic(self):
        """26. Deterministic hashing ensures identical context dictionaries produce identical hashes."""
        dict1 = {"b": 2, "a": 1, "nested": {"y": "test", "x": [1, 2, 3]}}
        dict2 = {"nested": {"x": [1, 2, 3], "y": "test"}, "a": 1, "b": 2}

        hash1 = reasoning_context_service.calculate_context_hash(dict1)
        hash2 = reasoning_context_service.calculate_context_hash(dict2)

        assert hash1 == hash2
        assert len(hash1) == 64

    def test_reasoning_new_evidence_updates_context_hash(self, client: TestClient, db_session: Session):
        """27. Submitting new evidence updates context hash and triggers a fresh reasoning run."""
        _, auth = register_and_auth(client, "reason26@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R26")
        verification_id = sess_data["id"]

        mock_res_1 = {
            "action": "CONTINUE_WORKFLOW",
            "reasoning_summary": "Pass before evidence.",
            "confidence": 0.7,
            "next_step_key": "damage_photo",
        }
        mock_res_2 = {
            "action": "ACCEPT_EVIDENCE",
            "reasoning_summary": "Pass after text evidence.",
            "confidence": 0.9,
        }

        with patch("app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning", side_effect=[mock_res_1, mock_res_2]):
            # First run without evidence
            r1 = client.post(f"/api/v1/verifications/{verification_id}/reason", headers={"Authorization": auth})
            hash1 = r1.json()["input_context_hash"]

            # Submit text evidence
            client.post(
                f"/api/v1/public/verifications/{token}/evidence/text",
                json={
                    "workflow_step_key": "customer_explanation",
                    "text": "Detailed damage description here.",
                },
            )

            # Second run with new evidence
            r2 = client.post(f"/api/v1/verifications/{verification_id}/reason", headers={"Authorization": auth})
            hash2 = r2.json()["input_context_hash"]

            assert hash1 != hash2
            assert r1.json()["id"] != r2.json()["id"]


class TestSecurityIsolationAndAccessControl:
    """Test tenant isolation, customer blocking, and state transitions."""

    def test_reasoning_merchant_isolation_post(self, client: TestClient, db_session: Session):
        """28. Merchant B cannot trigger reasoning on Merchant A's verification session (404)."""
        _, auth_a = register_and_auth(client, "merch_a@store.com")
        _, auth_b = register_and_auth(client, "merch_b@store.com")
        sess_data, _ = setup_test_verification(client, auth_a, "SKU-R27")

        res = client.post(
            f"/api/v1/verifications/{sess_data['id']}/reason",
            headers={"Authorization": auth_b},
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_reasoning_merchant_isolation_get(self, client: TestClient, db_session: Session):
        """29. Merchant B cannot view reasoning runs of Merchant A's verification session (404)."""
        _, auth_a = register_and_auth(client, "merch_a2@store.com")
        _, auth_b = register_and_auth(client, "merch_b2@store.com")
        sess_data, _ = setup_test_verification(client, auth_a, "SKU-R28")

        res = client.get(
            f"/api/v1/verifications/{sess_data['id']}/reasoning",
            headers={"Authorization": auth_b},
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_reasoning_customer_token_blocked(self, client: TestClient, db_session: Session):
        """30. Customer token cannot call internal reasoning endpoints (401)."""
        _, auth = register_and_auth(client, "reason29@store.com")
        sess_data, token = setup_test_verification(client, auth, "SKU-R29")
        verification_id = sess_data["id"]

        # Call with customer token in Authorization header
        res_post = client.post(
            f"/api/v1/verifications/{verification_id}/reason",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_post.status_code == status.HTTP_401_UNAUTHORIZED

        res_get = client.get(
            f"/api/v1/verifications/{verification_id}/reasoning",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_get.status_code == status.HTTP_401_UNAUTHORIZED


class TestLlamaReasoningNormalization:
    """Regression test suite for Llama response normalization, extra context field filtering, and fail-safe validation."""

    def test_normal_valid_llama_response(self):
        """A. Normal valid Llama response parsed into ReasoningResult."""
        from app.ai.ollama_reasoning import normalize_and_validate_reasoning_result
        raw = {
            "action": "ACCEPT_EVIDENCE",
            "reasoning_summary": "Visual evidence matches reference product.",
            "confidence": 0.95,
        }
        result = normalize_and_validate_reasoning_result(raw)
        assert isinstance(result, ReasoningResult)
        assert result.action == ReasoningAction.ACCEPT_EVIDENCE
        assert result.confidence == 0.95

    def test_valid_response_with_extra_context_fields(self, caplog):
        """B. Valid response containing extra context fields (previous_questions, previous_answers, etc.) successfully produces ReasoningResult."""
        from app.ai.ollama_reasoning import normalize_and_validate_reasoning_result
        raw_with_extras = {
            "action": "ACCEPT_EVIDENCE",
            "reasoning_summary": "Photo is clear and displays expected product.",
            "confidence": 0.95,
            "next_step_key": "step_accept_evidence",
            "requested_evidence_type": "CUSTOMER_IMAGE",
            "reason": "Clear photo",
            "previous_questions": ["What was damaged?"],
            "previous_answers": ["Screen crack"],
            "deterministic_facts": ["Order #123 delivered"],
            "adaptive_followups": {"count": 1},
        }
        result = normalize_and_validate_reasoning_result(raw_with_extras)
        assert isinstance(result, ReasoningResult)
        assert result.action == ReasoningAction.ACCEPT_EVIDENCE
        assert result.confidence == 0.95
        # Verify extra fields were ignored and logged
        assert "Ignoring unexpected extra fields" in caplog.text
        assert "previous_questions" in caplog.text

    def test_missing_required_field_fails_safely(self):
        """C. Missing required field (e.g. missing confidence) fails safely with ValueError."""
        from app.ai.ollama_reasoning import normalize_and_validate_reasoning_result
        raw_missing = {
            "action": "CONTINUE_WORKFLOW",
            "reasoning_summary": "Summary without confidence score.",
        }
        with pytest.raises(ValueError) as exc_info:
            normalize_and_validate_reasoning_result(raw_missing)
        assert "failed schema validation" in str(exc_info.value)

    def test_invalid_json_string_fails_safely(self):
        """D. Invalid JSON string in generate_reasoning fails safely with ValueError."""
        service = OllamaReasoningService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "{ invalid json string ... }"}}

        with patch.object(OllamaReasoningService, "check_health", return_value=True), \
             patch.object(OllamaReasoningService, "check_model_available", return_value=True), \
             patch("httpx.Client.post", return_value=mock_resp):
            with pytest.raises(ValueError, match="invalid JSON"):
                service.generate_reasoning({"verification_id": "test_123"})

    def test_invalid_action_fails_safely(self):
        """E. Invalid action (e.g. REFUND_APPROVED or FRAUD_DETECTED) fails safely with ValueError."""
        from app.ai.ollama_reasoning import normalize_and_validate_reasoning_result
        raw_invalid_action = {
            "action": "REFUND_APPROVED",
            "reasoning_summary": "Approved refund for customer.",
            "confidence": 0.99,
        }
        with pytest.raises(ValueError) as exc_info:
            normalize_and_validate_reasoning_result(raw_invalid_action)
        assert "failed schema validation" in str(exc_info.value)

    def test_failsafe_behavior_when_reasoning_fails(self, client: TestClient, db_session: Session):
        """F. Existing fail-safe behavior when reasoning fails: verification session remains IN_PROGRESS and safe."""
        _, auth = register_and_auth(client, "failsafe_norm@store.com")
        sess_data, _ = setup_test_verification(client, auth, "SKU-FS-NORM")
        verification_id = sess_data["id"]

        with patch(
            "app.ai.ollama_reasoning.ollama_reasoning_service.generate_reasoning",
            side_effect=ValueError("Ollama response failed schema validation: extra fields not permitted"),
        ):
            res = client.post(
                f"/api/v1/verifications/{verification_id}/reason",
                headers={"Authorization": auth},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "FAILED"
        assert "validation" in data["error_message"].lower()

        # Session remains safe IN_PROGRESS
        sess_check = client.get(f"/api/v1/verifications/{verification_id}", headers={"Authorization": auth}).json()
        assert sess_check["status"] == "IN_PROGRESS"

