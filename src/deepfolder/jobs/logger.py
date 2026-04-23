"""Structured logging helpers for background job worker."""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def log_job_claimed(*, job_id: str, kind: str, attempt: int) -> None:
    """Log that a job has been claimed by the worker."""
    log.info("job.claimed", job_id=job_id, kind=kind, attempt=attempt)


def log_job_success(
    *, job_id: str, kind: str, attempt: int, duration_ms: float
) -> None:
    """Log that a job completed successfully."""
    log.info(
        "job.success",
        job_id=job_id,
        kind=kind,
        attempt=attempt,
        duration_ms=duration_ms,
    )


def log_job_failure(
    *,
    job_id: str,
    kind: str,
    attempt: int,
    error: str,
    duration_ms: float,
) -> None:
    """Log that a job failed."""
    log.error(
        "job.failure",
        job_id=job_id,
        kind=kind,
        attempt=attempt,
        error=error,
        duration_ms=duration_ms,
    )
