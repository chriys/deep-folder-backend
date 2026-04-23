"""Sentry SDK initialization. No-op when SENTRY_DSN is absent or empty."""
from __future__ import annotations

import sentry_sdk


def init_sentry(*, dsn: str | None) -> None:
    """Initialize Sentry if a DSN is provided; otherwise do nothing.

    App continues to run normally when DSN is absent — Sentry becomes a no-op.
    """
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=1.0,
        send_default_pii=False,
    )
