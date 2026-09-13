"""Pydantic request and response schemas for customer evidence."""
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings


class EvidenceTextCreateRequest(BaseModel):
    """Schema for submitting customer text evidence."""
    workflow_step_key: Optional[str] = Field(None, max_length=100, description="Workflow step identifier")
    text: str = Field(..., min_length=1, max_length=settings.MAX_TEXT_EVIDENCE_LENGTH, description="Customer text explanation or answer")

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Text evidence cannot be empty or whitespace only")
        if len(clean) > settings.MAX_TEXT_EVIDENCE_LENGTH:
            raise ValueError(f"Text evidence exceeds maximum length of {settings.MAX_TEXT_EVIDENCE_LENGTH} characters")
        return clean

    @field_validator("workflow_step_key")
    @classmethod
    def strip_step_key(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            return clean if clean else None
        return None


class EvidenceResponse(BaseModel):
    """Sanitized evidence record exposed to customers and merchants.
    
    Guaranteed never to expose storage_path, customer_token_hash, or server filesystem internals.
    """
    evidence_id: str
    evidence_type: str
    workflow_step_key: Optional[str] = None
    status: str
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    sha256_hash: Optional[str] = None
    text_content: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvidenceProcessPlaceholderResponse(BaseModel):
    """Structured response contract for future AI processing queue."""
    evidence_id: str
    status: str
    message: str
    placeholder: bool = True
