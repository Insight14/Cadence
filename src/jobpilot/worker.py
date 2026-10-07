"""JobPilot background worker orchestrating Gmail polling, Reminder ticks, and Telegram bot."""

import asyncio
import logging
import signal
from types import FrameType

from sqlalchemy import select

from jobpilot.api.main import configure_logging
from jobpilot.bot.app import get_telegram_app
from jobpilot.config import get_settings
from jobpilot.db.models import GmailAccount
from jobpilot.db.session import async_session_factory
from jobpilot.gmail.poller import GmailPoller
from jobpilot.reminders.scheduler import ReminderScheduler

logger = logging.getLogger(__name__)


async def run_gmail_poll_cycle(poller: GmailPoller) -> None:
    """Run one polling pass across all active connected Gmail accounts."""
    try:
        async with await async_session_factory() as session:
            stmt = select(GmailAccount).where(GmailAccount.status == "active")
            accounts = list((await session.scalars(stmt)).all())

            if accounts:
                logger.info("Starting Gmail sync for %d active account(s)", len(accounts))
                for account in accounts:
                    await poller.poll_account(session, account)
    except Exception as exc:
        logger.exception("Error during Gmail polling cycle: %s", exc)


async def run_reminder_tick_cycle(scheduler: ReminderScheduler) -> None:
    """Run one reminder evaluation and notification tick."""
    try:
        async with await async_session_factory() as session:
            await scheduler.run_tick(session)
    except Exception as exc:
        logger.exception("Error during Reminder tick cycle: %s", exc)


async def run_worker() -> None:
    """Main worker entrypoint running concurrent asynchronous loops."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("JobPilot Worker starting in %s mode...", settings.app_env)

    stop_event = asyncio.Event()

    def handle_stop(sig: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s; shutting down worker...", sig)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle_stop)

    # 1. Start Telegram Bot polling if token configured
    bot_app = get_telegram_app()
    bot_running = False
    if settings.telegram_bot_token and settings.telegram_bot_token != "mock":
        try:
            await bot_app.initialize()
            await bot_app.start()
            if bot_app.updater:
                await bot_app.updater.start_polling()
            bot_running = True
            logger.info("Telegram bot polling started successfully.")
        except Exception as exc:
            logger.error("Failed to start Telegram bot polling: %s", exc)

    gmail_poller = GmailPoller()
    reminder_scheduler = ReminderScheduler(bot=bot_app.bot if bot_running else None)

    # Main scheduler loop
    last_gmail_poll = 0.0
    last_reminder_tick = 0.0

    logger.info("Worker loops initialized. Ready to process events.")

    try:
        while not stop_event.is_set():
            loop_now = asyncio.get_event_loop().time()

            # Trigger Gmail poller interval
            if loop_now - last_gmail_poll >= settings.gmail_poll_interval_seconds:
                asyncio.create_task(run_gmail_poll_cycle(gmail_poller))
                last_gmail_poll = loop_now

            # Trigger Reminder tick worker (runs every 60s)
            if loop_now - last_reminder_tick >= settings.reminder_tick_interval_seconds:
                asyncio.create_task(run_reminder_tick_cycle(reminder_scheduler))
                last_reminder_tick = loop_now

            await asyncio.sleep(1)

    finally:
        logger.info("Stopping worker processes...")
        if bot_running:
            if bot_app.updater:
                await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
        logger.info("JobPilot Worker stopped.")


def main() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
