"""VerificationSignal service for ingesting, validating, normalizing, and retrieving signals."""
import logging
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.verification_signal import (
    VerificationSignal,
    SignalType,
    SourceType,
    SignalStatus,
    utc_now,
)
from app.models.verification import SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.schemas.verification_signal import (
    PaymentSignalData,
    OrderSignalData,
    DeliverySignalData,
    LocationSignalData,
    SignalIngestRequest,
    CustomerSignalResponse,
)
from app.services import verification_service, public_verification_service

logger = logging.getLogger(__name__)

SENSITIVE_FIELD_NAMES = {
    "cvv",
    "cvv2",
    "card_number",
    "card_pan",
    "pan",
    "pin",
    "password",
    "secret",
    "api_key",
    "token",
}


def check_for_sensitive_fields(data: Dict[str, Any]) -> None:
    """Detect and block prohibited sensitive financial credentials or secrets."""
    for key, value in data.items():
        k_lower = key.lower()
        if any(sens in k_lower for sens in SENSITIVE_FIELD_NAMES):
            raise ValueError(f"Prohibited sensitive field '{key}' detected in signal data")
        if isinstance(value, dict):
            check_for_sensitive_fields(value)
        elif isinstance(value, str):
            # Check for full 16-digit card number patterns
            stripped = value.replace(" ", "").replace("-", "")
            if len(stripped) >= 13 and len(stripped) <= 19 and stripped.isdigit():
                raise ValueError("Potential raw card PAN detected in signal data value")


