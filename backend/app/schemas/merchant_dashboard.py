"""Pydantic schemas for Milestone 12: Merchant Dashboard, Investigation View, Timeline, and Explainable Final Report."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.merchant_decision import DecisionType, ActionTaken
from app.schemas.evidence import EvidenceResponse
from app.schemas.evidence_fusion import (
    FusionDimensionResult,
    ContradictionItem,
    MissingEvidenceItem,
    FusionResponse,
    FusionExplanation,
)
from app.schemas.reasoning import ReasoningRunResponse
from app.schemas.evidence_request import EvidenceRequestResponse


# ===========================================================================
# 1. Dashboard Verification Listing Schemas
# ===========================================================================

class DashboardVerificationItem(BaseModel):
    """Lightweight summary item for merchant dashboard table view."""
    id: Optional[str] = None
    verification_id: str
    order_id: str
    product_name: Optional[str] = None
    refund_amount: Optional[float] = None
    status: str
    assessment_state: Optional[str] = None
    confidence: Optional[float] = None
    customer_id: Optional[str] = None
    customer_email: Optional[str] = None
    latest_assessment_state: Optional[str] = None
    latest_decision: Optional[str] = None
    evidence_count: int = 0
    product: Optional[Dict[str, Any]] = None
    held_at: Optional[datetime] = None
    hold_until: Optional[datetime] = None
    held_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DashboardVerificationListResponse(BaseModel):
    """Paginated response contract for merchant verification dashboard."""
    items: List[DashboardVerificationItem]
    page: int = 1
    page_size: int = 20
    total: int = 0

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# 2. Merchant Decision Schemas
# ===========================================================================

class MerchantDecisionCreateRequest(BaseModel):
    """Request payload for recording a human merchant refund decision."""
    decision: DecisionType = Field(..., description="REFUND_APPROVED, REFUND_REJECTED, or MANUAL_REVIEW")
    notes: Optional[str] = Field(None, max_length=2000, description="Merchant rationale/notes for the decision")
    decision_reason: Optional[str] = Field(None, max_length=2000, description="Merchant rationale for the decision")
    rejection_reasons: Optional[List[str]] = Field(default_factory=list, description="List of reasons for rejection")
    action_taken: Optional[Union[ActionTaken, str]] = Field(None, description="Action taken (FULL_REFUND, etc.)")

    @field_validator("decision_reason", "notes")
    @classmethod
    def clean_text(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            return clean if clean else None
        return None

    model_config = ConfigDict(extra="forbid")


class MerchantDecisionResponse(BaseModel):
    """Structured response representing a recorded merchant decision."""
    id: str
    decision_id: Optional[str] = None
    verification_session_id: str
    merchant_id: str
    decision: str
    decision_reason: Optional[str] = None
    notes: Optional[str] = None
    rejection_reasons: Optional[List[str]] = None
    action_taken: Optional[str] = None
    decided_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def model_validate(cls, obj: Any, *args, **kwargs):
        instance = super().model_validate(obj, *args, **kwargs)
        if not instance.decision_id:
            instance.decision_id = instance.id
        if not instance.notes and instance.decision_reason:
            instance.notes = instance.decision_reason
        elif not instance.decision_reason and instance.notes:
            instance.decision_reason = instance.notes
        return instance


# ===========================================================================
# 3. Timeline Schemas
# ===========================================================================

class TimelineItemResponse(BaseModel):
    """Chronological event entry in verification session audit timeline."""
    timestamp: datetime
    event_type: str
    title: str
    description: str
    source: str = Field(..., description="SYSTEM, CUSTOMER, MERCHANT, GEMINI_VISION, LLAMA_REASONING, EXTERNAL_SIGNAL")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# 4. Explainable Verification Report Schemas (9 Sections)
# ===========================================================================

class ReportAssessmentSection(BaseModel):
    """Authoritative consistency assessment output."""
    state: str
    overall_confidence: float
    confidence: Optional[float] = None
    rule_evaluation_summary: str
    assessed_at: Optional[datetime] = None
    fusion_id: Optional[str] = None
    input_context_hash: Optional[str] = None
    reasoning: Optional[str] = None


class ReportClaimSection(BaseModel):
    """Customer refund claim details."""
    refund_reason: Optional[str] = None
    refund_amount: Optional[float] = None
    claimed_item_condition: Optional[str] = None
    order_id: str
    customer_name: Optional[str] = None
    customer_contact: Optional[str] = None


class ReportEvidenceSummarySection(BaseModel):
    """Statistical summary of evidence collected."""
    total_items: int = 0
    total_evidence_count: int = 0
    images_count: int = 0
    videos_count: int = 0
    text_count: int = 0
    adaptive_count: int = 0
    analyzed_count: int = 0
    failed_analysis_count: int = 0
    missing_evidence_count: int = 0


class ReportVisualEvidenceItem(BaseModel):
    """Sanitized visual analysis findings for a single customer image."""
    evidence_id: str
    status: str
    model_name: Optional[str] = None
    confidence: Optional[float] = None
    product_consistency: Optional[Dict[str, Any]] = None
    visible_condition: Optional[Dict[str, Any]] = None
    key_visual_observations: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class ReportSignalItem(BaseModel):
    """Sanitized deterministic transaction signal for report display."""
    id: str
    signal_type: str
    source_type: str
    source_reference: Optional[str] = None
    status: str
    confidence: Optional[float] = None
    observed_at: Optional[datetime] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class ReportAiExplanationSection(BaseModel):
    """Neutral Llama-generated human-readable explanation."""
    source: str = "LOCAL_LLAMA_EXPLANATION"
    model: str = "llama3.2:1b"
    prompt_version: str = "v1"
    status: str = "COMPLETED"
    explanation: Optional[Dict[str, Any]] = None


class ExplainableVerificationReportResponse(BaseModel):
    """Comprehensive, explainable verification report contract with 9 sections."""
    verification_id: str
    assessment_state: str
    overall_confidence: float

    # 9 Structured Sections
    executive_summary: Dict[str, Any] = Field(default_factory=dict)
    consistency_assessment: Dict[str, Any] = Field(default_factory=dict)
    visual_consistency_findings: Dict[str, Any] = Field(default_factory=dict)
    signal_verification_findings: Dict[str, Any] = Field(default_factory=dict)
    multi_source_fusion_matrix: Dict[str, Any] = Field(default_factory=dict)
    claim_vs_evidence_reconciliation: Dict[str, Any] = Field(default_factory=dict)
    missing_evidence_and_follow_up: Dict[str, Any] = Field(default_factory=dict)
    merchant_decision_context: Dict[str, Any] = Field(default_factory=dict)
    ai_audit_trail: Dict[str, Any] = Field(default_factory=dict)

    # Legacy / Compatibility fields
    assessment: Optional[ReportAssessmentSection] = None
    claim: Optional[ReportClaimSection] = None
    evidence_summary: Optional[ReportEvidenceSummarySection] = None
    visual_evidence: List[ReportVisualEvidenceItem] = Field(default_factory=list)
    trusted_reference_comparison: Dict[str, Any] = Field(default_factory=dict)
    deterministic_signals: List[ReportSignalItem] = Field(default_factory=list)
    fusion_dimensions: List[FusionDimensionResult] = Field(default_factory=list)
    missing_evidence: List[MissingEvidenceItem] = Field(default_factory=list)
    contradictions: List[ContradictionItem] = Field(default_factory=list)
    ai_explanation: Optional[ReportAiExplanationSection] = None
    merchant_decision: Optional[MerchantDecisionResponse] = None

    # Full Investigation Trail (Post-M13 Requirement 4 & 6)
    questions_asked: List[Dict[str, Any]] = Field(default_factory=list)
    adaptive_follow_up_questions: List[Dict[str, Any]] = Field(default_factory=list)
    visual_findings_categorized: Dict[str, Any] = Field(default_factory=dict)
    deterministic_signal_statuses: Dict[str, str] = Field(default_factory=dict)
    recommendation_code: Optional[str] = None
    recommendation_label: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# 5. Verification Detail / Investigation View Schema
# ===========================================================================

class VerificationDetailDashboardResponse(BaseModel):
    """Unified merchant investigation view aggregating all 13 session facets."""
    verification: Dict[str, Any]
    product: Dict[str, Any]
    claim: Dict[str, Any]
    workflow: Dict[str, Any]
    evidence_summary: ReportEvidenceSummarySection
    evidence_items: List[EvidenceResponse] = Field(default_factory=list)
    evidence: List[EvidenceResponse] = Field(default_factory=list)
    visual_analysis_summary: Dict[str, Any] = Field(default_factory=dict)
    visual_analysis_items: List[ReportVisualEvidenceItem] = Field(default_factory=list)
    visual_analysis: List[ReportVisualEvidenceItem] = Field(default_factory=list)
    signals_summary: Dict[str, Any] = Field(default_factory=dict)
    signal_items: List[ReportSignalItem] = Field(default_factory=list)
    signals: List[ReportSignalItem] = Field(default_factory=list)
    adaptive_requests: List[EvidenceRequestResponse] = Field(default_factory=list)
    fusion_result: Optional[FusionResponse] = None
    fusion: Optional[FusionResponse] = None
    llama_reasoning: Optional[ReasoningRunResponse] = None
    reasoning: Optional[ReasoningRunResponse] = None
    timeline: List[TimelineItemResponse] = Field(default_factory=list)
    merchant_decision: Optional[MerchantDecisionResponse] = None
    decisions: List[MerchantDecisionResponse] = Field(default_factory=list)
    report: Optional[ExplainableVerificationReportResponse] = None

    # Full Investigation Trail (Post-M13 Requirement 4 & 6)
    questions_asked: List[Dict[str, Any]] = Field(default_factory=list)
    adaptive_follow_up_questions: List[Dict[str, Any]] = Field(default_factory=list)
    visual_findings_categorized: Dict[str, Any] = Field(default_factory=dict)
    deterministic_signal_statuses: Dict[str, str] = Field(default_factory=dict)
    recommendation_code: Optional[str] = None
    recommendation_label: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
