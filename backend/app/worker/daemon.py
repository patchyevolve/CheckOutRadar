"""Standalone Worker Daemon Process for Docker Compose."""

import time
import os
import logging
from ..db import connection
from .job_runner import JobRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("worker_daemon")


def main():
    logger.info("Starting Checkout Radar worker daemon...")
    connection.init_db()

    worker_id = os.getenv("WORKER_ID", "daemon_worker_1")
    runner = JobRunner(worker_id=worker_id)

    while True:
        try:
            processed = runner.run_one_cycle()
            if not processed:
                time.sleep(2.0)
        except Exception as e:
            logger.exception(f"Unexpected error in worker loop: {e}")
            time.sleep(5.0)


if __name__ == "__main__":
    main()
