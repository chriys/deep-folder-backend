from typing import Any, Callable

from deepfolder.models.job import Job


JobHandler = Callable[[Job], Any]


class HandlerRegistry:
    """Registry for job handlers keyed by job kind."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, kind: str, handler: JobHandler) -> None:
        """Register a handler for a job kind."""
        self._handlers[kind] = handler

    def get(self, kind: str) -> JobHandler | None:
        """Get a handler for a job kind, or None if not registered."""
        return self._handlers.get(kind)

    def __contains__(self, kind: str) -> bool:
        """Check if a handler is registered for a kind."""
        return kind in self._handlers


# Global handler registry
_registry = HandlerRegistry()


def get_registry() -> HandlerRegistry:
    """Get the global handler registry."""
    return _registry


async def noop_handler(job: Job) -> None:
    """No-op job handler for testing."""
    pass
