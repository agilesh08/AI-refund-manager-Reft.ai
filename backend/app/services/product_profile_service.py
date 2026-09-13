"""Product profile service for background reference image analysis and Llama profile consolidation."""
import logging
from typing import Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.product_reference import ProductReference, ReferenceAngle
from app.models.product_reference_analysis import (
    ProductReferenceVisualAnalysis,
    ProductReferenceAnalysisStatus,
)
from app.models.product_visual_profile import (
    ProductVisualProfile,
    ProductVisualProfileStatus,
)
from app.ai.qwen_vision import qwen_vision_service
from app.ai.ollama_reasoning import ollama_reasoning_service
from app.utils.file_storage import get_reference_file_path

logger = logging.getLogger(__name__)

REQUIRED_ANGLES = {"FRONT", "BACK", "LEFT", "RIGHT"}


def analyze_single_product_reference(
    db: Session,
    reference_id: str,
    force_reanalyze: bool = False,
) -> ProductReferenceVisualAnalysis:
    """Process a single merchant product reference image through Qwen2.5-VL 3B.

    Uses SHA-256 caching: if image_hash, model_name, and prompt_version match an existing
    COMPLETED analysis, reuses it without calling Qwen again.
    """
    ref = db.execute(
        select(ProductReference).where(ProductReference.id == reference_id)
    ).scalar_one_or_none()

    if not ref:
        raise ValueError(f"ProductReference {reference_id} not found")

    product = ref.product
    product_info = {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "description": product.description or "",
        "category": getattr(product, "category", "General Merchandise"),
    }

    # Check for existing analysis record
    existing_analysis = db.execute(
        select(ProductReferenceVisualAnalysis).where(
            ProductReferenceVisualAnalysis.product_reference_id == ref.id
        )
    ).scalar_one_or_none()

    # Cache check: reuse if content hash matches and status is COMPLETED
    if (
        existing_analysis
        and not force_reanalyze
        and existing_analysis.status == ProductReferenceAnalysisStatus.COMPLETED.value
        and existing_analysis.image_hash == ref.image_hash
        and existing_analysis.model_name == qwen_vision_service.model_name
        and existing_analysis.prompt_version == qwen_vision_service.prompt_version
    ):
        logger.info(
            "Reusing cached reference visual analysis %s for angle %s of product %s",
            existing_analysis.id,
            ref.angle,
            product.id,
        )
        return existing_analysis

    # Create or update analysis record in PROCESSING state
    if not existing_analysis:
        analysis = ProductReferenceVisualAnalysis(
            product_id=product.id,
            product_reference_id=ref.id,
            angle=ref.angle,
            image_hash=ref.image_hash,
            model_name=qwen_vision_service.model_name,
            prompt_version=qwen_vision_service.prompt_version,
            status=ProductReferenceAnalysisStatus.PROCESSING.value,
        )
        db.add(analysis)
    else:
        analysis = existing_analysis
        analysis.image_hash = ref.image_hash
        analysis.model_name = qwen_vision_service.model_name
        analysis.prompt_version = qwen_vision_service.prompt_version
        analysis.status = ProductReferenceAnalysisStatus.PROCESSING.value
        analysis.error_message = None

    db.commit()
    db.refresh(analysis)

    # Read reference image bytes
    try:
        ref_file_path = get_reference_file_path(ref.image_path)
        image_bytes = ref_file_path.read_bytes()

        # Invoke Qwen for this single reference image
        result = qwen_vision_service.analyze_reference_image(
            image_bytes=image_bytes,
            angle=ref.angle,
            product_info=product_info,
        )

        analysis.result_json = result.model_dump()
        analysis.status = ProductReferenceAnalysisStatus.COMPLETED.value
        analysis.error_message = None
        db.commit()
        db.refresh(analysis)
        logger.info(
            "Completed Qwen reference analysis %s for angle %s (product: %s)",
            analysis.id,
            ref.angle,
            product.id,
        )
        return analysis

    except Exception as exc:
        logger.error(
            "Failed Qwen reference analysis for angle %s of product %s: %s",
            ref.angle,
            product.id,
            exc,
        )
        analysis.status = ProductReferenceAnalysisStatus.FAILED.value
        analysis.error_message = str(exc)
        db.commit()
        db.refresh(analysis)
        return analysis


