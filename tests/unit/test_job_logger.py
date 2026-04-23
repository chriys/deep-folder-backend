"""Tests for worker job logging."""
import json

import pytest

from deepfolder.logging_config import configure_logging


@pytest.fixture(autouse=True)
def setup_logging() -> None:
    configure_logging()


def test_log_job_claimed(capsys: pytest.CaptureFixture[str]) -> None:
    """log_job_claimed emits a structured log with job_id, kind, and attempt."""
    from deepfolder.jobs.logger import log_job_claimed

    log_job_claimed(job_id="job-1", kind="ingest_folder", attempt=1)

    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    record = json.loads(lines[-1])
    assert record["event"] == "job.claimed"
    assert record["job_id"] == "job-1"
    assert record["kind"] == "ingest_folder"
    assert record["attempt"] == 1


def test_log_job_success(capsys: pytest.CaptureFixture[str]) -> None:
    """log_job_success emits a structured log with job_id, kind, attempt, and duration."""
    from deepfolder.jobs.logger import log_job_success

    log_job_success(job_id="job-2", kind="embed_file", attempt=1, duration_ms=42.5)

    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    record = json.loads(lines[-1])
    assert record["event"] == "job.success"
    assert record["job_id"] == "job-2"
    assert record["kind"] == "embed_file"
    assert record["attempt"] == 1
    assert record["duration_ms"] == 42.5


def test_log_job_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """log_job_failure emits a structured log with job_id, kind, attempt, and error."""
    from deepfolder.jobs.logger import log_job_failure

    log_job_failure(
        job_id="job-3",
        kind="sync_folder",
        attempt=2,
        error="Connection timeout",
        duration_ms=1500.0,
    )

    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    record = json.loads(lines[-1])
    assert record["event"] == "job.failure"
    assert record["job_id"] == "job-3"
    assert record["kind"] == "sync_folder"
    assert record["attempt"] == 2
    assert record["error"] == "Connection timeout"
    assert record["duration_ms"] == 1500.0
