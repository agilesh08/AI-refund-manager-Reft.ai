"""Tests for product visual profile service: single reference analysis, SHA-256 caching, profile consolidation, and profile invalidation."""
import hashlib
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import select

from app.models.merchant import Merchant
from app.models.product import Product
from app.models.product_reference import ProductReference
from app.models.product_reference_analysis import (
    ProductReferenceVisualAnalysis,
    ProductReferenceAnalysisStatus,
)
from app.models.product_visual_profile import (
    ProductVisualProfile,
    ProductVisualProfileStatus,
)
from app.schemas.product_reference_analysis import (
    ProductReferenceAnalysisResult,
    ProductVisualProfileResult,
)
from app.services.product_profile_service import (
    analyze_single_product_reference,
    process_product_references_and_consolidate_profile,
    invalidate_product_visual_profile,
)


@pytest.fixture
def test_merchant(db_session):
    merchant = Merchant(
        business_name="Test Profile Merchant",
        email="profile_merchant@example.com",
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
        name="Test Wireless Headphones",
        sku="SKU-HEADPHONES-01",
        description="Premium wireless over-ear headphones",
        price=199.99,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


@pytest.fixture
def test_references(db_session, test_product, tmp_path):
    """Creates 4 fake reference image files on disk and corresponding DB entries."""
    angles = ["FRONT", "BACK", "LEFT", "RIGHT"]
    references = []

    for angle in angles:
        file_name = f"{test_product.id}_{angle}.jpg"
        file_path = tmp_path / file_name
        file_bytes = f"dummy_image_data_for_{angle}".encode("utf-8")
        file_path.write_bytes(file_bytes)
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        ref = ProductReference(
            product_id=test_product.id,
            angle=angle,
            image_path=str(file_path),
            image_hash=file_hash,
        )
        db_session.add(ref)
        references.append((ref, file_path))

    db_session.commit()
    for ref, _ in references:
        db_session.refresh(ref)
    return references


from app.schemas.product_reference_analysis import (
    ProductReferenceAnalysisResult,
    ProductVisualProfileResult,
    ReferenceImageVisualMetadata,
)

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


def mock_llama_profile() -> ProductVisualProfileResult:
    return ProductVisualProfileResult(
        canonical_product_name="Test Wireless Headphones",
        brand="AudioBrand",
        model="Pro-1",
        category="Headphones",
        primary_colors=["Black", "Silver"],
        key_design_features=["Over-ear cushions", "Metallic headband", "Type-C charging port"],
    )


def test_analyze_single_product_reference_success(db_session, test_references):
    ref, file_path = test_references[0]

    with patch("app.services.product_profile_service.get_reference_file_path", return_value=file_path), \
         patch("app.services.product_profile_service.qwen_vision_service.analyze_reference_image") as mock_qwen:

        mock_qwen.return_value = mock_qwen_analysis("FRONT")

        analysis = analyze_single_product_reference(db_session, ref.id)

        assert analysis.status == ProductReferenceAnalysisStatus.COMPLETED.value
        assert analysis.angle == "FRONT"
        assert analysis.image_hash == ref.image_hash
        assert analysis.result_json is not None
        assert analysis.result_json["angle"] == "FRONT"
        mock_qwen.assert_called_once()


def test_single_product_reference_sha256_caching(db_session, test_references):
    ref, file_path = test_references[0]

    with patch("app.services.product_profile_service.get_reference_file_path", return_value=file_path), \
         patch("app.services.product_profile_service.qwen_vision_service.analyze_reference_image") as mock_qwen:

        mock_qwen.return_value = mock_qwen_analysis("FRONT")

        # First run: should call Qwen
        analysis1 = analyze_single_product_reference(db_session, ref.id, force_reanalyze=False)
        assert analysis1.status == ProductReferenceAnalysisStatus.COMPLETED.value
        assert mock_qwen.call_count == 1

        # Second run with force_reanalyze=False: should hit SHA-256 cache, no new Qwen call
        analysis2 = analyze_single_product_reference(db_session, ref.id, force_reanalyze=False)
        assert analysis2.id == analysis1.id
        assert mock_qwen.call_count == 1

        # Third run with force_reanalyze=True: should bypass cache and call Qwen again
        analysis3 = analyze_single_product_reference(db_session, ref.id, force_reanalyze=True)
        assert analysis3.status == ProductReferenceAnalysisStatus.COMPLETED.value
        assert mock_qwen.call_count == 2


def test_process_product_references_and_consolidate_profile_success(db_session, test_product, test_references):
    def fake_get_file_path(path_str):
        for r, p in test_references:
            if r.image_path == path_str or str(p) == path_str:
                return p
        return test_references[0][1]

    with patch("app.services.product_profile_service.get_reference_file_path", side_effect=fake_get_file_path), \
         patch("app.services.product_profile_service.qwen_vision_service.analyze_reference_image") as mock_qwen, \
         patch("app.services.product_profile_service.ollama_reasoning_service.consolidate_product_visual_profile") as mock_llama:

        mock_qwen.side_effect = lambda image_bytes, angle, product_info: mock_qwen_analysis(angle)
        mock_llama.return_value = mock_llama_profile()

        profile = process_product_references_and_consolidate_profile(db_session, test_product.id)

        assert profile is not None
        assert profile.status == ProductVisualProfileStatus.READY.value
        assert profile.profile_json is not None
        assert profile.profile_json["canonical_product_name"] == "Test Wireless Headphones"
        assert len(profile.profile_json["key_design_features"]) == 3
        assert mock_qwen.call_count == 4
        mock_llama.assert_called_once()


def test_process_product_references_partial_profile(db_session, test_product, test_references):
    # Remove 2 references so only FRONT and BACK exist
    ref_left = test_references[2][0]
    ref_right = test_references[3][0]
    db_session.delete(ref_left)
    db_session.delete(ref_right)
    db_session.commit()

    def fake_get_file_path(path_str):
        for r, p in test_references[:2]:
            if r.image_path == path_str or str(p) == path_str:
                return p
        return test_references[0][1]

    with patch("app.services.product_profile_service.get_reference_file_path", side_effect=fake_get_file_path), \
         patch("app.services.product_profile_service.qwen_vision_service.analyze_reference_image") as mock_qwen, \
         patch("app.services.product_profile_service.ollama_reasoning_service.consolidate_product_visual_profile") as mock_llama:

        mock_qwen.side_effect = lambda image_bytes, angle, product_info: mock_qwen_analysis(angle)

        profile = process_product_references_and_consolidate_profile(db_session, test_product.id)

        assert profile is not None
        assert profile.status == ProductVisualProfileStatus.PARTIAL.value
        assert "Incomplete references" in profile.error_message
        assert mock_qwen.call_count == 2
        mock_llama.assert_not_called()


def test_invalidate_product_visual_profile(db_session, test_product):
    profile = ProductVisualProfile(
        product_id=test_product.id,
        qwen_model_name="qwen2.5vl:3b-q4_K_M",
        llama_model_name="llama3.2:1b",
        profile_version="v1.0-profile",
        status=ProductVisualProfileStatus.READY.value,
        profile_json={"canonical_visual_features": ["test"]},
    )
    db_session.add(profile)
    db_session.commit()

    invalidate_product_visual_profile(db_session, test_product.id)

    db_session.refresh(profile)
    assert profile.status == ProductVisualProfileStatus.PENDING.value
    assert "Pending re-analysis" in profile.error_message
