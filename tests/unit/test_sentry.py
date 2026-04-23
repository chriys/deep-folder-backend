"""Tests for Sentry initialization."""
import os
from unittest.mock import MagicMock, patch

import pytest


def test_init_sentry_no_op_when_dsn_absent() -> None:
    """init_sentry is a no-op and does not raise when SENTRY_DSN is unset."""
    from deepfolder.sentry import init_sentry

    with patch.dict(os.environ, {}, clear=True):
        with patch("sentry_sdk.init") as mock_init:
            init_sentry(dsn=None)
            mock_init.assert_not_called()


def test_init_sentry_calls_sdk_when_dsn_provided() -> None:
    """init_sentry calls sentry_sdk.init with the given DSN."""
    from deepfolder.sentry import init_sentry

    with patch("sentry_sdk.init") as mock_init:
        init_sentry(dsn="https://key@sentry.io/123")
        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args.kwargs
        assert call_kwargs["dsn"] == "https://key@sentry.io/123"


def test_init_sentry_empty_string_dsn_is_no_op() -> None:
    """Empty string DSN is treated the same as None (no Sentry init)."""
    from deepfolder.sentry import init_sentry

    with patch("sentry_sdk.init") as mock_init:
        init_sentry(dsn="")
        mock_init.assert_not_called()
