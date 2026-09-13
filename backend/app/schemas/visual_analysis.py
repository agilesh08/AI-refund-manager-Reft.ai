"""Pydantic schemas for Gemini Vision visual analysis."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, AliasChoices, field_validator


class EvidenceCaptureAssessment(BaseModel):
    """Visual assessment of how the evidence photo was captured (direct physical vs screen/display)."""
    type: str = Field(
        default="UNCLEAR",
        description="DIRECT_PHYSICAL_APPEARANCE, SCREEN_DISPLAY_APPEARANCE, SCREENSHOT_APPEARANCE, PRINTED_IMAGE_APPEARANCE, or UNCLEAR",
        validation_alias=AliasChoices("type", "capture_context"),
    )
    capture_context: str = Field(
        default="UNCLEAR",
        description="PHYSICAL_PHOTO, SCREEN_DISPLAY, SCREENSHOT, DIGITAL_IMAGE, UNCLEAR",
        validation_alias=AliasChoices("capture_context", "type"),
    )
    screen_artifact_detected: Optional[bool] = Field(
        default=None,
        description="True if monitor frame, desktop UI, pixel grid, or screen glare is observed",
    )
    physical_scene_detected: Optional[bool] = Field(
        default=None,
        description="True if natural ambient lighting, physical depth, real hands/surface are observed",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence of capture assessment")
    observations: List[str] = Field(
        default_factory=list,
        description="Visual indicators observed (e.g. screen bezel, laptop frame, glare, moire pattern, desktop UI, natural depth)",
    )



class ProductIdentityAnalysis(BaseModel):
    """Structured product identification and merchant baseline comparison."""
    apparent_product_type: str = Field(..., description="Observed product type/name in image (e.g. computer mouse, in-ear earphones)")
    matches_trusted_product: str = Field(..., description="MATCH, MISMATCH, UNCERTAIN, NOT_APPLICABLE")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence in product identity determination")
    identifying_features_visible: List[str] = Field(default_factory=list, description="Visible features used to establish identity")
    notes: Optional[str] = Field(None, description="Detailed product identity notes")


class ImageQualityAnalysis(BaseModel):
    """Visual assessment of the customer evidence image quality."""
    is_clear: bool = Field(True, description="Whether the image is clear enough for evaluation")
    lighting: str = Field("good", description="Lighting condition: good, dim, harsh, unclear")
    blur_detected: bool = Field(False, description="Whether significant motion or focus blur is present")
    resolution_adequate: bool = Field(True, description="Whether resolution allows identifying product details")
    overall: str = Field("GOOD", description="GOOD, ACCEPTABLE, POOR, INSUFFICIENT")
    product_visibility: str = Field("CLEAR", description="CLEAR, PARTIAL, UNCLEAR, NOT_VISIBLE")
    issues: List[str] = Field(default_factory=list, description="Quality issues: blur, darkness, overexposure, glare, obstruction, etc.")
    notes: Optional[str] = Field(None, description="Additional image quality observations")


class ProductConsistencyAnalysis(BaseModel):
    """Comparison observations between customer evidence and merchant reference product."""
    is_same_product_type: str = Field(..., description="observed, not_observed, unclear")
    matched_reference_angle: Optional[str] = Field(None, description="FRONT, BACK, LEFT, RIGHT, MULTIPLE, NONE")
    brand_marking_visible: str = Field(..., description="observed, not_observed, not_visible, unclear")
    color_consistency: str = Field(..., description="consistent, inconsistent, unclear")
    shape_consistency: str = Field(..., description="consistent, inconsistent, unclear")
    notes: Optional[str] = Field(None, description="Observations comparing against merchant reference angles")


class VisibleConditionAnalysis(BaseModel):
    """Visual inspection of claimed damage or item condition."""
    claimed_damage_visible: str = Field(..., description="observed, not_observed, not_visible, unclear")
    damage_type_detected: Optional[str] = Field(None, description="Type of damage observed (crack, tear, dent, etc.)")
    damage_location: Optional[str] = Field(None, description="Location on product where damage appears")
    damage_severity_observation: Optional[str] = Field(None, description="minor, moderate, severe, superficial, unclear")
    packaging_condition: Optional[str] = Field(None, description="Observations on visible packaging")
    notes: Optional[str] = Field(None, description="Specific visual details of the damage area")


class VisualAnalysisResult(BaseModel):
    """Structured output payload produced by Gemini Vision visual consistency analysis."""
    image_quality: ImageQualityAnalysis
    product_consistency: ProductConsistencyAnalysis
    visible_condition: VisibleConditionAnalysis
    capture_assessment: EvidenceCaptureAssessment = Field(
        default_factory=lambda: EvidenceCaptureAssessment(
            type="UNCLEAR",
            confidence=0.0,
            observations=[],
        ),
        validation_alias=AliasChoices("capture_assessment", "evidence_capture_assessment"),
    )
    product_identity: Optional[ProductIdentityAnalysis] = None
    key_visual_observations: List[str] = Field(default_factory=list, description="Objective visual observations")
    uncertainties: List[str] = Field(default_factory=list, description="Visual limitations or occluded details")
    overall_visual_confidence: float = Field(..., ge=0.0, le=1.0, description="Visual assessment confidence between 0.0 and 1.0")

    model_config = {
        "populate_by_name": True,
    }


class VisualAnalysisResponse(BaseModel):
    """API response model for evidence visual analysis record."""
    id: str
    evidence_id: str = Field(
        ...,
        validation_alias=AliasChoices("public_evidence_id", "evidence_id"),
    )
    model_name: str
    prompt_version: str
    overall_confidence: Optional[float] = None
    status: str
    result: Optional[VisualAnalysisResult] = Field(
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
        if not v or not isinstance(v, dict) or "image_quality" not in v:
            return None
        return v