def process_product_references_and_consolidate_profile(
    db: Session,
    product_id: str,
    force_reanalyze: bool = False,
) -> Optional[ProductVisualProfile]:
    """Process all reference images for a product ONE BY ONE and consolidate into a ProductVisualProfile.

    Sequential processing prevents Ollama VRAM overload.
    """
    product = db.execute(
        select(Product).where(Product.id == product_id)
    ).scalar_one_or_none()

    if not product:
        logger.warning("Cannot process references: product %s not found", product_id)
        return None

    # Fetch all reference images uploaded for this product
    references = db.execute(
        select(ProductReference).where(ProductReference.product_id == product.id)
    ).scalars().all()

    ref_by_angle = {ref.angle: ref for ref in references}
    current_hashes = {ref.angle: ref.image_hash for ref in references}

    # Process each uploaded reference image sequentially
    completed_analyses: List[Dict[str, Any]] = []
    failed_angles: List[str] = []

    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        ref = ref_by_angle.get(angle)
        if not ref:
            continue

        try:
            analysis = analyze_single_product_reference(db, ref.id, force_reanalyze=force_reanalyze)
            if analysis.status == ProductReferenceAnalysisStatus.COMPLETED.value and analysis.result_json:
                completed_analyses.append(analysis.result_json)
            else:
                failed_angles.append(angle)
        except Exception as exc:
            logger.error("Error processing reference angle %s for product %s: %s", angle, product.id, exc)
            failed_angles.append(angle)

    # Fetch or create ProductVisualProfile record
    profile = db.execute(
        select(ProductVisualProfile).where(ProductVisualProfile.product_id == product.id)
    ).scalar_one_or_none()

    # Cache check: Reuse existing READY profile if 4 angles completed and reference hashes unchanged
    if (
        profile
        and not force_reanalyze
        and profile.status == ProductVisualProfileStatus.READY.value
        and profile.profile_json
        and profile.reference_hashes_json == current_hashes
        and len(completed_analyses) == 4
    ):
        logger.info(
            "Reusing existing ProductVisualProfile %s for product %s (reference hashes unchanged)",
            profile.id,
            product.id,
        )
        product.reference_processing_status = "READY"
        db.commit()
        return profile

    if not profile:
        profile = ProductVisualProfile(
            product_id=product.id,
            qwen_model_name=qwen_vision_service.model_name,
            llama_model_name=ollama_reasoning_service.model_name,
            profile_version="v1.0-profile",
            reference_hashes_json=current_hashes,
            status=ProductVisualProfileStatus.PROCESSING.value,
        )
        db.add(profile)
    else:
        profile.qwen_model_name = qwen_vision_service.model_name
        profile.llama_model_name = ollama_reasoning_service.model_name
        profile.reference_hashes_json = current_hashes

    # Check if all 4 angles are completed
    if len(completed_analyses) == 4 and not failed_angles:
        product_info = {
            "id": product.id,
            "name": product.name,
            "sku": product.sku,
            "description": product.description or "",
            "category": getattr(product, "category", "General Merchandise"),
        }

        try:
            # Consolidate via Llama 3.2 1B
            profile_result = ollama_reasoning_service.consolidate_product_visual_profile(
                product_info=product_info,
                reference_analyses=completed_analyses,
            )
            profile.profile_json = profile_result.model_dump()
            profile.status = ProductVisualProfileStatus.READY.value
            profile.error_message = None
            product.reference_processing_status = "READY"
            logger.info("Successfully consolidated ProductVisualProfile for product %s", product.id)
        except Exception as exc:
            logger.error("Llama profile consolidation failed for product %s: %s", product.id, exc)
            profile.status = ProductVisualProfileStatus.PARTIAL.value
            profile.error_message = f"Consolidation failed: {exc}"
            profile.profile_json = {"raw_reference_observations": completed_analyses}
            product.reference_processing_status = "PROCESSING"
    elif len(completed_analyses) > 0:
        profile.status = ProductVisualProfileStatus.PARTIAL.value
        profile.error_message = f"Incomplete references. Completed: {len(completed_analyses)}/4. Missing: {sorted(list(REQUIRED_ANGLES - set(ref_by_angle.keys())))}"
        profile.profile_json = {"raw_reference_observations": completed_analyses}
        product.reference_processing_status = "PROCESSING" if len(ref_by_angle) == 4 else "NOT_READY"
    else:
        profile.status = ProductVisualProfileStatus.FAILED.value
        profile.error_message = "All reference image analyses failed."
        product.reference_processing_status = "FAILED"

    db.commit()
    db.refresh(profile)
    db.refresh(product)
    return profile


def invalidate_product_visual_profile(db: Session, product_id: str) -> None:
    """Invalidate product visual profile when reference images are added, updated, or removed."""
    profile = db.execute(
        select(ProductVisualProfile).where(ProductVisualProfile.product_id == product_id)
    ).scalar_one_or_none()

    if profile:
        profile.status = ProductVisualProfileStatus.PENDING.value
        profile.error_message = "References modified. Pending re-analysis."

    product = db.execute(
        select(Product).where(Product.id == product_id)
    ).scalar_one_or_none()

    if product:
        product.reference_processing_status = "PROCESSING"

    db.commit()
    logger.info("Invalidated ProductVisualProfile for product %s", product_id)
