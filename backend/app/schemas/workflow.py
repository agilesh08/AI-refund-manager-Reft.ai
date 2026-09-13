from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, AliasChoices, field_validator

from app.models.workflow import WorkflowStatus
from app.models.workflow_step import WorkflowStepType


class WorkflowCreateRequest(BaseModel):
    """Request schema for creating a new verification workflow."""
    name: str = Field(..., min_length=1, max_length=255, description="Descriptive name of the workflow")
    description: Optional[str] = Field(None, max_length=2000, description="Optional description of verification purpose")

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Workflow name cannot be empty or whitespace only")
        return clean


class WorkflowUpdateRequest(BaseModel):
    """Request schema for updating workflow metadata."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated name")
    description: Optional[str] = Field(None, max_length=2000, description="Updated description")

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                raise ValueError("Workflow name cannot be blank")
            return clean
        return v


class WorkflowStepCreateRequest(BaseModel):
    """Request schema for adding a new step to a workflow."""
    step_key: str = Field(..., min_length=1, max_length=100, description="Unique identifier for step within workflow")
    step_type: WorkflowStepType = Field(..., description="Canonical step type (MCQ, TEXT, IMAGE, etc.)")
    title: str = Field(..., min_length=1, max_length=255, description="Display title for customer guidance")
    description: Optional[str] = Field(None, max_length=2000, description="Optional step guidance or instructions")
    required: bool = Field(True, description="Whether completing this step is mandatory")
    step_order: Optional[int] = Field(None, ge=1, description="Optional 1-based ordering index")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Step-type specific configuration")

    @field_validator("step_key", "title")
    @classmethod
    def strip_text(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Field cannot be empty or whitespace only")
        return clean


class WorkflowStepUpdateRequest(BaseModel):
    """Request schema for updating an existing step."""
    title: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated title")
    description: Optional[str] = Field(None, max_length=2000, description="Updated guidance")
    required: Optional[bool] = Field(None, description="Updated mandatory flag")
    config: Optional[Dict[str, Any]] = Field(None, description="Updated step configuration")

    @field_validator("title")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                raise ValueError("Title cannot be blank")
            return clean
        return v


class WorkflowStepResponse(BaseModel):
    """Public representation of a workflow step."""
    id: str
    workflow_id: str
    step_key: str
    step_type: str
    title: str
    description: Optional[str] = None
    step_order: int
    required: bool
    config: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("config", "config_json"),
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class WorkflowResponse(BaseModel):
    """Public representation of a verification workflow."""
    id: str
    merchant_id: str
    name: str
    description: Optional[str] = None
    status: str
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime
    steps: Optional[List[WorkflowStepResponse]] = None

    model_config = ConfigDict(from_attributes=True)


class WorkflowReorderRequest(BaseModel):
    """Request schema for reordering all steps within a workflow."""
    step_ids: List[str] = Field(..., min_length=1, description="Ordered list containing all step IDs of the workflow")
