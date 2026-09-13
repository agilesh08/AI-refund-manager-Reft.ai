"""Reasoning context builder service for local Ollama Llama 3.2 3B reasoning.

Constructs controlled, sanitized, deterministic context for AI reasoning, enforcing
the frozen workflow snapshot and distinguishing information sources.
"""
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.models.evidence import Evidence, EvidenceType
from app.models.verification import VerificationSession
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus

logger = logging.getLogger(__name__)


def build_reasoning_context(
    session: VerificationSession,
    evidence_items: List[Evidence],
    visual_analyses: List[VisualAnalysis],
    evidence_requests: Optional[List[Any]] = None,
    signals: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Construct controlled, structured context for Llama 3.2 reasoning.

    Args:
        session: Active VerificationSession model.
        evidence_items: List of submitted Evidence records for this session.
        visual_analyses: List of VisualAnalysis records for evidence items.
        evidence_requests: Optional list of EvidenceRequest records.
        signals: Optional list of VerificationSignal records.



    Returns:
        Sanitized dict containing only necessary reasoning facts.
    """
    snapshot = session.workflow_snapshot_json or {}
    snapshot_steps = snapshot.get("steps", [])

    # 1. Verification facts
    verification_info = {
        "verification_id": session.verification_id,
        "order_id": session.order_id,
        "refund_reason": session.refund_reason or "",
        "refund_amount": str(session.refund_amount) if session.refund_amount is not None else None,
    }

    # 2. Frozen workflow definition and allowed next actions
    # Identify current step from latest submitted evidence
    current_step_key = None
    if evidence_items:
        # Most recent item with a workflow_step_key
        for ev in reversed(evidence_items):
            if ev.workflow_step_key:
                current_step_key = ev.workflow_step_key
                break

    # If no evidence yet or not found, default to first step of snapshot
    if not current_step_key and snapshot_steps:
        current_step_key = snapshot_steps[0].get("step_key")

    current_step_def = next((s for s in snapshot_steps if s.get("step_key") == current_step_key), None)
    if not current_step_def and snapshot_steps:
        current_step_def = snapshot_steps[0]

    # Allowed next steps: strictly bounded to the frozen snapshot
    allowed_next_steps = [
        {
            "step_key": step.get("step_key"),
            "step_type": step.get("step_type"),
            "title": step.get("title", ""),
            "required": step.get("required", step.get("is_required", False)),
            "supports_adaptive_evidence": step.get("step_type") in ("IMAGE", "CAMERA"),
        }
        for step in snapshot_steps
    ]

    # Extract merchant-configured scenario follow-up questions
    configured_follow_ups: List[str] = []
    customer_statement_text = session.refund_reason or ""
    for ev in evidence_items:
        if ev.evidence_type == EvidenceType.CUSTOMER_TEXT.value and ev.text_content:
            customer_statement_text = f"{customer_statement_text} {ev.text_content}".strip()

    stated_lower = customer_statement_text.lower()
    all_workflow_fqs: List[str] = []
    for step in snapshot_steps:
        cfg = step.get("config") or step.get("config_json") or {}
        options = cfg.get("options") or cfg.get("choices") or cfg.get("scenarios") or []
        for opt in options:
            if isinstance(opt, dict):
                opt_val = str(opt.get("value", "")).lower()
                opt_lbl = str(opt.get("label", "")).lower()
                fqs = opt.get("follow_up_questions")
                if isinstance(fqs, list) and fqs:
                    clean_fqs = [str(q) for q in fqs]
                    all_workflow_fqs.extend(clean_fqs)
                    # Check substring match or word tokens overlap
                    tokens = [t for t in (opt_val + " " + opt_lbl).split() if len(t) > 2]
                    matches = (
                        (opt_val and opt_val in stated_lower) or
                        (opt_lbl and opt_lbl in stated_lower) or
                        any(t in stated_lower for t in tokens) or
                        not stated_lower
                    )
                    if matches:
                        configured_follow_ups.extend(clean_fqs)

    # Fallback to all workflow follow-ups if no specific scenario match
    if not configured_follow_ups and all_workflow_fqs:
        configured_follow_ups.extend(all_workflow_fqs)

    deduped_follow_ups = list(dict.fromkeys(configured_follow_ups))

    workflow_context = {
        "current_step": {
            "step_key": current_step_def.get("step_key") if current_step_def else "unknown",
            "step_type": current_step_def.get("step_type") if current_step_def else "unknown",
            "title": current_step_def.get("title") if current_step_def else "unknown",
        },
        "allowed_next_steps": allowed_next_steps,
        "configured_follow_up_questions": deduped_follow_ups,
    }


    # 3. Evidence items summary
    evidence_summary = [
        {
            "evidence_id": ev.evidence_id,
            "evidence_type": ev.evidence_type,
            "workflow_step_key": ev.workflow_step_key,
            "status": ev.status,
        }
        for ev in evidence_items
    ]

    # 4. Customer Stated Claims (source: CUSTOMER_STATED)
    customer_stated = []
    if session.refund_reason:
        customer_stated.append({
            "source": "CUSTOMER_STATED",
            "field": "refund_reason",
            "statement": session.refund_reason,
        })

    for ev in evidence_items:
        if ev.evidence_type == EvidenceType.CUSTOMER_TEXT.value and ev.text_content:
            customer_stated.append({
                "source": "CUSTOMER_STATED",
                "evidence_id": ev.evidence_id,
                "workflow_step_key": ev.workflow_step_key,
                "statement": ev.text_content,
            })

    # 5. Visual Observations (source: AI_VISUAL_OBSERVATION)
    # Map latest analysis per evidence
    analysis_by_ev_id: Dict[str, VisualAnalysis] = {}
    for a in visual_analyses:
        if a.public_evidence_id and a.public_evidence_id not in analysis_by_ev_id:
            analysis_by_ev_id[a.public_evidence_id] = a
        if a.evidence_id and a.evidence_id not in analysis_by_ev_id:
            analysis_by_ev_id[a.evidence_id] = a

    visual_observations = []
    has_failed_visual_analysis = False
    for ev in evidence_items:
        if ev.evidence_type == EvidenceType.CUSTOMER_IMAGE.value:
            analysis = analysis_by_ev_id.get(ev.evidence_id) or analysis_by_ev_id.get(ev.id)
            if analysis and analysis.status == VisualAnalysisStatus.COMPLETED.value and analysis.result_json:
                res = analysis.result_json
                visual_observations.append({
                    "source": "AI_VISUAL_OBSERVATION",
                    "evidence_id": ev.evidence_id,
                    "visual_analysis_status": "COMPLETED",
                    "status": "COMPLETED",
                    "confidence": analysis.overall_confidence,
                    "capture_assessment": res.get("capture_assessment") or res.get("evidence_capture_assessment"),
                    "image_quality": res.get("image_quality"),
                    "product_identity": res.get("product_identity"),
                    "product_consistency": {
                        "is_same_product_type": res.get("product_consistency", {}).get("is_same_product_type"),
                        "matched_reference_angle": res.get("product_consistency", {}).get("matched_reference_angle"),
                        "brand_marking_visible": res.get("product_consistency", {}).get("brand_marking_visible"),
                        "color_consistency": res.get("product_consistency", {}).get("color_consistency"),
                        "shape_consistency": res.get("product_consistency", {}).get("shape_consistency"),
                    },
                    "visible_condition": {
                        "claimed_damage_visible": res.get("visible_condition", {}).get("claimed_damage_visible"),
                        "damage_type_detected": res.get("visible_condition", {}).get("damage_type_detected"),
                        "damage_location": res.get("visible_condition", {}).get("damage_location"),
                        "damage_severity_observation": res.get("visible_condition", {}).get("damage_severity_observation"),
                        "packaging_condition": res.get("visible_condition", {}).get("packaging_condition"),
                    },
                    "observations": res.get("key_visual_observations", []),
                    "uncertainties": res.get("uncertainties", []),
                    "is_verified": True,
                })
            elif analysis and analysis.status == VisualAnalysisStatus.FAILED.value:
                has_failed_visual_analysis = True
                visual_observations.append({
                    "source": "AI_VISUAL_OBSERVATION",
                    "evidence_id": ev.evidence_id,
                    "visual_analysis_status": "FAILED",
                    "status": "FAILED",
                    "error_message": analysis.error_message or "Visual analysis failed",
                    "note": "Visual analysis failed for this required image evidence; cannot be treated as verified",
                    "is_verified": False,
                })
            else:
                has_failed_visual_analysis = True
                visual_observations.append({
                    "source": "AI_VISUAL_OBSERVATION",
                    "evidence_id": ev.evidence_id,
                    "visual_analysis_status": "FAILED",
                    "status": "UNAVAILABLE",
                    "note": "Visual analysis has not been completed for this image evidence item",
                    "is_verified": False,
                })

    # 6. Deterministic Facts (source: DETERMINISTIC)
    deterministic_facts = [
        {
            "source": "DETERMINISTIC",
            "type": "ORDER_SIGNAL",
            "order_id": session.order_id,
            "customer_name": session.customer_name or "Unknown",
        },
        {
            "source": "DETERMINISTIC",
            "type": "PRODUCT_BASELINE",
            "product_name": session.product.name if session.product else "Unknown",
            "sku": session.product.sku if session.product else "Unknown",
            "reference_angles": ["FRONT", "BACK", "LEFT", "RIGHT"],
        },
    ]

    # Ingest Valid Verification Signals
    sig_list = signals
    if sig_list is None:
        try:
            sig_list = list(session.signals or [])
        except Exception:
            sig_list = []

    for sig in sig_list:
        status_val = getattr(sig, "status", None)
        if status_val == "VALID":
            deterministic_facts.append({
                "source": "DETERMINISTIC",
                "signal_type": getattr(sig, "signal_type", None),
                "source_type": getattr(sig, "source_type", None),
                "source_reference": getattr(sig, "source_reference", None),
                "data": getattr(sig, "data_json", {}),
                "observed_at": sig.observed_at.isoformat() if getattr(sig, "observed_at", None) else None,
            })

    # 7. Adaptive Follow-Up Requests State & History
    req_list = evidence_requests
    if req_list is None:
        try:
            req_list = list(session.evidence_requests or [])
        except Exception:
            req_list = []

    # Map fulfilled answers from text/mcq evidence items
    evidence_by_step = {}
    for ev in evidence_items:
        if ev.workflow_step_key:
            evidence_by_step.setdefault(ev.workflow_step_key, []).append(ev)

    previous_questions: List[str] = []
    previous_answers: List[str] = []
    active_requests = []

    for req in req_list:
        step_key = getattr(req, "workflow_step_key", None)
        reason_text = getattr(req, "reason", None) or ""
        status_val = getattr(req, "status", None)
        opts = getattr(req, "options_json", None)

        # Look up fulfilled customer answer for this step
        customer_answer = None
        if step_key and step_key in evidence_by_step:
            step_evs = evidence_by_step[step_key]
            for ev in reversed(step_evs):
                if ev.text_content:
                    customer_answer = ev.text_content
                    break
                elif ev.evidence_type == "CUSTOMER_IMAGE":
                    customer_answer = f"Uploaded photo ({ev.original_filename or 'image.jpg'})"
                    break

        if reason_text:
            previous_questions.append(reason_text)
        if customer_answer:
            previous_answers.append(customer_answer)

        active_requests.append({
            "id": getattr(req, "id", None),
            "workflow_step_key": step_key,
            "requested_evidence_type": getattr(req, "requested_evidence_type", None),
            "status": status_val,
            "question": reason_text,
            "options": opts,
            "customer_answer": customer_answer,
        })

    followup_count = sum(1 for req in req_list if getattr(req, "status", None) != "CANCELLED")
    has_pending = any(getattr(req, "status", None) == "PENDING" for req in req_list)

    # Extract unresolved visual uncertainties & gaps
    unresolved_issues: List[str] = []
    for vo in visual_observations:
        for unc in vo.get("uncertainties", []):
            if unc and unc not in unresolved_issues:
                unresolved_issues.append(unc)

    adaptive_followup_info = {
        "adaptive_followup_count": followup_count,
        "max_adaptive_followups": settings.MAX_ADAPTIVE_FOLLOWUPS,
        "limit_reached": followup_count >= settings.MAX_ADAPTIVE_FOLLOWUPS,
        "has_pending_request": has_pending,
        "previous_questions": list(dict.fromkeys(previous_questions)),
        "previous_answers": list(dict.fromkeys(previous_answers)),
        "history": active_requests,
    }

    return {
        "verification": verification_info,
        "customer_claim": customer_statement_text,
        "configured_follow_up_questions": deduped_follow_ups,
        "workflow": workflow_context,
        "evidence_submitted": evidence_summary,
        "customer_statements": customer_stated,
        "visual_observations": visual_observations,
        "has_failed_visual_analysis": has_failed_visual_analysis,
        "unresolved_issues": unresolved_issues,
        "previous_questions": list(dict.fromkeys(previous_questions)),
        "previous_answers": list(dict.fromkeys(previous_answers)),
        "deterministic_facts": deterministic_facts,
        "adaptive_followups": adaptive_followup_info,
    }



def calculate_context_hash(context: Dict[str, Any]) -> str:
    """Calculate deterministic SHA-256 hex digest for structured context.
    
    Used for auditability and idempotency caching.
    """
    serialized = json.dumps(context, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
