from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreateRequest(BaseModel):
    """Schema for registering a new merchant product."""
    name: str = Field(..., min_length=1, max_length=255, description="Product name/title")
    sku: str = Field(..., min_length=1, max_length=100, description="Merchant-unique product SKU")
    description: Optional[str] = Field(None, max_length=2000, description="Optional product description")
    price: Decimal = Field(..., gt=Decimal("0.00"), decimal_places=2, max_digits=10, description="Product price in currency units")

    @field_validator("name", "sku")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Field cannot be empty or whitespace only")
        return clean


class ProductUpdateRequest(BaseModel):
    """Schema for updating product details."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated product name")
    sku: Optional[str] = Field(None, min_length=1, max_length=100, description="Updated SKU")
    description: Optional[str] = Field(None, max_length=2000, description="Updated description")
    price: Optional[Decimal] = Field(None, gt=Decimal("0.00"), decimal_places=2, max_digits=10, description="Updated price")

    @field_validator("name", "sku")
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                raise ValueError("Field cannot be blank")
            return clean
        return v


class ProductResponse(BaseModel):
    """Safe merchant product representation."""
    id: str
    merchant_id: str
    name: str
    sku: str
    description: Optional[str] = None
    price: Decimal
    reference_processing_status: str = "NOT_READY"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductReferenceResponse(BaseModel):
    """Safe metadata representation for a trusted product reference image.
    
    Excludes internal server filesystem paths.
    """
    id: str
    product_id: str
    angle: str
    image_hash: str
    captured_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductReferenceStatusResponse(BaseModel):
    """Status report on the four canonical reference angles for a product."""
    product_id: str
    reference_status: Dict[str, bool]
    complete: bool
    is_complete: bool = False
    existing_count: int = 0
    required_count: int = 4
