"""Pydantic schemas for local AI reasoning using Ollama Llama 3.2 3B."""
import enum
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, AliasChoices, field_validator


class ReasoningAction(str, enum.Enum):
    """Closed action vocabulary allowed for Llama reasoning."""
    ACCEPT_EVIDENCE = "ACCEPT_EVIDENCE"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"
    CONTINUE_WORKFLOW = "CONTINUE_WORKFLOW"
    COMPLETE_VERIFICATION = "COMPLETE_VERIFICATION"


class MissingEvidenceItem(BaseModel):
    """Specific item of missing evidence needed for workflow progression."""
    evidence_type: str = Field(..., description="Type of evidence required (CUSTOMER_IMAGE, CUSTOMER_TEXT, etc.)")
    purpose: str = Field(..., description="Purpose or specific justification for requesting this evidence")

    model_config = ConfigDict(extra="forbid")


class ReasoningResult(BaseModel):
    """Normalized structured reasoning output from Llama 3.2.
    
    Strictly forbids extra fields to block arbitrary LLM assertions (e.g. fraud verdicts or refund decisions).
    """
    action: ReasoningAction = Field(..., description="Workflow progression action from closed vocabulary")
    reasoning_summary: str = Field(..., min_length=5, description="Objective factual reasoning synthesis")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    next_step_key: Optional[str] = Field(None, description="Suggested next workflow step key from frozen workflow")
    requested_evidence_type: Optional[str] = Field(None, description="Type of evidence to request if action is REQUEST_MORE_EVIDENCE (CUSTOMER_IMAGE, MCQ, CUSTOMER_TEXT)")
    reason: Optional[str] = Field(None, description="User-safe justification when requesting more evidence")
    question: Optional[str] = Field(None, description="Targeted question text for MCQ or TEXT follow-up")
    options: Optional[List[str]] = Field(None, description="Dynamic choices for MCQ follow-up")
    missing_evidence: List[MissingEvidenceItem] = Field(default_factory=list, description="Specific missing evidence items")
    observations_used: List[str] = Field(default_factory=list, description="Specific factual observations relied upon")
    limitations: List[str] = Field(default_factory=list, description="Epistemic limitations or missing information")

    model_config = ConfigDict(extra="forbid")

    @field_validator("reasoning_summary", "reason", "question")
    @classmethod
    def validate_summary_no_verdict(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip()
        lower = clean.lower()
        prohibited_phrases = [
            "fraudulent customer",
            "customer is lying",
            "customer is dishonest",
            "fraud detected",
            "refund approved",
            "refund rejected",
            "fraud",
            "scam",
        ]
        for phrase in prohibited_phrases:
            if phrase in lower:
                raise ValueError(f"Reasoning field contains prohibited verdict phrase: '{phrase}'")
        return clean




class ReasoningRunResponse(BaseModel):
    """API response model for a reasoning run record."""
    id: str
    verification_session_id: str
    model_name: str
    prompt_version: str
    input_context_hash: str
    status: str
    result: Optional[ReasoningResult] = Field(
        None,
        validation_alias=AliasChoices("result", "result_json"),
    )
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }

    @field_validator("result", mode="before")
    @classmethod
    def parse_result(cls, v: Any) -> Optional[Any]:
        if not v or not isinstance(v, dict) or "action" not in v:
            return None
        return v
