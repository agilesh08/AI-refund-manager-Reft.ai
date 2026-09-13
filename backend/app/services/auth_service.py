"""Authentication and credential management services."""
import logging
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.schemas.auth import (
    MerchantRegisterRequest,
    MerchantLoginRequest,
    TokenResponse,
    PasswordChangeRequest,
)
from app.core.security import hash_password, verify_password, create_access_token

logger = logging.getLogger(__name__)


def register_merchant(db: Session, data: MerchantRegisterRequest) -> Merchant:
    """Register a new merchant account with hashed credentials.
    
    Raises HTTP 409 Conflict if email is already taken.
    """
    # Check for existing account with the same email
    existing = db.execute(
        select(Merchant).where(Merchant.email == data.email)
    ).scalar_one_or_none()

    if existing:
        logger.warning("Registration attempt with duplicate email: %s", data.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A merchant with this email address already exists",
        )

    # Hash plaintext password using Argon2
    hashed = hash_password(data.password)

    merchant = Merchant(
        business_name=data.business_name,
        email=data.email,
        phone=data.phone,
        password_hash=hashed,
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    logger.info("New merchant registered: %s (id: %s)", merchant.email, merchant.id)
    return merchant


def authenticate_merchant(db: Session, data: MerchantLoginRequest) -> TokenResponse:
    """Authenticate merchant credentials and issue a signed JWT.
    
    Does not distinguish between non-existent user and wrong password to prevent user enumeration.
    """
    merchant = db.execute(
        select(Merchant).where(Merchant.email == data.email)
    ).scalar_one_or_none()

    # Verify password against hash
    if not merchant or not verify_password(data.password, merchant.password_hash):
        logger.warning("Failed login attempt for email: %s", data.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check active status
    if not merchant.is_active:
        logger.warning("Login attempted for inactive merchant id: %s", merchant.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Merchant account is inactive",
        )

    token = create_access_token(subject=str(merchant.id))
    logger.info("Merchant logged in successfully: %s", merchant.id)
    return TokenResponse(access_token=token, token_type="bearer")


def change_merchant_password(db: Session, merchant: Merchant, data: PasswordChangeRequest) -> None:
    """Change the authenticated merchant's password after verifying current password."""
    if not verify_password(data.current_password, merchant.password_hash):
        logger.warning("Password change rejected - incorrect current password for merchant id: %s", merchant.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    merchant.password_hash = hash_password(data.new_password)
    db.commit()
    logger.info("Password changed successfully for merchant id: %s", merchant.id)
