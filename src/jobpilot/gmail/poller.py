"""Gmail incremental sync and message processing engine."""

import asyncio
import logging
import uuid
from datetime import datetime

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot.classify.llm_classifier import LLMClassifier
from jobpilot.classify.rules import is_candidate_email
from jobpilot.db.models import Event, GmailAccount, ProcessedEmail, utc_now
from jobpilot.gmail.client import build_gmail_service
from jobpilot.gmail.parser import parse_email_metadata, parse_full_email

logger = logging.getLogger(__name__)


class GmailPoller:
    """Synchronizes new messages for a connected Gmail account using Gmail API."""

    def __init__(self, classifier: LLMClassifier | None = None) -> None:
        self.classifier = classifier or LLMClassifier()

    async def poll_account(
        self,
        session: AsyncSession,
        account: GmailAccount,
    ) -> int:
        """Poll a single GmailAccount for new messages and classify them.

        Returns number of newly processed messages.
        """
        logger.info("Polling Gmail account %s (%s)", account.id, account.google_email)
        try:
            service = build_gmail_service(account.refresh_token_encrypted)
        except Exception as exc:
            logger.error("Failed to build Gmail service for %s: %s", account.id, exc)
            if "invalid_grant" in str(exc).lower():
                account.status = "needs_reauth"
                await session.commit()
            return 0

        processed_count = 0
        try:
            if account.history_id:
                processed_count = await self._sync_history(session, account, service)
            else:
                processed_count = await self._initial_sync(session, account, service)

            account.last_polled_at = utc_now()
            account.status = "active"
            await session.commit()
        except HttpError as http_err:
            status_code = http_err.resp.status
            if status_code == 404:
                logger.warning(
                    "History ID %s expired (404). Falling back to messages.list", account.history_id
                )
                processed_count = await self._fallback_recent_sync(session, account, service)
                account.last_polled_at = utc_now()
                await session.commit()
            elif status_code in (400, 401) and "invalid_grant" in str(http_err).lower():
                logger.warning(
                    "Account %s received invalid_grant. Marking needs_reauth", account.id
                )
                account.status = "needs_reauth"
                await session.commit()
            elif status_code in (429, 500, 502, 503, 504):
                logger.warning(
                    "Rate limit / server error %s while polling %s", status_code, account.id
                )
                await asyncio.sleep(2)
            else:
                logger.error(
                    "Unhandled HTTP error %s for account %s: %s", status_code, account.id, http_err
                )
        except Exception as err:
            logger.exception("Unexpected error while polling account %s: %s", account.id, err)

        return processed_count

    async def _sync_history(
        self,
        session: AsyncSession,
        account: GmailAccount,
        service: Resource,
    ) -> int:
        """Incremental sync using users.history.list."""
        message_ids: set[str] = set()
        page_token: str | None = None
        latest_history_id = account.history_id

        while True:
            history_response = (
                service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=account.history_id,
                    historyTypes=["messageAdded"],
                    pageToken=page_token,
                )
                .execute()
            )

            histories = history_response.get("history", [])
            for h in histories:
                for msg_added in h.get("messagesAdded", []):
                    msg = msg_added.get("message", {})
                    if msg.get("id"):
                        message_ids.add(msg["id"])

            latest_history_id = history_response.get("historyId", latest_history_id)
            page_token = history_response.get("nextPageToken")
            if not page_token:
                break

        count = 0
        for msg_id in message_ids:
            if await self._process_single_message(session, account.user_id, service, msg_id):
                count += 1

        account.history_id = str(latest_history_id)
        return count

    async def _fallback_recent_sync(
        self,
        session: AsyncSession,
        account: GmailAccount,
        service: Resource,
    ) -> int:
        """Fallback to querying messages within the last 7 days when historyId expires."""
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q="newer_than:7d",
                maxResults=100,
            )
            .execute()
        )

        messages = response.get("messages", [])
        count = 0
        for msg in messages:
            msg_id = msg.get("id")
            if msg_id:
                if await self._process_single_message(session, account.user_id, service, msg_id):
                    count += 1

        profile = service.users().getProfile(userId="me").execute()
        account.history_id = str(profile.get("historyId", ""))
        return count

    async def _initial_sync(
        self,
        session: AsyncSession,
        account: GmailAccount,
        service: Resource,
    ) -> int:
        """Perform initial sync and record current profile historyId."""
        profile = service.users().getProfile(userId="me").execute()
        account.history_id = str(profile.get("historyId", ""))
        return await self._fallback_recent_sync(session, account, service)

    async def _process_single_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        service: Resource,
        gmail_message_id: str,
    ) -> bool:
        """Fetch, classify, and persist a single message idempotently."""
        # 1. Check if already processed
        stmt = select(ProcessedEmail.id).where(
            ProcessedEmail.user_id == user_id,
            ProcessedEmail.gmail_message_id == gmail_message_id,
        )
        existing = await session.scalar(stmt)
        if existing:
            return False

        # 2. Stage 1: Fetch metadata headers first
        meta_dict = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=gmail_message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )

        parsed_meta = parse_email_metadata(meta_dict)

        # Evaluate Stage 1 rules
        passes_stage1 = is_candidate_email(
            sender_domain=parsed_meta.sender_domain,
            subject=parsed_meta.subject,
            snippet=parsed_meta.snippet,
        )

        if not passes_stage1:
            # Mark as 'other' without invoking LLM
            await self._persist_email_record(
                session=session,
                user_id=user_id,
                message_id=gmail_message_id,
                thread_id=parsed_meta.thread_id,
                sender_domain=parsed_meta.sender_domain,
                received_at=parsed_meta.received_at,
                label="other",
                confidence=1.0,
            )
            return True

        # 3. Stage 2: Fetch full message body
        full_dict = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=gmail_message_id,
                format="full",
            )
            .execute()
        )

        parsed_full = parse_full_email(full_dict)

        classification = await self.classifier.classify(
            sender_domain=parsed_full.sender_domain,
            subject=parsed_full.subject,
            body_snippet=parsed_full.body_text,
            received_at=parsed_full.received_at,
        )

        # 4. Idempotently persist ProcessedEmail
        proc_email = await self._persist_email_record(
            session=session,
            user_id=user_id,
            message_id=gmail_message_id,
            thread_id=parsed_full.thread_id,
            sender_domain=parsed_full.sender_domain,
            received_at=parsed_full.received_at,
            label=classification.label,
            confidence=classification.confidence,
        )

        # 5. If OA or Interview, create Event row
        if classification.label in ("oa", "interview"):
            company_name = classification.company or parsed_full.sender_domain or "Unknown Company"
            event = Event(
                user_id=user_id,
                processed_email_id=proc_email.id,
                kind=classification.label,
                company=company_name,
                role_title=classification.role_title,
                platform=classification.platform,
                deadline_at=(
                    classification.deadline_iso
                    if isinstance(classification.deadline_iso, datetime)
                    else None
                ),
                link=classification.link,
                status="active",
            )
            session.add(event)
            await session.flush()
            logger.info(
                "Created %s event for user %s (company: %s, platform: %s)",
                classification.label,
                user_id,
                company_name,
                classification.platform,
            )

        return True

    async def _persist_email_record(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        message_id: str,
        thread_id: str | None,
        sender_domain: str | None,
        received_at: datetime,
        label: str,
        confidence: float | None,
    ) -> ProcessedEmail:
        """Insert or retrieve ProcessedEmail row."""
        proc_email = ProcessedEmail(
            user_id=user_id,
            gmail_message_id=message_id,
            thread_id=thread_id,
            sender_domain=sender_domain,
            received_at=received_at,
            label=label,
            confidence=confidence,
        )
        session.add(proc_email)
        await session.flush()
        return proc_email
