"""Product reference image business logic."""
import logging
from typing import List
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product_reference import ProductReference, ReferenceAngle
from app.services.product_service import get_merchant_product
from app.utils.file_storage import (
    validate_and_read_image,
    calculate_sha256,
    generate_safe_filename,
    save_reference_file,
    delete_reference_file,
)

logger = logging.getLogger(__name__)


def _normalize_and_validate_angle(angle_str: str) -> str:
    """Normalize and validate the provided angle against canonical reference angles."""
    clean_angle = (angle_str or "").strip().upper()
    try:
        return ReferenceAngle(clean_angle).value
    except ValueError:
        valid_angles = [a.value for a in ReferenceAngle]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid angle '{angle_str}'. Allowed angles: {', '.join(valid_angles)}",
        )



async def upload_reference_image(
    db: Session,
    merchant_id: str,
    product_id: str,
    angle: str,
    image_file: UploadFile,
) -> ProductReference:
    """Upload, validate, hash, and persist a trusted reference angle for a merchant product."""
    # 1. Enforce merchant ownership of the parent product
    product = get_merchant_product(db, merchant_id, product_id)

    # 2. Validate and normalize the reference angle
    norm_angle = _normalize_and_validate_angle(angle)

    # 3. Check for existing reference for this angle (strict replacement policy)
    existing_ref = db.execute(
        select(ProductReference).where(
            ProductReference.product_id == product.id,
            ProductReference.angle == norm_angle,
        )
    ).scalar_one_or_none()

    if existing_ref:
        logger.warning(
            "Conflict: Reference for angle %s already exists on product %s",
            norm_angle,
            product.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {norm_angle} reference already exists. Delete it before uploading a replacement.",
        )

    # 4. Read, validate image format and decode via Pillow
    file_bytes, extension = await validate_and_read_image(image_file)

    # 5. Compute SHA-256 cryptographic hash
    image_hash = calculate_sha256(file_bytes)

    # 6. Generate collision-free filename and save to storage
    filename = generate_safe_filename(product.id, norm_angle, extension)
    relative_path = save_reference_file(file_bytes, filename)

    # 7. Create and persist database record
    reference = ProductReference(
        product_id=product.id,
        angle=norm_angle,
        image_path=relative_path,
        image_hash=image_hash,
    )
    db.add(reference)
    product.reference_processing_status = "PROCESSING"
    db.commit()
    db.refresh(reference)

    # Invalidate existing profile and enqueue background AI analysis job
    from app.services import product_profile_service
    from app.ai.ai_queue import ai_job_queue, AIJob, JobType

    product_profile_service.invalidate_product_visual_profile(db, product.id)
    ai_job_queue.enqueue(
        AIJob(
            job_type=JobType.REFERENCE_ANALYSIS,
            product_id=product.id,
            reference_id=reference.id,
        )
    )

    logger.info(
        "Persisted trusted %s reference for product %s (hash: %s...). Enqueued background AI job.",
        norm_angle,
        product.id,
        image_hash[:12],
    )
    return reference


def list_product_references(
    db: Session,
    merchant_id: str,
    product_id: str,
) -> List[ProductReference]:
    """List all trusted reference images uploaded for a product."""
    product = get_merchant_product(db, merchant_id, product_id)
    return list(
        db.execute(
            select(ProductReference)
            .where(ProductReference.product_id == product.id)
            .order_by(ProductReference.created_at.asc())
        ).scalars().all()
    )


def get_product_reference_by_angle(
    db: Session,
    merchant_id: str,
    product_id: str,
    angle: str,
) -> ProductReference:
    """Retrieve metadata for a specific angle reference."""
    product = get_merchant_product(db, merchant_id, product_id)
    norm_angle = _normalize_and_validate_angle(angle)

    reference = db.execute(
        select(ProductReference).where(
            ProductReference.product_id == product.id,
            ProductReference.angle == norm_angle,
        )
    ).scalar_one_or_none()

    if not reference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reference image not found for angle {norm_angle}",
        )

    return reference


def delete_product_reference_by_angle(
    db: Session,
    merchant_id: str,
    product_id: str,
    angle: str,
) -> None:
    """Delete a reference image database record and associated physical file."""
    product = get_merchant_product(db, merchant_id, product_id)
    norm_angle = _normalize_and_validate_angle(angle)

    reference = db.execute(
        select(ProductReference).where(
            ProductReference.product_id == product.id,
            ProductReference.angle == norm_angle,
        )
    ).scalar_one_or_none()

    if not reference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reference image not found for angle {norm_angle}",
        )

    # Delete disk file
    delete_reference_file(reference.image_path)

    # Delete database record
    db.delete(reference)

    # Update product status to NOT_READY (incomplete reference set)
    product.reference_processing_status = "NOT_READY"
    db.commit()

    # Invalidate product visual profile
    from app.services import product_profile_service
    product_profile_service.invalidate_product_visual_profile(db, product.id)

    logger.info("Deleted %s reference for product %s", norm_angle, product.id)
