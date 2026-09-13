from typing import Optional
import email_validator
from pydantic import BaseModel, EmailStr, Field, field_validator

# Permit .local domain for local development and demonstration testing
if hasattr(email_validator, "SPECIAL_USE_DOMAIN_NAMES") and "local" in email_validator.SPECIAL_USE_DOMAIN_NAMES:
    email_validator.SPECIAL_USE_DOMAIN_NAMES = [d for d in email_validator.SPECIAL_USE_DOMAIN_NAMES if d != "local"]


class MerchantRegisterRequest(BaseModel):
    """Schema for merchant self-registration."""
    business_name: str = Field(..., min_length=1, max_length=255, description="Registered merchant business name")
    email: EmailStr = Field(..., description="Unique merchant email address")
    phone: Optional[str] = Field(None, max_length=50, description="Optional merchant contact phone")
    password: str = Field(..., min_length=8, max_length=128, description="Account password (min 8 chars)")

    @field_validator("business_name")
    @classmethod
    def validate_business_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Business name cannot be empty or whitespace only")
        return clean

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return str(v).lower().strip()


class MerchantLoginRequest(BaseModel):
    """Schema for merchant credential login."""
    email: EmailStr = Field(..., description="Registered merchant email")
    password: str = Field(..., description="Merchant password")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return str(v).lower().strip()


class TokenResponse(BaseModel):
    """Schema for successful authentication response containing JWT."""
    access_token: str
    token_type: str = "bearer"


class PasswordChangeRequest(BaseModel):
    """Schema for authenticated password change."""
    current_password: str = Field(..., description="Current account password")
    new_password: str = Field(..., min_length=8, max_length=128, description="New account password (min 8 chars)")