def validate_and_normalize_signal_data(
    signal_type: SignalType,
    raw_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate and normalize signal data against type-specific Pydantic schemas.

    Raises:
        ValueError: If validation fails, bounds are violated, or sensitive data is found.
    """
    check_for_sensitive_fields(raw_data)

    if signal_type == SignalType.PAYMENT:
        validated = PaymentSignalData.model_validate(raw_data)
    elif signal_type == SignalType.ORDER:
        validated = OrderSignalData.model_validate(raw_data)
    elif signal_type == SignalType.DELIVERY:
        validated = DeliverySignalData.model_validate(raw_data)
    elif signal_type == SignalType.LOCATION:
        validated = LocationSignalData.model_validate(raw_data)
    else:
        raise ValueError(f"Unsupported signal_type '{signal_type}'")

    return validated.model_dump(mode="json")


def ingest_signal(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
    request: SignalIngestRequest,
) -> VerificationSignal:
    """Ingest, validate, normalize, and persist a deterministic verification signal.

    Enforces:
    - Merchant tenant isolation and session existence.
    - Session active state (rejects cancelled or expired sessions).
    - Strict Pydantic validation and field normalization.
    - Idempotent deduplication for identical submissions.
    - Audit history preservation for updated data.
    """
    # 1. Fetch session enforcing merchant isolation
    session = verification_service.get_merchant_session(
        db=db,
        merchant_id=merchant_id,
        verification_identifier=verification_identifier,
    )

    # 2. Enforce session state
    if session.status in (SessionStatus.CANCELLED.value, SessionStatus.EXPIRED.value):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Verification session is {session.status.lower()}; cannot ingest signals",
        )
    if session.status not in (SessionStatus.CREATED.value, SessionStatus.IN_PROGRESS.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot ingest signals for session in '{session.status}' state",
        )

    # 3. Validate and normalize signal payload
    try:
        normalized_data = validate_and_normalize_signal_data(
            signal_type=request.signal_type,
            raw_data=request.data,
        )
    except Exception as exc:
        # Audit log rejection
        reject_event = VerificationEvent(
            session_id=session.id,
            verification_id=session.verification_id,
            event_type=VerificationEventType.SIGNAL_REJECTED.value,
            metadata_json={
                "signal_type": request.signal_type.value,
                "source_type": request.source_type.value,
                "source_reference": request.source_reference,
                "error": str(exc)[:255],
            },
        )
        db.add(reject_event)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Signal validation failed: {exc}",
        )

    # 4. Deduplication & update check
    existing = db.execute(
        select(VerificationSignal).where(
            VerificationSignal.verification_session_id == session.id,
            VerificationSignal.signal_type == request.signal_type.value,
            VerificationSignal.source_reference == request.source_reference,
        )
    ).scalars().first()

    if existing:
        if existing.data_json == normalized_data:
            logger.info(
                "Identical signal %s already exists for session %s (ref=%s); returning existing",
                existing.id,
                session.verification_id,
                request.source_reference,
            )
            return existing

        # Data changed: Update record and log audit event
        existing.data_json = normalized_data
        existing.status = SignalStatus.VALID.value
        existing.updated_at = utc_now()
        if request.observed_at:
            existing.observed_at = request.observed_at
        if request.confidence is not None:
            existing.confidence = request.confidence

        update_event = VerificationEvent(
            session_id=session.id,
            verification_id=session.verification_id,
            event_type=VerificationEventType.SIGNAL_UPDATED.value,
            metadata_json={
                "signal_id": existing.id,
                "signal_type": existing.signal_type,
                "source_type": existing.source_type,
                "source_reference": existing.source_reference,
            },
        )
        db.add(update_event)
        db.commit()
        db.refresh(existing)
        logger.info(
            "Updated signal %s for session %s (ref=%s)",
            existing.id,
            session.verification_id,
            request.source_reference,
        )
        return existing

    # 5. Persist new VerificationSignal
    signal = VerificationSignal(
        verification_session_id=session.id,
        signal_type=request.signal_type.value,
        source_type=request.source_type.value,
        status=SignalStatus.VALID.value,
        data_json=normalized_data,
        source_reference=request.source_reference,
        confidence=request.confidence,
        observed_at=request.observed_at or utc_now(),
    )
    db.add(signal)
    db.flush()

    # 6. Immutable audit events: SIGNAL_CREATED and SIGNAL_VALIDATED
    create_event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.SIGNAL_CREATED.value,
        metadata_json={
            "signal_id": signal.id,
            "signal_type": signal.signal_type,
            "source_type": signal.source_type,
            "source_reference": signal.source_reference,
        },
    )
    validate_event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.SIGNAL_VALIDATED.value,
        metadata_json={
            "signal_id": signal.id,
            "signal_type": signal.signal_type,
        },
    )
    db.add(create_event)
    db.add(validate_event)
    db.commit()
    db.refresh(signal)

    logger.info(
        "Ingested deterministic signal %s (type=%s, ref=%s) for session %s",
        signal.id,
        signal.signal_type,
        signal.source_reference,
        session.verification_id,
    )
    return signal


def list_signals(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
    signal_type: Optional[str] = None,
) -> List[VerificationSignal]:
    """List all deterministic signals for an owned verification session."""
    session = verification_service.get_merchant_session(
        db=db,
        merchant_id=merchant_id,
        verification_identifier=verification_identifier,
    )
    stmt = select(VerificationSignal).where(
        VerificationSignal.verification_session_id == session.id
    )
    if signal_type:
        stmt = stmt.where(VerificationSignal.signal_type == signal_type.upper())

    return list(db.execute(stmt.order_by(VerificationSignal.created_at.asc())).scalars().all())


def get_signal(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
    signal_id: str,
) -> VerificationSignal:
    """Retrieve a single deterministic signal for an owned session."""
    session = verification_service.get_merchant_session(
        db=db,
        merchant_id=merchant_id,
        verification_identifier=verification_identifier,
    )
    signal = db.execute(
        select(VerificationSignal).where(
            VerificationSignal.id == signal_id,
            VerificationSignal.verification_session_id == session.id,
        )
    ).scalar_one_or_none()

    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification signal not found for this session",
        )
    return signal


def list_customer_signals(
    db: Session,
    raw_token: str,
) -> List[CustomerSignalResponse]:
    """Retrieve sanitized verification signals for a customer session."""
    session = public_verification_service.get_session_by_token(db, raw_token)

    signals = db.execute(
        select(VerificationSignal).where(
            VerificationSignal.verification_session_id == session.id,
            VerificationSignal.status == SignalStatus.VALID.value,
        ).order_by(VerificationSignal.created_at.asc())
    ).scalars().all()

    sanitized_list = []
    for sig in signals:
        data = sig.data_json or {}
        if sig.signal_type == SignalType.PAYMENT.value:
            safe_summary = {
                "payment_status": data.get("payment_status"),
                "payment_method": data.get("payment_method"),
                "currency": data.get("currency"),
            }
        elif sig.signal_type == SignalType.ORDER.value:
            safe_summary = {
                "order_status": data.get("order_status"),
                "quantity": data.get("quantity"),
            }
        elif sig.signal_type == SignalType.DELIVERY.value:
            safe_summary = {
                "carrier": data.get("carrier"),
                "delivery_status": data.get("delivery_status"),
                "delivered_at": data.get("delivered_at"),
            }
        elif sig.signal_type == SignalType.LOCATION.value:
            safe_summary = {
                "source": data.get("source"),
                "captured_at": data.get("captured_at"),
            }
        else:
            safe_summary = {}

        sanitized_list.append(
            CustomerSignalResponse(
                id=sig.id,
                signal_type=sig.signal_type,
                status=sig.status,
                observed_at=sig.observed_at,
                safe_summary=safe_summary,
            )
        )
    return sanitized_list


def ingest_customer_signal(
    db: Session,
    raw_token: str,
    request: SignalIngestRequest,
) -> VerificationSignal:
    """Ingest, validate, normalize, and persist a customer-provided deterministic signal.

    Validates session token and active state, executes Pydantic normalization,
    and logs immutable audit events.
    """
    session = public_verification_service.get_session_by_token(db, raw_token)

    if session.status in (SessionStatus.CANCELLED.value, SessionStatus.EXPIRED.value):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Verification session is {session.status.lower()}; cannot submit signal",
        )

    # Validate and normalize payload
    normalized_data = validate_and_normalize_signal_data(
        signal_type=request.signal_type,
        raw_data=request.data,
    )

    signal = VerificationSignal(
        verification_session_id=session.id,
        signal_type=request.signal_type.value,
        source_type=SourceType.CUSTOMER_PROVIDED.value,
        status=SignalStatus.VALID.value,
        data_json=normalized_data,
        source_reference=request.source_reference or f"customer_{session.verification_id}",
        confidence=request.confidence or 0.85,
        observed_at=request.observed_at or utc_now(),
    )
    db.add(signal)
    db.flush()

    create_event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.SIGNAL_CREATED.value,
        metadata_json={
            "signal_id": signal.id,
            "signal_type": signal.signal_type,
            "source_type": signal.source_type,
            "source_reference": signal.source_reference,
        },
    )
    db.add(create_event)
    db.commit()
    db.refresh(signal)

    logger.info(
        "Customer ingested deterministic signal %s (type=%s) for session %s",
        signal.id,
        signal.signal_type,
        session.verification_id,
    )
    return signal

