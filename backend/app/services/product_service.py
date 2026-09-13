"""Product management business logic."""
import logging
from typing import List
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.product_reference import ReferenceAngle
from app.schemas.product import (
    ProductCreateRequest,
    ProductUpdateRequest,
    ProductReferenceStatusResponse,
)
from app.utils.file_storage import delete_reference_file

logger = logging.getLogger(__name__)


def create_product(db: Session, merchant_id: str, data: ProductCreateRequest) -> Product:
    """Create a new product for the authenticated merchant with SKU uniqueness check."""
    existing = db.execute(
        select(Product).where(
            Product.merchant_id == merchant_id,
            Product.sku == data.sku,
        )
    ).scalar_one_or_none()

    if existing:
        logger.warning("Duplicate SKU '%s' attempted for merchant id %s", data.sku, merchant_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Product with SKU '{data.sku}' already exists in your inventory",
        )

    product = Product(
        merchant_id=merchant_id,
        name=data.name,
        sku=data.sku,
        description=data.description,
        price=data.price,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    logger.info("Created product %s (SKU: %s) for merchant %s", product.id, product.sku, merchant_id)
    return product


def list_merchant_products(db: Session, merchant_id: str) -> List[Product]:
    """Retrieve all products owned by the authenticated merchant."""
    return list(
        db.execute(
            select(Product)
            .where(Product.merchant_id == merchant_id)
            .order_by(Product.created_at.desc())
        ).scalars().all()
    )


def get_merchant_product(db: Session, merchant_id: str, product_id: str) -> Product:
    """Retrieve a single product ensuring strict merchant ownership.
    
    Returns HTTP 404 if the product does not exist or belongs to another merchant.
    """
    product = db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.merchant_id == merchant_id,
        )
    ).scalar_one_or_none()

    if not product:
        # Never reveal existence of another merchant's product
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return product


def update_merchant_product(
    db: Session,
    merchant_id: str,
    product_id: str,
    data: ProductUpdateRequest,
) -> Product:
    """Update product details with ownership and SKU uniqueness enforcement."""
    product = get_merchant_product(db, merchant_id, product_id)

    # Check for SKU conflict if SKU is being modified
    if data.sku is not None and data.sku != product.sku:
        existing = db.execute(
            select(Product).where(
                Product.merchant_id == merchant_id,
                Product.sku == data.sku,
                Product.id != product_id,
            )
        ).scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Product with SKU '{data.sku}' already exists in your inventory",
            )
        product.sku = data.sku

    if data.name is not None:
        product.name = data.name

    if data.description is not None:
        product.description = data.description

    if data.price is not None:
        product.price = data.price

    db.commit()
    db.refresh(product)
    logger.info("Updated product %s for merchant %s", product.id, merchant_id)
    return product


def delete_merchant_product(db: Session, merchant_id: str, product_id: str) -> None:
    """Delete a merchant's product and cleanup all associated reference image files."""
    product = get_merchant_product(db, merchant_id, product_id)

    # Remove all physical reference image files from disk
    for ref in product.references:
        delete_reference_file(ref.image_path)

    db.delete(product)
    db.commit()
    logger.info("Deleted product %s and associated reference files for merchant %s", product_id, merchant_id)


def get_product_completeness(
    db: Session,
    merchant_id: str,
    product_id: str,
) -> ProductReferenceStatusResponse:
    """Calculate the availability of all 4 trusted reference angles (FRONT, BACK, LEFT, RIGHT)."""
    product = get_merchant_product(db, merchant_id, product_id)

    uploaded_angles = {ref.angle.upper() for ref in product.references}

    status_map = {
        "front": ReferenceAngle.FRONT.value in uploaded_angles,
        "back": ReferenceAngle.BACK.value in uploaded_angles,
        "left": ReferenceAngle.LEFT.value in uploaded_angles,
        "right": ReferenceAngle.RIGHT.value in uploaded_angles,
    }

    existing_count = sum(1 for v in status_map.values() if v)
    required_count = len(status_map)
    is_comp = existing_count == required_count

    return ProductReferenceStatusResponse(
        product_id=product.id,
        reference_status=status_map,
        complete=is_comp,
        is_complete=is_comp,
        existing_count=existing_count,
        required_count=required_count,
    )
