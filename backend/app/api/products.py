"""Merchant product and trusted reference image endpoints."""
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, Form, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.merchant import Merchant
from app.api.dependencies import get_current_merchant
from app.schemas.product import (
    ProductCreateRequest,
    ProductUpdateRequest,
    ProductResponse,
    ProductReferenceResponse,
    ProductReferenceStatusResponse,
)
from app.services import product_service, reference_service
from app.utils.file_storage import get_reference_file_path

router = APIRouter()


# ---------------------------------------------------------------------------
# Product Management Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new product",
)
def create_product(
    data: ProductCreateRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Create a new product owned by the authenticated merchant."""
    product = product_service.create_product(
        db=db,
        merchant_id=current_merchant.id,
        data=data,
    )
    return ProductResponse.model_validate(product)


@router.get(
    "",
    response_model=List[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="List merchant's products",
)
def list_products(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> List[ProductResponse]:
    """Retrieve all products belonging to the authenticated merchant."""
    products = product_service.list_merchant_products(
        db=db,
        merchant_id=current_merchant.id,
    )
    return [ProductResponse.model_validate(p) for p in products]


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single product",
)
def get_product(
    product_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Retrieve a single product by ID ensuring merchant ownership."""
    product = product_service.get_merchant_product(
        db=db,
        merchant_id=current_merchant.id,
        product_id=product_id,
    )
    return ProductResponse.model_validate(product)


@router.put(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Update product details",
)
def update_product(
    product_id: str,
    data: ProductUpdateRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Update name, SKU, description, or price of an owned product."""
    product = product_service.update_merchant_product(
        db=db,
        merchant_id=current_merchant.id,
        product_id=product_id,
        data=data,
    )
    return ProductResponse.model_validate(product)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete product and all reference images",
)
def delete_product(
    product_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """Delete a product, cascading to delete all associated reference images on disk and DB."""
    product_service.delete_merchant_product(
        db=db,
        merchant_id=current_merchant.id,
        product_id=product_id,
    )
    return {"message": "Product and associated references deleted successfully"}


@router.get(
    "/{product_id}/completeness",
    response_model=ProductReferenceStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Check reference angles completeness",
)
def get_product_completeness(
    product_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> ProductReferenceStatusResponse:
    """Verify whether all 4 canonical reference angles (FRONT, BACK, LEFT, RIGHT) exist."""
    return product_service.get_product_completeness(
        db=db,
        merchant_id=current_merchant.id,
        product_id=product_id,
    )


# ---------------------------------------------------------------------------
# Trusted Reference Images Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{product_id}/references",
    response_model=ProductReferenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload trusted reference image for an angle",
)
async def upload_reference(
    product_id: str,
    angle: str = Form(..., description="Canonical angle: FRONT, BACK, LEFT, RIGHT"),
    image: UploadFile = File(..., description="Authentic reference image file (JPEG, PNG, WEBP)"),
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> ProductReferenceResponse:
    """Upload authentic reference image, compute SHA-256 hash, and store securely."""
    reference = await reference_service.upload_reference_image(
        db=db,
        merchant_id=current_merchant.id,
        product_id=product_id,
        angle=angle,
        image_file=image,
    )
    return ProductReferenceResponse.model_validate(reference)


@router.get(
    "/{product_id}/references",
    response_model=List[ProductReferenceResponse],
    status_code=status.HTTP_200_OK,
    summary="List product reference images",
)
def list_references(
    product_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> List[ProductReferenceResponse]:
    """Retrieve metadata for all uploaded reference images of a product."""
    references = reference_service.list_product_references(
        db=db,
        merchant_id=current_merchant.id,
        product_id=product_id,
    )
    return [ProductReferenceResponse.model_validate(r) for r in references]


@router.get(
    "/{product_id}/references/{angle}",
    response_model=ProductReferenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get reference image by angle",
)
def get_reference_by_angle(
    product_id: str,
    angle: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> ProductReferenceResponse:
    """Retrieve metadata for a specific angle reference image."""
    reference = reference_service.get_product_reference_by_angle(
        db=db,
        merchant_id=current_merchant.id,
        product_id=product_id,
        angle=angle,
    )
    return ProductReferenceResponse.model_validate(reference)


@router.delete(
    "/{product_id}/references/{angle}",
    status_code=status.HTTP_200_OK,
    summary="Delete reference image by angle",
)
def delete_reference_by_angle(
    product_id: str,
    angle: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """Delete a reference image for a specific angle and remove the physical file."""
    reference_service.delete_product_reference_by_angle(
        db=db,
        merchant_id=current_merchant.id,
        product_id=product_id,
        angle=angle,
    )
    return {"message": f"Reference image for angle {angle.upper()} deleted successfully"}


@router.get(
    "/{product_id}/references/{angle}/file",
    summary="Download or stream trusted reference image for preview",
)
def get_reference_file_by_angle(
    product_id: str,
    angle: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """Stream authentic reference image binary for merchant UI preview."""
    reference = reference_service.get_product_reference_by_angle(
        db=db,
        merchant_id=current_merchant.id,
        product_id=product_id,
        angle=angle,
    )
    file_path = get_reference_file_path(reference.image_path)
    ext = Path(reference.image_path).suffix.lower()
    media_type = "image/png" if ext == ".png" else "image/jpeg"
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=Path(reference.image_path).name,
    )
