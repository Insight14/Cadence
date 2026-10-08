"""CLI script to seed companies into the database."""

import asyncio
import logging
import sys

from jobpilot.db.session import async_session_factory
from jobpilot.jobs.seed import seed_companies

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    """Run company seeding."""
    logger.info("Connecting to database and seeding companies...")
    async with await async_session_factory() as session:
        inserted, updated = await seed_companies(session)
        logger.info("Successfully seeded companies: %d inserted, %d updated.", inserted, updated)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        logger.exception("Failed to seed companies: %s", exc)
        sys.exit(1)
