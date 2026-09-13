"""Merchant profile management services."""
import logging
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.schemas.merchant import MerchantProfileUpdateRequest

logger = logging.getLogger(__name__)


def update_merchant_profile(
    db: Session,
    merchant: Merchant,
    data: MerchantProfileUpdateRequest,
) -> Merchant:
    """Update editable merchant profile fields (business name, phone).
    
    Immutable fields (id, email, password_hash, created_at) cannot be changed through this operation.
    """
    if data.business_name is not None:
        merchant.business_name = data.business_name

    if data.phone is not None:
        merchant.phone = data.phone

    db.commit()
    db.refresh(merchant)
    logger.info("Updated profile for merchant id: %s", merchant.id)
    return merchant
