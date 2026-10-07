"""Telegram bot command handlers and interactive callback query dispatchers."""

import datetime
import logging
import uuid

import httpx
from sqlalchemy import delete, select
from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from jobpilot.db.models import Event, GmailAccount, Reminder, User
from jobpilot.db.session import async_session_factory
from jobpilot.reminders.schedule_math import (
    calculate_next_fire_slot,
    get_user_zone,
    validate_timezone,
)
from jobpilot.security.crypto import decrypt_token

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command, optionally with a linking token."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []

    async with await async_session_factory() as db:
        # Check if already linked
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)

        if args:
            token = args[0].strip()
            # Attempt to link user by user UUID or token
            linked_user = None
            try:
                user_id = uuid.UUID(token)
                linked_user = await db.get(User, user_id)
            except ValueError:
                pass

            if not linked_user:
                # Try finding by email
                stmt_email = select(User).where(User.email == token)
                linked_user = await db.scalar(stmt_email)

            if linked_user:
                linked_user.telegram_chat_id = chat_id
                await db.commit()
                await update.message.reply_text(
                    f"✅ **Account linked successfully!**\n\n"
                    f"👤 **Email:** `{linked_user.email or 'Connected'}`\n"
                    f"🕒 **Timezone:** `{linked_user.timezone}`\n"
                    f"(change with `/timezone <IANA>`)\n\n"
                    f"You will now receive instant notifications when new Online Assessments "
                    f"or interviews are detected.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

        if user:
            await update.message.reply_text(
                f"👋 **Welcome back to JobPilot!**\n\n"
                f"Your Telegram is linked to `{user.email or 'your account'}`.\n"
                f"🕒 Current timezone: `{user.timezone}`\n\n"
                f"**Available Commands:**\n"
                f"• `/timezone <IANA>` — Update your timezone (e.g. `America/New_York`)\n"
                f"• `/pause` — Temporarily pause reminder notifications\n"
                f"• `/resume` — Resume reminders\n"
                f"• `/delete_my_data` — Wipe all your data and revoke Google permissions",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "👋 **Welcome to JobPilot!**\n\n"
                "To link your Telegram account to JobPilot:\n"
                "1. Connect your Gmail at `http://localhost:8000`\n"
                "2. Send `/link <your_user_id_or_email>` here in chat.\n\n"
                "Once linked, you'll receive interactive OA reminders and interview alerts!",
                parse_mode=ParseMode.MARKDOWN,
            )


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /link <token_or_email> command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/link <user_id_or_email>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    token = args[0].strip()
    async with await async_session_factory() as db:
        user = None
        try:
            user_id = uuid.UUID(token)
            user = await db.get(User, user_id)
        except ValueError:
            pass

        if not user:
            stmt = select(User).where(User.email == token)
            user = await db.scalar(stmt)

        if not user:
            await update.message.reply_text(
                "❌ No user found matching that ID or email. Please check and try again."
            )
            return

        user.telegram_chat_id = chat_id
        await db.commit()
        await update.message.reply_text(
            f"✅ **Telegram linked successfully!**\n\n"
            f"👤 **Account:** `{user.email or user.id}`\n"
            f"🕒 **Timezone:** `{user.timezone}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /timezone <IANA_STRING> command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/timezone <IANA_TIMEZONE>`\n"
            "Example: `/timezone America/New_York` or `/timezone America/Los_Angeles`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    tz_input = args[0].strip()
    if not validate_timezone(tz_input):
        await update.message.reply_text(
            f"❌ `{tz_input}` is not a recognized IANA timezone.\n"
            "Please use standard names like `America/New_York`, `America/Chicago`, "
            "`America/Los_Angeles`, `Europe/London`, etc.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    async with await async_session_factory() as db:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)
        if not user:
            await update.message.reply_text(
                "❌ Your Telegram is not yet linked. Use `/link <user_id>` first."
            )
            return

        user.timezone = tz_input
        await db.commit()
        await update.message.reply_text(
            f"✅ **Timezone updated to:** `{tz_input}`\n"
            f"Reminders will now fire at 10:00 and 19:00 in `{tz_input}`.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pause command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    async with await async_session_factory() as db:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)
        if not user:
            await update.message.reply_text("❌ Account not linked.")
            return

        user.paused = True
        await db.commit()
        await update.message.reply_text(
            "⏸️ **Reminders paused.** Send `/resume` whenever you're ready to restart."
        )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    async with await async_session_factory() as db:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)
        if not user:
            await update.message.reply_text("❌ Account not linked.")
            return

        user.paused = False
        await db.commit()
        await update.message.reply_text(
            "▶️ **Reminders resumed!** You will receive scheduled reminders as usual."
        )


async def delete_my_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete_my_data command (privacy-minimal wipe and token revocation)."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    async with await async_session_factory() as db:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)
        if not user:
            await update.message.reply_text("No linked account found.")
            return

        # Fetch Gmail accounts to revoke refresh tokens
        acc_stmt = select(GmailAccount).where(GmailAccount.user_id == user.id)
        accounts = list((await db.scalars(acc_stmt)).all())

        for acc in accounts:
            try:
                plain_token = decrypt_token(acc.refresh_token_encrypted)
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": plain_token},
                        timeout=5.0,
                    )
            except Exception as exc:
                logger.warning("Failed to revoke Google token during delete_my_data: %s", exc)

        # Delete user (CASCADE deletes all related rows in all tables via DB foreign keys)
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()

        await update.message.reply_text(
            "🗑️ **All your data has been permanently deleted.**\n\n"
            "• All database records and history removed.\n"
            "• Google OAuth access tokens revoked.\n"
            "Thank you for using JobPilot!",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button callbacks (recur:<id>, dismiss:<id>, done:<id>)."""
    query = update.callback_query
    if not query or not query.data or not update.effective_chat:
        return

    await query.answer()
    chat_id = update.effective_chat.id
    action, _, reminder_id_str = query.data.partition(":")

    try:
        reminder_id = uuid.UUID(reminder_id_str)
    except ValueError:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    now = datetime.datetime.now(datetime.UTC)
    async with await async_session_factory() as db:
        # Load reminder with user and event
        stmt = select(Reminder).where(Reminder.id == reminder_id)
        reminder = await db.scalar(stmt)

        if not reminder:
            await query.edit_message_reply_markup(reply_markup=None)
            return

        user = await db.get(User, reminder.user_id)
        if not user or user.telegram_chat_id != chat_id:
            # Authorization check failed: user clicking button does not own the reminder
            logger.warning(
                "Unauthorized callback attempt by chat %s for reminder %s",
                chat_id,
                reminder_id,
            )
            return

        event = await db.get(Event, reminder.event_id)

        orig_text = (
            query.message.text if isinstance(query.message, Message) and query.message.text else ""
        )

        if action == "recur":
            reminder.state = "recurring"
            next_fire = calculate_next_fire_slot(now, user.timezone)
            reminder.next_fire_at = next_fire
            user_tz = get_user_zone(user.timezone)
            local_fire = next_fire.astimezone(user_tz)
            await db.commit()

            await query.edit_message_text(
                text=(
                    f"{orig_text}\n\n"
                    f"🔁 **Recurring active!** Next reminder: "
                    f"**{local_fire.strftime('%b %d at %I:%M %p')}**"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )

        elif action == "dismiss":
            reminder.state = "dismissed"
            if event:
                event.status = "dismissed"
            await db.commit()

            await query.edit_message_text(
                text=f"{orig_text}\n\n✖ **Reminder dismissed.**",
                parse_mode=ParseMode.MARKDOWN,
            )

        elif action == "done":
            reminder.state = "done"
            if event:
                event.status = "completed"
            await db.commit()

            await query.edit_message_text(
                text=f"{orig_text}\n\n🎉 **Great job! Marked as completed.**",
                parse_mode=ParseMode.MARKDOWN,
            )
