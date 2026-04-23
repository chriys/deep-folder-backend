"""Worker process that dequeues and executes background jobs."""
import asyncio
import logging
import traceback

from deepfolder.db import _get_session_factory
from deepfolder.job_queue import JobQueue, JobHandlers

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5


async def _run_worker_loop() -> None:
    session_factory = _get_session_factory()

    while True:
        try:
            async with session_factory() as session:
                job = await JobQueue.dequeue_job(session)
                if job is None:
                    await asyncio.sleep(POLL_INTERVAL_S)
                    continue

                logger.info("Claimed job %d (%s)", job.id, job.job_type)
                await JobQueue.mark_in_progress(session, job.id)

                try:
                    await JobHandlers.execute(session, job)
                    await JobQueue.mark_complete(session, job.id)
                    logger.info("Completed job %d (%s)", job.id, job.job_type)
                except Exception:
                    logger.exception("Job %d (%s) failed", job.id, job.job_type)
                    await JobQueue.mark_failed(
                        session, job.id, traceback.format_exc()
                    )
        except Exception:
            logger.exception("Worker loop error")
            await asyncio.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting worker process")
    asyncio.run(_run_worker_loop())
