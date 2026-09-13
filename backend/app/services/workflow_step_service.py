"""Workflow step business logic and configuration validation."""
import logging
from typing import Any, Dict, List
from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.workflow_step import WorkflowStep, WorkflowStepType
from app.schemas.workflow import (
    WorkflowStepCreateRequest,
    WorkflowStepUpdateRequest,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration Validation Helpers
# ---------------------------------------------------------------------------

def validate_step_config(step_type: str, config: Dict[str, Any], current_step_key: str) -> None:
    """Validate configuration payload according to canonical step type requirements."""
    if not isinstance(config, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Step config must be a JSON object",
        )

    # 1. Step-type specific validation
    if step_type == WorkflowStepType.MCQ.value:
        options = config.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="MCQ step requires an 'options' list with at least 2 selectable choices",
            )
        seen_values = set()
        for idx, opt in enumerate(options):
            if not isinstance(opt, dict):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Option at index {idx} must be an object with 'value' and 'label'",
                )
            val = str(opt.get("value", "")).strip()
            lbl = str(opt.get("label", "")).strip()
            if not val or not lbl:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Option at index {idx} must contain non-empty 'value' and 'label'",
                )
            if val in seen_values:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Duplicate option value '{val}' detected in MCQ options",
                )
            seen_values.add(val)

    elif step_type == WorkflowStepType.TEXT.value:
        min_len = config.get("min_length", 0)
        max_len = config.get("max_length", 1000)
        if not isinstance(min_len, int) or min_len < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="TEXT step 'min_length' must be a non-negative integer",
            )
        if not isinstance(max_len, int) or max_len <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="TEXT step 'max_length' must be a positive integer",
            )
        if min_len > max_len:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"TEXT step 'min_length' ({min_len}) cannot exceed 'max_length' ({max_len})",
            )

    elif step_type in (WorkflowStepType.IMAGE.value, WorkflowStepType.CAMERA.value):
        min_imgs = config.get("min_images", 1)
        max_imgs = config.get("max_images", 4)
        if not isinstance(min_imgs, int) or min_imgs < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{step_type} step 'min_images' must be at least 1",
            )
        if not isinstance(max_imgs, int) or max_imgs < min_imgs:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{step_type} step 'max_images' ({max_imgs}) cannot be less than 'min_images' ({min_imgs})",
            )

    # 2. Conditional branching validation
    conditions = config.get("conditions")
    if conditions is not None:
        if not isinstance(conditions, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="'conditions' must be a list of conditional branch definitions",
            )
        for idx, cond in enumerate(conditions):
            if not isinstance(cond, dict):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Condition at index {idx} must be an object",
                )
            when = cond.get("when")
            next_step = cond.get("next_step")
            if not isinstance(when, dict):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Condition at index {idx} must include a 'when' specification",
                )
            cond_key = str(when.get("step_key", "")).strip()
            op = str(when.get("operator", "")).strip().lower()
            if not cond_key:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Condition at index {idx} 'when.step_key' cannot be empty",
                )
            if op != "equals":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Condition operator '{op}' is unsupported. Only 'equals' is supported",
                )
            if not next_step or not isinstance(next_step, str):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Condition at index {idx} must specify a valid 'next_step' target key",
                )
            if next_step == current_step_key:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Self-loop detected: 'next_step' cannot target current step '{current_step_key}'",
                )

    default_next = config.get("default_next_step")
    if default_next is not None:
        if not isinstance(default_next, str) or not default_next.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="'default_next_step' must be a non-empty string",
            )
        if default_next == current_step_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Self-loop detected: 'default_next_step' cannot target current step '{current_step_key}'",
            )


# ---------------------------------------------------------------------------
# Step Operations
# ---------------------------------------------------------------------------

