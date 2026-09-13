"""Dedicated serialized single-worker AI job queue for background Qwen/Llama local inference."""
from enum import Enum
import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


class JobType(str, Enum):
    REFERENCE_ANALYSIS = "REFERENCE_ANALYSIS"
    PROFILE_CONSOLIDATION = "PROFILE_CONSOLIDATION"
    CUSTOMER_VISUAL_ANALYSIS = "CUSTOMER_VISUAL_ANALYSIS"
    LLAMA_REASONING = "LLAMA_REASONING"


@dataclass
class AIJob:
    job_type: JobType
    product_id: Optional[str] = None
    reference_id: Optional[str] = None
    verification_id: Optional[str] = None
    evidence_id: Optional[str] = None
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AIJobQueueManager:
    """Manages a thread-safe, serialized queue for local AI inference tasks.
    
    Serializing execution prevents GPU VRAM overload and local model resource contention
    on single-GPU environments (e.g. RTX 3050 6GB).
    """

    def __init__(self):
        self._queue: queue.Queue[AIJob] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._start_worker()

    def _start_worker(self):
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="AIJobWorkerThread",
                daemon=True,
            )
            self._worker_thread.start()
            logger.info("Started dedicated AI job worker thread")

    def enqueue(self, job: AIJob) -> str:
        """Enqueue an AI job for asynchronous background processing."""
        self._queue.put(job)
        logger.info(
            "Enqueued AI job %s (type: %s, product: %s, reference: %s)",
            job.job_id,
            job.job_type.value,
            job.product_id,
            job.reference_id,
        )
        return job.job_id

    def _worker_loop(self):
        """Worker loop executing AI jobs one by one with clean, isolated DB sessions."""
        while True:
            try:
                job = self._queue.get()
                logger.info("AI Worker processing job %s (%s)", job.job_id, job.job_type.value)
                self._execute_job(job)
            except Exception as exc:
                logger.error("Error in AI worker loop: %s", exc, exc_info=True)
            finally:
                self._queue.task_done()

    def _execute_job(self, job: AIJob):
        """Execute a single job with an independent SQLAlchemy session."""
        db = SessionLocal()
        try:
            if job.job_type == JobType.REFERENCE_ANALYSIS:
                self._handle_reference_analysis(db, job)
            elif job.job_type == JobType.PROFILE_CONSOLIDATION:
                self._handle_profile_consolidation(db, job)
            elif job.job_type == JobType.CUSTOMER_VISUAL_ANALYSIS:
                self._handle_customer_visual_analysis(db, job)
            else:
                logger.warning("Unknown job type: %s", job.job_type)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error(
                "AI job %s failed during execution: %s",
                job.job_id,
                exc,
                exc_info=True,
            )
        finally:
            db.close()

    def _handle_reference_analysis(self, db, job: AIJob):
        if not job.reference_id or not job.product_id:
            logger.error("Invalid REFERENCE_ANALYSIS job parameters")
            return

        from app.services import product_profile_service
        # Process the single reference angle image
        product_profile_service.analyze_single_product_reference(db, job.reference_id)
        # Check if all reference images are ready for consolidation
        product_profile_service.process_product_references_and_consolidate_profile(
            db, job.product_id, force_reanalyze=False
        )

    def _handle_profile_consolidation(self, db, job: AIJob):
        if not job.product_id:
            logger.error("Invalid PROFILE_CONSOLIDATION job parameters")
            return

        from app.services import product_profile_service
        product_profile_service.process_product_references_and_consolidate_profile(
            db, job.product_id, force_reanalyze=True
        )

    def _handle_customer_visual_analysis(self, db, job: AIJob):
        if not job.evidence_id:
            logger.error("Invalid CUSTOMER_VISUAL_ANALYSIS job parameters")
            return

        from app.services import evidence_processing_service
        evidence_processing_service.process_evidence_visual_analysis(db, job.evidence_id)


# Global singleton instance
ai_job_queue = AIJobQueueManager()
