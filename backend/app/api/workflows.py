"""Workflow builder and step configuration endpoints."""
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.merchant import Merchant
from app.api.dependencies import get_current_merchant
from app.schemas.workflow import (
    WorkflowCreateRequest,
    WorkflowUpdateRequest,
    WorkflowResponse,
    WorkflowStepCreateRequest,
    WorkflowStepUpdateRequest,
    WorkflowStepResponse,
    WorkflowReorderRequest,
)
from app.services import workflow_service, workflow_step_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Workflow Lifecycle Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new verification workflow draft",
)
def create_workflow(
    data: WorkflowCreateRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    """Create a new verification workflow in DRAFT status."""
    workflow = workflow_service.create_workflow(
        db=db,
        merchant_id=current_merchant.id,
        data=data,
    )
    return WorkflowResponse.model_validate(workflow)


@router.get(
    "",
    response_model=List[WorkflowResponse],
    status_code=status.HTTP_200_OK,
    summary="List merchant's workflows",
)
def list_workflows(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> List[WorkflowResponse]:
    """Retrieve all workflows belonging to the authenticated merchant."""
    workflows = workflow_service.list_merchant_workflows(
        db=db,
        merchant_id=current_merchant.id,
    )
    return [WorkflowResponse.model_validate(w) for w in workflows]


@router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single workflow with steps",
)
def get_workflow(
    workflow_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    """Retrieve an owned workflow along with its defined steps."""
    workflow = workflow_service.get_merchant_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    return WorkflowResponse.model_validate(workflow)


@router.put(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Update workflow metadata",
)
def update_workflow(
    workflow_id: str,
    data: WorkflowUpdateRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    """Update workflow name or description."""
    workflow = workflow_service.update_merchant_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
        data=data,
    )
    return WorkflowResponse.model_validate(workflow)


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete workflow draft or archive",
)
def delete_workflow(
    workflow_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """Delete a workflow draft or archived workflow. Active workflows cannot be deleted."""
    workflow_service.delete_merchant_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    return {"message": "Workflow deleted successfully"}


@router.post(
    "/{workflow_id}/publish",
    response_model=WorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish and activate workflow",
)
def publish_workflow(
    workflow_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    """Validate steps, configuration, and branching, then transition status from DRAFT to ACTIVE."""
    workflow = workflow_service.publish_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    return WorkflowResponse.model_validate(workflow)


@router.post(
    "/{workflow_id}/archive",
    response_model=WorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive workflow",
)
def archive_workflow(
    workflow_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    """Archive an existing workflow, retiring it from future verification sessions."""
    workflow = workflow_service.archive_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    return WorkflowResponse.model_validate(workflow)


# ---------------------------------------------------------------------------
# Workflow Step Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/steps",
    response_model=WorkflowStepResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a step to workflow",
)
def create_step(
    workflow_id: str,
    data: WorkflowStepCreateRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> WorkflowStepResponse:
    """Create a new step in an owned workflow."""
    workflow = workflow_service.get_merchant_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    step = workflow_step_service.create_workflow_step(
        db=db,
        workflow=workflow,
        data=data,
    )
    return WorkflowStepResponse.model_validate(step)


@router.get(
    "/{workflow_id}/steps",
    response_model=List[WorkflowStepResponse],
    status_code=status.HTTP_200_OK,
    summary="List all steps in workflow",
)
def list_steps(
    workflow_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> List[WorkflowStepResponse]:
    """Retrieve all steps of a workflow ordered by step_order."""
    workflow = workflow_service.get_merchant_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    steps = workflow_step_service.list_workflow_steps(
        db=db,
        workflow=workflow,
    )
    return [WorkflowStepResponse.model_validate(s) for s in steps]


@router.put(
    "/{workflow_id}/steps/reorder",
    response_model=List[WorkflowStepResponse],
    status_code=status.HTTP_200_OK,
    summary="Reorder all steps in workflow",
)
def reorder_steps(
    workflow_id: str,
    data: WorkflowReorderRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> List[WorkflowStepResponse]:
    """Assign sequential 1..N order to all workflow steps based on provided ID order."""
    workflow = workflow_service.get_merchant_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    updated_steps = workflow_step_service.reorder_workflow_steps(
        db=db,
        workflow=workflow,
        step_ids=data.step_ids,
    )
    return [WorkflowStepResponse.model_validate(s) for s in updated_steps]


@router.get(
    "/{workflow_id}/steps/{step_id}",
    response_model=WorkflowStepResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single workflow step",
)
def get_step(
    workflow_id: str,
    step_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> WorkflowStepResponse:
    """Retrieve a single step by ID ensuring workflow ownership."""
    workflow = workflow_service.get_merchant_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    step = workflow_step_service.get_workflow_step(
        db=db,
        workflow=workflow,
        step_id=step_id,
    )
    return WorkflowStepResponse.model_validate(step)


@router.put(
    "/{workflow_id}/steps/{step_id}",
    response_model=WorkflowStepResponse,
    status_code=status.HTTP_200_OK,
    summary="Update workflow step",
)
def update_step(
    workflow_id: str,
    step_id: str,
    data: WorkflowStepUpdateRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> WorkflowStepResponse:
    """Update title, description, required flag, or configuration of a step."""
    workflow = workflow_service.get_merchant_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    step = workflow_step_service.update_workflow_step(
        db=db,
        workflow=workflow,
        step_id=step_id,
        data=data,
    )
    return WorkflowStepResponse.model_validate(step)


@router.delete(
    "/{workflow_id}/steps/{step_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete workflow step",
)
def delete_step(
    workflow_id: str,
    step_id: str,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """Delete a step from the workflow and re-sequence remaining steps."""
    workflow = workflow_service.get_merchant_workflow(
        db=db,
        merchant_id=current_merchant.id,
        workflow_id=workflow_id,
    )
    workflow_step_service.delete_workflow_step(
        db=db,
        workflow=workflow,
        step_id=step_id,
    )
    return {"message": "Workflow step deleted successfully"}