def create_workflow_step(
    db: Session,
    workflow,
    data: WorkflowStepCreateRequest,
) -> WorkflowStep:
    """Create a new step within an owned workflow with config and key validation."""
    # Check duplicate step_key
    existing = db.execute(
        select(WorkflowStep).where(
            WorkflowStep.workflow_id == workflow.id,
            WorkflowStep.step_key == data.step_key,
        )
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Step with key '{data.step_key}' already exists in this workflow",
        )

    # Validate configuration
    config = data.config or {}
    validate_step_config(data.step_type.value, config, data.step_key)

    # Determine step_order
    if data.step_order is not None:
        order = data.step_order
    else:
        max_order = db.execute(
            select(func.max(WorkflowStep.step_order)).where(
                WorkflowStep.workflow_id == workflow.id
            )
        ).scalar()
        order = (max_order or 0) + 1

    step = WorkflowStep(
        workflow_id=workflow.id,
        step_key=data.step_key,
        step_type=data.step_type.value,
        title=data.title,
        description=data.description,
        step_order=order,
        required=data.required,
        config_json=config,
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    logger.info("Created step '%s' (%s) in workflow %s", step.step_key, step.step_type, workflow.id)
    return step


def list_workflow_steps(db: Session, workflow) -> List[WorkflowStep]:
    """List all steps for a workflow in ascending step_order."""
    return list(
        db.execute(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow.id)
            .order_by(WorkflowStep.step_order.asc())
        ).scalars().all()
    )


def get_workflow_step(db: Session, workflow, step_id: str) -> WorkflowStep:
    """Retrieve an individual step guaranteeing workflow membership."""
    step = db.execute(
        select(WorkflowStep).where(
            WorkflowStep.id == step_id,
            WorkflowStep.workflow_id == workflow.id,
        )
    ).scalar_one_or_none()

    if not step:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow step not found",
        )
    return step


def update_workflow_step(
    db: Session,
    workflow,
    step_id: str,
    data: WorkflowStepUpdateRequest,
) -> WorkflowStep:
    """Update step title, description, required flag, or configuration."""
    step = get_workflow_step(db, workflow, step_id)

    if data.config is not None:
        validate_step_config(step.step_type, data.config, step.step_key)
        step.config_json = data.config

    if data.title is not None:
        step.title = data.title

    if data.description is not None:
        step.description = data.description

    if data.required is not None:
        step.required = data.required

    db.commit()
    db.refresh(step)
    logger.info("Updated step %s in workflow %s", step_id, workflow.id)
    return step


def delete_workflow_step(db: Session, workflow, step_id: str) -> None:
    """Delete a step and re-index remaining steps sequentially."""
    step = get_workflow_step(db, workflow, step_id)
    db.delete(step)
    db.commit()

    # Re-sequence remaining steps
    remaining = list_workflow_steps(db, workflow)
    for idx, s in enumerate(remaining):
        s.step_order = idx + 1
    db.commit()
    logger.info("Deleted step %s and re-sequenced workflow %s", step_id, workflow.id)


def reorder_workflow_steps(
    db: Session,
    workflow,
    step_ids: List[str],
) -> List[WorkflowStep]:
    """Reorder all steps in a workflow sequentially (1..N) with full validation."""
    existing_steps = list_workflow_steps(db, workflow)
    existing_map = {s.id: s for s in existing_steps}

    # 1. Reject duplicate step IDs
    if len(step_ids) != len(set(step_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Reorder request contains duplicate step IDs",
        )

    # 2. Check for missing or foreign step IDs
    if set(step_ids) != set(existing_map.keys()):
        missing = set(existing_map.keys()) - set(step_ids)
        foreign = set(step_ids) - set(existing_map.keys())
        err_msg = []
        if missing:
            err_msg.append(f"Missing steps: {list(missing)}")
        if foreign:
            err_msg.append(f"Foreign/invalid step IDs: {list(foreign)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Reorder list must contain all and only existing steps of this workflow. {'; '.join(err_msg)}",
        )

    # 3. Assign sequential ordering
    for idx, sid in enumerate(step_ids):
        existing_map[sid].step_order = idx + 1

    db.commit()
    logger.info("Successfully reordered %d steps for workflow %s", len(step_ids), workflow.id)
    return list_workflow_steps(db, workflow)
