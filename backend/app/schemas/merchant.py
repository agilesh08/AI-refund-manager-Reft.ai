from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MerchantResponse(BaseModel):
    """Schema for public/authenticated merchant profile representations.
    
    Guaranteed never to expose password hashes or sensitive internal credentials.
    """
    id: str
    business_name: str
    email: str
    phone: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MerchantProfileUpdateRequest(BaseModel):
    """Schema for updating merchant profile information."""
    business_name: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated business name")
    phone: Optional[str] = Field(None, max_length=50, description="Updated contact phone")

    @field_validator("business_name")
    @classmethod
    def validate_business_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                raise ValueError("Business name cannot be blank")
            return clean
        return v
