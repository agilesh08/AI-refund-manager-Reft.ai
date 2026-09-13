"""Pydantic schemas for Milestone 11 Evidence Fusion Engine.

Defines strict structured models for fusion dimensions, contradiction items,
missing evidence items, Llama human-readable explanations with anti-accusation
validators, and merchant / customer response representations.
"""
import enum
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerificationAssessmentState(str, enum.Enum):
    """Assessment state outcomes for evidence fusion."""
    EVIDENCE_CONSISTENT = "EVIDENCE_CONSISTENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INCONSISTENCY_DETECTED = "INCONSISTENCY_DETECTED"


class DimensionType(str, enum.Enum):
    """Independent evaluation dimensions in evidence fusion."""
    CLAIM_VS_VISUAL = "CLAIM_VS_VISUAL"
    CLAIM_VS_PAYMENT = "CLAIM_VS_PAYMENT"
    CLAIM_VS_ORDER = "CLAIM_VS_ORDER"
    CLAIM_VS_DELIVERY = "CLAIM_VS_DELIVERY"
    CLAIM_VS_LOCATION = "CLAIM_VS_LOCATION"
    VISUAL_VS_TRUSTED_REFERENCE = "VISUAL_VS_TRUSTED_REFERENCE"
    ORDER_VS_PAYMENT = "ORDER_VS_PAYMENT"
    ORDER_VS_DELIVERY = "ORDER_VS_DELIVERY"


class DimensionStatus(str, enum.Enum):
    """Status outcomes for each evaluated dimension."""
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    INSUFFICIENT = "INSUFFICIENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ContradictionSeverity(str, enum.Enum):
    """Severity ratings for detected evidence contradictions."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


PROHIBITED_PHRASES = [
    "fraud",
    "fraudulent",
    "scam",
    "scammer",
    "liar",
    "lying",
    "dishonest",
    "fake customer",
    "refund approved",
    "refund rejected",
    "approve refund",
    "reject refund",
    "guilty",
]


class ContradictionItem(BaseModel):
    """Structured representation of a contradiction between two evidence sources."""
    dimension: str = Field(..., description="Affected dimension")
    severity: ContradictionSeverity = Field(..., description="Severity of contradiction (LOW, MEDIUM, HIGH)")
    description: str = Field(..., min_length=1, description="Objective description of conflicting facts")
    source_a: str = Field(..., description="First evidence source category")
    source_b: str = Field(..., description="Second evidence source category")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of involved evidence records")

    model_config = ConfigDict(extra="forbid")

    @field_validator("description")
    @classmethod
    def validate_no_accusations(cls, v: str) -> str:
        lower = v.lower()
        for phrase in PROHIBITED_PHRASES:
            if phrase in lower:
                raise ValueError(f"Contradiction description contains prohibited term '{phrase}'")
        return v


class MissingEvidenceItem(BaseModel):
    """Structured representation of missing or insufficient evidence."""
    workflow_step_key: str = Field(..., min_length=1, description="Workflow step key requiring evidence")
    reason: str = Field(..., min_length=1, description="Factual reason why evidence is insufficient or missing")

    model_config = ConfigDict(extra="forbid")


FusionMissingEvidenceItem = MissingEvidenceItem


class FusionDimensionResult(BaseModel):
    """Structured evaluation result for a single fusion dimension."""
    dimension: DimensionType = Field(..., description="Evaluated dimension")
    status: DimensionStatus = Field(..., description="Outcome: CONSISTENT, INCONSISTENT, INSUFFICIENT, NOT_APPLICABLE")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Dimension confidence score")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of evidence or signal items evaluated")
    details: Optional[Dict[str, Any]] = Field(None, description="Dimension-specific factual details")

    model_config = ConfigDict(extra="forbid")


class FusionExplanation(BaseModel):
    """Human-readable explanation produced by Llama 3.2 based on deterministic fusion facts.

    Strictly validated: Llama is prohibited from modifying states or producing
    accusatory, fraudulent, or verdict language.
    """
    summary: str = Field(..., min_length=1, description="High-level objective assessment summary")
    key_points: List[str] = Field(..., min_length=1, description="Bullet points of verified facts and observations")
    recommended_review: str = Field(..., min_length=1, description="Neutral guidance for merchant human review")

    model_config = ConfigDict(extra="forbid")

    @field_validator("summary", "recommended_review")
    @classmethod
    def validate_clean_language(cls, v: str) -> str:
        lower = v.lower()
        for phrase in PROHIBITED_PHRASES:
            # Word boundary regex check for whole word / phrase match
            pattern = rf"\b{re.escape(phrase)}\b"
            if re.search(pattern, lower):
                raise ValueError(f"Prohibited accusatory/verdict language detected: '{phrase}'")
        return v

    @field_validator("key_points")
    @classmethod
    def validate_clean_points(cls, v: List[str]) -> List[str]:
        for point in v:
            lower = point.lower()
            for phrase in PROHIBITED_PHRASES:
                pattern = rf"\b{re.escape(phrase)}\b"
                if re.search(pattern, lower):
                    raise ValueError(f"Prohibited language in key_points item: '{phrase}'")
        return v


class FusionResultSchema(BaseModel):
    """Complete structured JSON representation produced by deterministic fusion."""
    assessment_state: VerificationAssessmentState
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    dimensions: List[FusionDimensionResult]
    contradictions: List[ContradictionItem] = Field(default_factory=list)
    missing_evidence: List[MissingEvidenceItem] = Field(default_factory=list)
    explanation_facts: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class FusionResponse(BaseModel):
    """Merchant-facing API response for an evidence fusion assessment."""
    id: str
    verification_session_id: str
    assessment_state: str
    overall_confidence: float
    dimensions: List[FusionDimensionResult]
    contradictions: List[ContradictionItem]
    missing_evidence: List[MissingEvidenceItem]
    explanation: Optional[FusionExplanation] = None
    fusion_version: str
    input_context_hash: str
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CustomerFusionResponse(BaseModel):
    """Sanitized customer-facing API response.

    Excludes internal UUIDs, payment transaction IDs, internal confidence calculations,
    and private merchant notes.
    """
    assessment_state: str
    status_display: str
    customer_summary: str
    has_missing_evidence: bool
    missing_steps: List[str] = Field(default_factory=list)
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid")
