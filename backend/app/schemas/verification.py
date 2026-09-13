from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.verification import SessionStatus
from app.models.verification_event import VerificationEventType


# ---------------------------------------------------------------------------
# Merchant Request & Response Schemas
# ---------------------------------------------------------------------------

class VerificationCreateRequest(BaseModel):
    """Schema for merchant to initiate a new verification session."""
    product_id: str = Field(..., min_length=1, description="ID of registered product with complete reference images")
    workflow_id: str = Field(..., min_length=1, description="ID of an ACTIVE verification workflow")
    order_id: str = Field(..., min_length=1, max_length=100, description="Merchant order reference number")
    customer_name: Optional[str] = Field(None, max_length=255, description="Customer full name")
    customer_contact: Optional[str] = Field(None, max_length=255, description="Customer phone number or email")
    refund_reason: Optional[str] = Field(None, max_length=2000, description="Optional stated reason for refund request")
    refund_amount: Optional[Decimal] = Field(None, gt=Decimal("0.00"), decimal_places=2, max_digits=10, description="Requested refund amount")
    max_attempts: Optional[int] = Field(1, ge=1, le=10, description="Maximum allowed customer attempts")

    @field_validator("order_id")
    @classmethod
    def strip_order_id(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Order ID cannot be empty or whitespace only")
        return clean


class VerificationResponse(BaseModel):
    """Full representation of a verification session for merchant dashboards."""
    id: str
    verification_id: str
    merchant_id: str
    product_id: str
    workflow_id: str
    workflow_version: int
    order_id: str
    customer_name: Optional[str] = None
    customer_contact: Optional[str] = None
    refund_reason: Optional[str] = None
    refund_amount: Optional[Decimal] = None
    status: str
    customer_link: Optional[str] = Field(None, description="One-time secure verification link generated on creation")
    max_attempts: int = 1
    attempts_count: int = 0
    expires_at: datetime
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    held_at: Optional[datetime] = None
    hold_until: Optional[datetime] = None
    held_by: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class VerificationHoldRequest(BaseModel):
    """Request schema for holding a verification session."""
    duration_seconds: Optional[int] = Field(
        None,
        ge=1,
        description="Duration in seconds to hold the session. Omit or null for indefinite hold.",
    )


class VerificationHoldResponse(BaseModel):
    """Response returned when a session is held or resumed by the merchant."""
    verification_id: str
    status: str
    held_at: Optional[datetime] = None
    hold_until: Optional[datetime] = None
    message: str


class VerificationCancelResponse(BaseModel):
    """Response returned when a session is cancelled by the merchant."""
    verification_id: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# Customer Public Schemas (Strictly Sanitized)
# ---------------------------------------------------------------------------

class CustomerMerchantInfo(BaseModel):
    """Sanitized merchant information visible to customers."""
    business_name: str


class CustomerProductInfo(BaseModel):
    """Sanitized product information visible to customers."""
    name: str


class CustomerWorkflowInfo(BaseModel):
    """Sanitized workflow information visible to customers."""
    name: str


class CustomerVerificationResponse(BaseModel):
    """Public customer-facing verification overview.
    
    Guaranteed never to expose customer_token_hash, merchant email/phone, or internal IDs.
    """
    verification_id: str
    merchant: CustomerMerchantInfo
    product: CustomerProductInfo
    status: str
    max_attempts: int = 1
    attempts_count: int = 0
    expires_at: datetime
    workflow: CustomerWorkflowInfo


class CustomerWorkflowResponse(BaseModel):
    """Frozen workflow definition provided to customers based on session creation snapshot."""
    verification_id: str
    workflow_name: str
    workflow_version: int
    steps: List[Dict[str, Any]]


class VerificationStartResponse(BaseModel):
    """Response when a customer begins their guided verification."""
    verification_id: str
    status: str
    started_at: datetime
    message: str
