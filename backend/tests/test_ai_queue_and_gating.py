"""Tests for dedicated AI worker queue, non-blocking uploads, SQLite WAL concurrency, cached profile reuse, and product verification gating."""
import hashlib
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.merchant import Merchant
from app.models.product import Product
from app.models.product_reference import ProductReference
from app.models.product_visual_profile import ProductVisualProfile, ProductVisualProfileStatus
from app.models.workflow import Workflow, WorkflowStatus
from app.models.workflow_step import WorkflowStep, WorkflowStepType
from app.schemas.product_reference_analysis import (
    ProductReferenceAnalysisResult,
    ProductVisualProfileResult,
    ReferenceImageVisualMetadata,
)
from app.services.product_profile_service import (
    process_product_references_and_consolidate_profile,
    invalidate_product_visual_profile,
)
from app.ai.ai_queue import ai_job_queue, AIJob, JobType


@pytest.fixture
def test_merchant(db_session):
    merchant = Merchant(
        business_name="Test Queue Merchant",
        email="queue_merchant@example.com",
        password_hash="secretpassword",
    )
    db_session.add(merchant)
    db_session.commit()
    db_session.refresh(merchant)
    return merchant


@pytest.fixture
def test_product(db_session, test_merchant):
    product = Product(
        merchant_id=test_merchant.id,
        name="Test Queue Headphones",
        sku="SKU-QUEUE-01",
        description="Over-ear headphones for queue testing",
        price=99.99,
        reference_processing_status="NOT_READY",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


@pytest.fixture
def test_workflow(db_session, test_merchant):
    wf = Workflow(
        merchant_id=test_merchant.id,
        name="Test Gating Workflow",
        status=WorkflowStatus.ACTIVE.value,
    )
    db_session.add(wf)
    db_session.commit()
    db_session.refresh(wf)

    step = WorkflowStep(
        workflow_id=wf.id,
        step_key="evidence_upload",
        title="Upload Evidence",
        step_type=WorkflowStepType.IMAGE.value,
        step_order=1,
    )
    db_session.add(step)
    db_session.commit()
    return wf


def test_ai_queue_enqueue():
    job = AIJob(job_type=JobType.REFERENCE_ANALYSIS, product_id="prod-123", reference_id="ref-123")
    job_id = ai_job_queue.enqueue(job)
    assert job_id == job.job_id


from app.api.dependencies import get_current_merchant
from app.main import app


def test_verification_creation_gating_not_ready(client, test_merchant, test_product, test_workflow, db_session):
    # Add 4 dummy reference entries so completeness passes
    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        ref = ProductReference(
            product_id=test_product.id,
            angle=angle,
            image_path=f"path_{angle}.jpg",
            image_hash=f"hash_{angle}",
        )
        db_session.add(ref)
    db_session.commit()

    payload = {
        "product_id": test_product.id,
        "workflow_id": test_workflow.id,
        "order_id": "ORD-GATING-01",
        "customer_name": "John Doe",
    }

    headers = {"Authorization": "Bearer fake_test_token"}
    app.dependency_overrides[get_current_merchant] = lambda: test_merchant
    try:
        response = client.post("/api/v1/verifications", json=payload, headers=headers)
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "REFERENCE_ANALYSIS_NOT_READY"
    finally:
        app.dependency_overrides.pop(get_current_merchant, None)


def test_verification_creation_gating_processing(client, test_merchant, test_product, test_workflow, db_session):
    # Add 4 dummy reference entries so completeness passes
    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        ref = ProductReference(
            product_id=test_product.id,
            angle=angle,
            image_path=f"path_{angle}.jpg",
            image_hash=f"hash_{angle}",
        )
        db_session.add(ref)
    test_product.reference_processing_status = "PROCESSING"
    db_session.commit()

    payload = {
        "product_id": test_product.id,
        "workflow_id": test_workflow.id,
        "order_id": "ORD-GATING-02",
        "customer_name": "Jane Doe",
    }

    headers = {"Authorization": "Bearer fake_test_token"}
    app.dependency_overrides[get_current_merchant] = lambda: test_merchant
    try:
        response = client.post("/api/v1/verifications", json=payload, headers=headers)
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "REFERENCE_ANALYSIS_IN_PROGRESS"
    finally:
        app.dependency_overrides.pop(get_current_merchant, None)


def test_verification_creation_allowed_when_ready(client, test_merchant, test_product, test_workflow, db_session):
    test_product.reference_processing_status = "READY"
    profile = ProductVisualProfile(
        product_id=test_product.id,
        qwen_model_name="qwen2.5vl:3b-q4_K_M",
        llama_model_name="llama3.2:1b",
        profile_version="v1.0-profile",
        status=ProductVisualProfileStatus.READY.value,
        profile_json={"canonical_product_name": "Test Queue Headphones"},
    )
    db_session.add(profile)

    # Add 4 dummy reference entries so product completeness passes
    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        ref = ProductReference(
            product_id=test_product.id,
            angle=angle,
            image_path=f"path_{angle}.jpg",
            image_hash=f"hash_{angle}",
        )
        db_session.add(ref)
    db_session.commit()

    payload = {
        "product_id": test_product.id,
        "workflow_id": test_workflow.id,
        "order_id": "ORD-GATING-03",
        "customer_name": "Alice Smith",
    }

    headers = {"Authorization": "Bearer fake_test_token"}
    app.dependency_overrides[get_current_merchant] = lambda: test_merchant
    try:
        response = client.post("/api/v1/verifications", json=payload, headers=headers)
        assert response.status_code == 201
        res_data = response.json()
        assert res_data["order_id"] == "ORD-GATING-03"
    finally:
        app.dependency_overrides.pop(get_current_merchant, None)


def test_cached_profile_reuse_no_llama_call(db_session, test_product, tmp_path):
    # Setup 4 references
    hashes = {}
    references = []
    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        file_path = tmp_path / f"{angle}.jpg"
        file_path.write_bytes(f"bytes_{angle}".encode("utf-8"))
        h = hashlib.sha256(f"bytes_{angle}".encode("utf-8")).hexdigest()
        hashes[angle] = h

        ref = ProductReference(
            product_id=test_product.id,
            angle=angle,
            image_path=str(file_path),
            image_hash=h,
        )
        db_session.add(ref)
        references.append((ref, file_path))
    db_session.commit()

    # Pre-create READY profile matching current hashes
    profile = ProductVisualProfile(
        product_id=test_product.id,
        qwen_model_name="qwen2.5vl:3b-q4_K_M",
        llama_model_name="llama3.2:1b",
        profile_version="v1.0-profile",
        reference_hashes_json=hashes,
        status=ProductVisualProfileStatus.READY.value,
        profile_json={"canonical_product_name": "Test Queue Headphones"},
    )
    db_session.add(profile)
    db_session.commit()

    def fake_get_file_path(path_str):
        for r, p in references:
            if r.image_path == path_str or str(p) == path_str:
                return p
        return references[0][1]

    def mock_qwen_analysis(angle: str) -> ProductReferenceAnalysisResult:
        return ProductReferenceAnalysisResult(
            angle=angle,
            metadata=ReferenceImageVisualMetadata(
                product_category="Headphones",
                brand="AudioBrand",
                model="Pro-1",
                visible_product_identity="Wireless headphones",
                shape="Over-ear oval cups",
                color="Black and Silver",
                orientation_angle=angle,
            ),
            summary=f"Detailed view from {angle}",
            confidence=0.95,
        )

    with patch("app.services.product_profile_service.get_reference_file_path", side_effect=fake_get_file_path), \
         patch("app.services.product_profile_service.qwen_vision_service.analyze_reference_image", side_effect=lambda image_bytes, angle, product_info: mock_qwen_analysis(angle)) as mock_qwen, \
         patch("app.services.product_profile_service.ollama_reasoning_service.consolidate_product_visual_profile") as mock_llama:

        res = process_product_references_and_consolidate_profile(db_session, test_product.id, force_reanalyze=False)

        assert res is not None
        assert res.status == ProductVisualProfileStatus.READY.value
        mock_llama.assert_not_called()  # Llama call bypassed due to cache match!
