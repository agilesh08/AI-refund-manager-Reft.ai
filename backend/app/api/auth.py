"""Merchant authentication endpoints."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.merchant import Merchant
from app.schemas.auth import (
    MerchantRegisterRequest,
    MerchantLoginRequest,
    TokenResponse,
    PasswordChangeRequest,
)
from app.schemas.merchant import MerchantResponse
from app.api.dependencies import get_current_merchant
from app.services import auth_service

router = APIRouter()


@router.post(
    "/register",
    response_model=MerchantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new merchant account",
)
def register(
    data: MerchantRegisterRequest,
    db: Session = Depends(get_db),
) -> MerchantResponse:
    """Create a new merchant account with securely hashed credentials."""
    merchant = auth_service.register_merchant(db=db, data=data)
    return MerchantResponse.model_validate(merchant)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Merchant credential login",
)
def login(
    data: MerchantLoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate merchant credentials and receive an access token."""
    return auth_service.authenticate_merchant(db=db, data=data)


@router.get(
    "/me",
    response_model=MerchantResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current merchant profile",
)
def get_me(
    current_merchant: Merchant = Depends(get_current_merchant),
) -> MerchantResponse:
    """Return the profile of the currently authenticated merchant."""
    return MerchantResponse.model_validate(current_merchant)


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change merchant account password",
)
def change_password(
    data: PasswordChangeRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """Change the authenticated merchant's password after validating current password."""
    auth_service.change_merchant_password(db=db, merchant=current_merchant, data=data)
    return {"message": "Password changed successfully"}
