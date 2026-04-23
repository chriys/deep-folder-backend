"""Tests for structlog configuration."""
import io
import json
import logging
import sys
from unittest.mock import patch

import pytest
import structlog


def test_configure_structlog_outputs_json(capsys: pytest.CaptureFixture[str]) -> None:
    """Configured logger emits valid JSON to stdout."""
    from deepfolder.logging_config import configure_logging

    configure_logging()
    log = structlog.get_logger("test")
    log.info("hello", key="value")

    captured = capsys.readouterr()
    record = json.loads(captured.out.strip())
    assert record["event"] == "hello"
    assert record["key"] == "value"
    assert "timestamp" in record


def test_log_record_contains_iso8601_timestamp(capsys: pytest.CaptureFixture[str]) -> None:
    """Log records include ISO-8601 timestamp field."""
    from deepfolder.logging_config import configure_logging

    configure_logging()
    log = structlog.get_logger("test")
    log.info("ts_test")

    captured = capsys.readouterr()
    record = json.loads(captured.out.strip())
    ts = record["timestamp"]
    # ISO-8601: contains T separator and Z or +HH:MM
    assert "T" in ts


def test_log_record_contains_level(capsys: pytest.CaptureFixture[str]) -> None:
    """Log records include level field."""
    from deepfolder.logging_config import configure_logging

    configure_logging()
    log = structlog.get_logger("test")
    log.warning("warn_event")

    captured = capsys.readouterr()
    record = json.loads(captured.out.strip())
    assert record.get("level") == "warning"


def test_configure_logging_is_idempotent() -> None:
    """Calling configure_logging twice does not raise."""
    from deepfolder.logging_config import configure_logging

    configure_logging()
    configure_logging()  # second call should be harmless


def test_bind_request_id_in_context(capsys: pytest.CaptureFixture[str]) -> None:
    """Bound context vars (like request_id) appear in log output."""
    from deepfolder.logging_config import configure_logging

    configure_logging()
    log = structlog.get_logger("test").bind(request_id="req-abc-123")
    log.info("bound_event")

    captured = capsys.readouterr()
    record = json.loads(captured.out.strip())
    assert record["request_id"] == "req-abc-123"
    assert record["event"] == "bound_event"
