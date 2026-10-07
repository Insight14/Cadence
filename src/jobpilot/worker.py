"""JobPilot background worker entrypoint."""

import asyncio
import logging
import signal
from types import FrameType

from jobpilot.api.main import configure_logging
from jobpilot.config import get_settings

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    """Main worker event loop."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("JobPilot worker starting up in %s mode...", settings.app_env)

    stop_event = asyncio.Event()

    def handle_stop(sig: int, _frame: FrameType | None) -> None:
        logger.info("Received termination signal %s, initiating graceful shutdown...", sig)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle_stop)

    logger.info("Worker initialized. Ready to process scheduled tasks.")
    # Keep worker running until stop signal
    while not stop_event.is_set():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            break

    logger.info("Worker gracefully stopped.")


def main() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker terminated.")


if __name__ == "__main__":
    main()
