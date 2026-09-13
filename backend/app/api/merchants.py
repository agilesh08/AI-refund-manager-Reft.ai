"""Merchant profile endpoints."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.merchant import Merchant
from app.schemas.merchant import (
    MerchantResponse,
    MerchantProfileUpdateRequest,
)
from app.api.dependencies import get_current_merchant
from app.services import merchant_service

router = APIRouter()


@router.get(
    "/profile",
    response_model=MerchantResponse,
    status_code=status.HTTP_200_OK,
    summary="Get merchant profile",
)
def get_profile(
    current_merchant: Merchant = Depends(get_current_merchant),
) -> MerchantResponse:
    """Retrieve profile information for the authenticated merchant."""
    return MerchantResponse.model_validate(current_merchant)


@router.put(
    "/profile",
    response_model=MerchantResponse,
    status_code=status.HTTP_200_OK,
    summary="Update merchant profile",
)
def update_profile(
    data: MerchantProfileUpdateRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> MerchantResponse:
    """Update profile information (business name, phone) for the authenticated merchant."""
    updated = merchant_service.update_merchant_profile(
        db=db,
        merchant=current_merchant,
        data=data,
    )
    return MerchantResponse.model_validate(updated)
