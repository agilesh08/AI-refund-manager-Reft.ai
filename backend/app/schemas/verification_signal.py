"""Pydantic schemas and strict normalizers for multi-source deterministic signals."""
import re
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.verification_signal import SignalType, SourceType, SignalStatus


ALLOWED_CURRENCY_SYMBOLS = {
    "₹": "INR",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
}

ALLOWED_PAYMENT_STATUSES = {
    "PAID",
    "PENDING",
    "FAILED",
    "REFUNDED",
    "PARTIALLY_REFUNDED",
}

ALLOWED_PAYMENT_METHODS = {
    "CARD",
    "UPI",
    "NET_BANKING",
    "WALLET",
    "COD",
    "BANK_TRANSFER",
}

ALLOWED_ORDER_STATUSES = {
    "CREATED",
    "CONFIRMED",
    "PROCESSING",
    "SHIPPED",
    "DELIVERED",
    "CANCELLED",
    "RETURNED",
}

ALLOWED_DELIVERY_STATUSES = {
    "NOT_SHIPPED",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "DELIVERY_FAILED",
    "RETURNED",
}

ALLOWED_LOCATION_SOURCES = {
    "DEVICE",
    "MERCHANT_PROVIDED",
    "SYSTEM_GENERATED",
}


class PaymentSignalData(BaseModel):
    """Strict schema and normalizer for PAYMENT signals."""
    payment_id: str = Field(..., min_length=1, description="Unique payment identifier")
    order_id: str = Field(..., min_length=1, description="Associated order identifier")
    amount: float = Field(..., ge=0.0, description="Payment amount (must be >= 0)")
    currency: str = Field(..., description="Normalized 3-letter uppercase currency code")
    payment_status: str = Field(..., description="Allowed payment status")
    payment_method: str = Field(..., description="Allowed payment method")
    paid_at: Optional[datetime] = Field(None, description="Timestamp of payment execution")
    transaction_reference: Optional[str] = Field(None, description="External transaction reference ID")
    payee_account: Optional[str] = Field(None, description="Payee UPI ID or merchant payment identifier")
    payer_account: Optional[str] = Field(None, description="Payer UPI ID or customer account identifier")

    model_config = ConfigDict(extra="forbid")

    @field_validator("payment_id", "order_id")
    @classmethod
    def strip_and_validate_id(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("ID cannot be empty or whitespace only")
        return clean

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        clean = v.strip()
        if clean in ALLOWED_CURRENCY_SYMBOLS:
            return ALLOWED_CURRENCY_SYMBOLS[clean]
        upper = clean.upper()
        if len(upper) != 3 or not upper.isalpha():
            raise ValueError(f"Invalid currency code '{v}'. Must be a 3-letter currency code or recognized symbol.")
        return upper

    @field_validator("payment_status")
    @classmethod
    def normalize_payment_status(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper in ("SUCCESS", "COMPLETED", "SETTLED"):
            return "PAID"
        if upper not in ALLOWED_PAYMENT_STATUSES:
            raise ValueError(f"Invalid payment_status '{v}'. Allowed: {sorted(ALLOWED_PAYMENT_STATUSES)}")
        return upper

    @field_validator("payment_method")
    @classmethod
    def normalize_payment_method(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in ALLOWED_PAYMENT_METHODS:
            raise ValueError(f"Invalid payment_method '{v}'. Allowed: {sorted(ALLOWED_PAYMENT_METHODS)}")
        return upper


class OrderSignalData(BaseModel):
    """Strict schema and normalizer for ORDER signals."""
    order_id: str = Field(..., min_length=1, description="Unique order identifier")
    product_id: Optional[str] = Field(None, description="Product identifier")
    sku: Optional[str] = Field(None, description="Product SKU")
    quantity: int = Field(..., ge=1, description="Purchased quantity (must be >= 1)")
    order_amount: float = Field(..., ge=0.0, description="Total order amount (must be >= 0)")
    ordered_at: Optional[datetime] = Field(None, description="Order placement timestamp")
    order_status: str = Field(..., description="Allowed order status")

    model_config = ConfigDict(extra="forbid")

    @field_validator("order_id")
    @classmethod
    def strip_order_id(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("order_id cannot be empty or whitespace only")
        return clean

    @field_validator("order_status")
    @classmethod
    def normalize_order_status(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in ALLOWED_ORDER_STATUSES:
            raise ValueError(f"Invalid order_status '{v}'. Allowed: {sorted(ALLOWED_ORDER_STATUSES)}")
        return upper


class DeliveryLocation(BaseModel):
    """Structured location metadata for delivery signal."""
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0, description="Destination delivery latitude")
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0, description="Destination delivery longitude")

    model_config = ConfigDict(extra="forbid")

    @field_validator("country")
    @classmethod
    def normalize_country(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return v.strip().upper()
        return None


class DeliverySignalData(BaseModel):
    """Strict schema and normalizer for DELIVERY signals."""
    order_id: str = Field(..., min_length=1, description="Associated order identifier")
    carrier: Optional[str] = Field(None, description="Courier/carrier name")
    tracking_reference: Optional[str] = Field(None, description="Tracking reference code")
    delivery_status: str = Field(..., description="Allowed delivery status")
    shipped_at: Optional[datetime] = Field(None, description="Timestamp shipment dispatched")
    delivered_at: Optional[datetime] = Field(None, description="Timestamp delivery confirmed")
    delivery_location: Optional[DeliveryLocation] = Field(None, description="Destination location metadata")

    model_config = ConfigDict(extra="forbid")

    @field_validator("order_id")
    @classmethod
    def strip_order_id(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("order_id cannot be empty or whitespace only")
        return clean

    @field_validator("delivery_status")
    @classmethod
    def normalize_delivery_status(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in ALLOWED_DELIVERY_STATUSES:
            raise ValueError(f"Invalid delivery_status '{v}'. Allowed: {sorted(ALLOWED_DELIVERY_STATUSES)}")
        return upper

    @model_validator(mode="after")
    def validate_date_ordering(self) -> "DeliverySignalData":
        if self.shipped_at and self.delivered_at:
            if self.delivered_at < self.shipped_at:
                raise ValueError("delivered_at cannot be earlier than shipped_at")
        return self


class LocationSignalData(BaseModel):
    """Strict schema and bounds validation for LOCATION signals."""
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude between -90.0 and +90.0")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude between -180.0 and +180.0")
    accuracy_meters: float = Field(..., gt=0.0, description="Accuracy radius in meters (must be > 0)")
    captured_at: Optional[datetime] = Field(None, description="Capture timestamp")
    source: str = Field(default="DEVICE", description="Allowed location source")

    model_config = ConfigDict(extra="forbid")

    @field_validator("source")
    @classmethod
    def normalize_source(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in ALLOWED_LOCATION_SOURCES:
            raise ValueError(f"Invalid location source '{v}'. Allowed: {sorted(ALLOWED_LOCATION_SOURCES)}")
        return upper


class SignalIngestRequest(BaseModel):
    """Merchant request schema to ingest a structured deterministic signal."""
    signal_type: SignalType = Field(..., description="PAYMENT, ORDER, DELIVERY, or LOCATION")
    source_type: SourceType = Field(..., description="Provenance origin category")
    source_reference: str = Field(..., min_length=1, max_length=255, description="Traceable source reference key")
    data: Dict[str, Any] = Field(..., description="Structured signal payload matching signal_type schema")
    observed_at: Optional[datetime] = Field(None, description="Optional observation timestamp (defaults to current time)")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")

    model_config = ConfigDict(extra="forbid")

    @field_validator("source_reference")
    @classmethod
    def strip_source_reference(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("source_reference cannot be empty")
        return clean


class SignalResponse(BaseModel):
    """Merchant-facing representation of a deterministic verification signal."""
    id: str
    verification_session_id: str
    signal_type: str
    source_type: str
    status: str
    data_json: Dict[str, Any]
    source_reference: str
    confidence: Optional[float] = None
    observed_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerSignalResponse(BaseModel):
    """Sanitized customer-facing view of a verification signal.
    
    Excludes internal session UUIDs, merchant financial references, and sensitive details.
    """
    id: str
    signal_type: str
    status: str
    observed_at: datetime
    safe_summary: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)
