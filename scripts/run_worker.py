"""Worker process entry point for job queue."""
import asyncio
import logging
import sys
from pathlib import Path

# Add src to path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deepfolder.config import settings
from deepfolder.db import _get_session_factory
from deepfolder.services.job_handlers import get_registry, noop_handler
from deepfolder.services.job_queue import JobQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_worker() -> None:
    """Main worker loop that polls for jobs and processes them."""
    registry = get_registry()
    registry.register("noop", noop_handler)

    logger.info("Worker starting...")

    while True:
        try:
            async_session_factory = _get_session_factory()
            async with async_session_factory() as session:
                queue = JobQueue(session)
                job = await queue.claim()

                if job is None:
                    # No jobs available, sleep before checking again
                    await asyncio.sleep(1)
                    continue

                logger.info(f"Claimed job {job.id} of kind {job.kind}")

                handler = registry.get(job.kind)
                if handler is None:
                    error_msg = f"No handler registered for job kind: {job.kind}"
                    logger.error(error_msg)
                    await queue.mark_failed(job.id, error_msg)
                    await session.commit()
                    continue

                try:
                    await handler(job)
                    await queue.mark_succeeded(job.id)
                    logger.info(f"Job {job.id} completed successfully")
                except Exception as e:
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    logger.error(f"Job {job.id} failed: {error_msg}", exc_info=True)
                    await queue.mark_failed(job.id, error_msg)

                await session.commit()

        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_worker())
