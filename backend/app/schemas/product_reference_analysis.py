"""Pydantic schemas for merchant reference image analysis and consolidated product visual profile."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, AliasChoices


class ReferenceImageVisualMetadata(BaseModel):
    """Structured visual characteristics extracted from a single merchant product reference image."""
    product_category: str = Field(..., description="Observed product category (e.g. Headphones, Smartphone, Footwear)")
    brand: Optional[str] = Field(None, description="Observed or inferred brand name")
    model: Optional[str] = Field(None, description="Observed or inferred model designation/number")
    visible_product_identity: str = Field(..., description="Clear concise summary of what item is visible")
    shape: str = Field(..., description="Geometric shape and silhouette characteristics")
    dimensions_proportions: str = Field("unclear", description="Visually inferable proportions or estimated dimensions")
    color: str = Field(..., description="Primary and secondary colors observed")
    material: str = Field("unclear", description="Primary materials (plastic, metal, leather, glass, fabric, etc.)")
    texture_finish: str = Field("unclear", description="Surface texture and finish (matte, glossy, brushed, textured, etc.)")
    distinctive_features: List[str] = Field(default_factory=list, description="Unique design elements, hinges, seams, joints, curves")
    buttons_ports_components: List[str] = Field(default_factory=list, description="Visible buttons, charging ports, LEDs, grilles, connectors")
    logos_markings: List[str] = Field(default_factory=list, description="Visible logos, brand emblems, text, regulatory badges, labels")
    visible_text: List[str] = Field(default_factory=list, description="Any readable text printed on product or serial labels")
    packaging_characteristics: Optional[str] = Field(None, description="Packaging box, seals, or tags visible in image")
    physical_condition: str = Field("NEW", description="Condition of item in reference photo (NEW, PRISTINE, LIGHT_WEAR)")
    orientation_angle: str = Field(..., description="FRONT, BACK, LEFT, RIGHT, OBLIQUE")
    important_landmarks: List[str] = Field(default_factory=list, description="Key visual landmarks for cross-angle comparison")
    image_quality: str = Field("GOOD", description="Quality of reference photo (EXCELLENT, GOOD, ACCEPTABLE, LOW_RES)")
    occlusions: List[str] = Field(default_factory=list, description="Any areas occluded or out of frame")
    uncertainties: List[str] = Field(default_factory=list, description="Visual details that cannot be determined from this angle")


class ProductReferenceAnalysisResult(BaseModel):
    """Structured result payload for single reference image analysis."""
    angle: str = Field(..., description="Canonical reference angle (FRONT, BACK, LEFT, RIGHT)")
    metadata: ReferenceImageVisualMetadata
    summary: str = Field(..., description="Factual concise synthesis of reference image observations")
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)


class ProductVisualProfileResult(BaseModel):
    """Canonical Product Visual Profile consolidated by Llama 3.2 1B from 4 Qwen reference observations."""
    canonical_product_name: str = Field(..., description="Official canonical product name")
    brand: str = Field("Unspecified", description="Consolidated brand name")
    model: str = Field("Unspecified", description="Consolidated model designation")
    category: str = Field(..., description="Consolidated product category")
    primary_colors: List[str] = Field(default_factory=list, description="All primary colors across reference angles")
    materials_finish: List[str] = Field(default_factory=list, description="Materials and surface finishes observed")
    key_design_features: List[str] = Field(default_factory=list, description="Key design features across all angles")
    angle_specific_expectations: Dict[str, str] = Field(
        default_factory=dict,
        description="Expected visual appearance mapped by angle (FRONT, BACK, LEFT, RIGHT)",
    )
    visible_identifiers_and_text: List[str] = Field(
        default_factory=list,
        description="Logos, serial numbers, regulatory marks across all angles",
    )
    distinguishing_landmarks: List[str] = Field(
        default_factory=list,
        description="Landmarks for forensic visual comparison against customer evidence",
    )
    packaging_characteristics: Optional[str] = Field(None, description="Packaging details if present")
    known_limitations_uncertainties: List[str] = Field(
        default_factory=list,
        description="Any details not visible from the 4 reference angles",
    )
    provenance_summary: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Feature provenance mapping showing which angle established each feature",
    )
