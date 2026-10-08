"""Telegram bot application setup and message dispatching."""

import logging
from typing import Any

from telegram import Bot, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
)

from jobpilot.bot.handlers import (
    applications_command,
    delete_my_data_command,
    handle_callback_query,
    lead_command,
    link_command,
    matches_command,
    mute_command,
    pause_command,
    resume_command,
    start_command,
    stats_command,
    threshold_command,
    timezone_command,
    unmute_command,
)
from jobpilot.config import get_settings

logger = logging.getLogger(__name__)

_bot_app: Application[Any, Any, Any, Any, Any, Any] | None = None


def get_telegram_app() -> Application[Any, Any, Any, Any, Any, Any]:
    """Build or return singleton Telegram Application."""
    global _bot_app
    if _bot_app is None:
        settings = get_settings()
        if not settings.telegram_bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not configured.")
        builder = Application.builder().token(settings.telegram_bot_token or "1234567890:mock")
        _bot_app = builder.build()

        # Register commands
        _bot_app.add_handler(CommandHandler("start", start_command))
        _bot_app.add_handler(CommandHandler("link", link_command))
        _bot_app.add_handler(CommandHandler("matches", matches_command))
        _bot_app.add_handler(CommandHandler("applications", applications_command))
        _bot_app.add_handler(CommandHandler("lead", lead_command))
        _bot_app.add_handler(CommandHandler("threshold", threshold_command))
        _bot_app.add_handler(CommandHandler("stats", stats_command))
        _bot_app.add_handler(CommandHandler("mute", mute_command))
        _bot_app.add_handler(CommandHandler("unmute", unmute_command))
        _bot_app.add_handler(CommandHandler("timezone", timezone_command))
        _bot_app.add_handler(CommandHandler("pause", pause_command))
        _bot_app.add_handler(CommandHandler("resume", resume_command))
        _bot_app.add_handler(CommandHandler("delete_my_data", delete_my_data_command))

        # Register callback handler
        _bot_app.add_handler(CallbackQueryHandler(handle_callback_query))

    return _bot_app


async def send_telegram_alert(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int | None:
    """Send a formatted telegram alert message to a user.

    Returns the telegram message ID if successful, or None if failed.
    """
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
        return msg.message_id
    except Forbidden:
        logger.warning("Bot was blocked by user chat %s", chat_id)
        return None
    except TelegramError as exc:
        logger.error("Failed to send telegram message to chat %s: %s", chat_id, exc)
        return None
