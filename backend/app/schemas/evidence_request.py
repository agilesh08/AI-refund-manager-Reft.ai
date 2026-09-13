"""Pydantic schemas for adaptive evidence follow-up requests."""
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.evidence import EvidenceResponse


class EvidenceRequestResponse(BaseModel):
    """Full merchant-facing schema for an adaptive evidence follow-up request."""
    id: str = Field(..., description="Unique ID of the evidence request")
    verification_session_id: str = Field(..., description="Internal verification session UUID")
    workflow_step_key: str = Field(..., description="Target workflow step key from frozen snapshot")
    step_key: Optional[str] = Field(None, description="Alias for workflow_step_key")
    requested_evidence_type: str = Field(..., description="Evidence type requested (e.g. CUSTOMER_IMAGE)")
    reason: str = Field(..., description="User-safe justification explaining why this evidence is requested")
    options: Optional[List[str]] = Field(None, description="Optional MCQ choices", alias="options_json")
    status: str = Field(..., description="Status: PENDING, FULFILLED, CANCELLED, EXPIRED")
    created_at: datetime = Field(..., description="Creation timestamp")
    fulfilled_at: Optional[datetime] = Field(None, description="Fulfillment timestamp if completed")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def populate_step_key(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "workflow_step_key" in data and not data.get("step_key"):
                data["step_key"] = data["workflow_step_key"]
            elif "step_key" in data and not data.get("workflow_step_key"):
                data["workflow_step_key"] = data["step_key"]
            if "options_json" in data and not data.get("options"):
                data["options"] = data["options_json"]
        elif hasattr(data, "workflow_step_key") and not getattr(data, "step_key", None):
            try:
                setattr(data, "step_key", data.workflow_step_key)
            except Exception:
                pass
        return data


class CustomerEvidenceRequestResponse(BaseModel):
    """Sanitized customer-facing schema for an adaptive evidence request.
    
    Excludes internal database foreign keys and session UUIDs.
    """
    id: str = Field(..., description="Unique ID of the evidence request")
    workflow_step_key: str = Field(..., description="Target workflow step key from frozen snapshot")
    step_key: Optional[str] = Field(None, description="Alias for workflow_step_key")
    requested_evidence_type: str = Field(..., description="Evidence type requested")
    reason: str = Field(..., description="User-safe guidance on what evidence to provide")
    options: Optional[List[str]] = Field(None, description="Optional MCQ choices", alias="options_json")
    status: str = Field(..., description="Status: PENDING, FULFILLED, CANCELLED, EXPIRED")
    created_at: datetime = Field(..., description="Creation timestamp")
    fulfilled_at: Optional[datetime] = Field(None, description="Fulfillment timestamp if completed")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def populate_step_key(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "workflow_step_key" in data and not data.get("step_key"):
                data["step_key"] = data["workflow_step_key"]
            elif "step_key" in data and not data.get("workflow_step_key"):
                data["workflow_step_key"] = data["step_key"]
        elif hasattr(data, "workflow_step_key") and not getattr(data, "step_key", None):
            try:
                setattr(data, "step_key", data.workflow_step_key)
            except Exception:
                pass
        return data


class EvidenceRequestFulfillResponse(BaseModel):
    """Response returned to customer upon fulfilling an evidence request."""
    request: CustomerEvidenceRequestResponse = Field(..., description="The fulfilled evidence request")
    evidence: EvidenceResponse = Field(..., description="The submitted evidence item")
    reasoning_action: Optional[str] = Field(None, description="Immediate AI reasoning outcome if auto-triggered")
    next_step_key: Optional[str] = Field(None, description="Next suggested workflow step if available")
    message: str = Field(..., description="Human-readable status message")
