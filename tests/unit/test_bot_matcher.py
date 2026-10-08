from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jobpilot.bot.handlers import (
    handle_callback_query,
    matches_command,
    mute_command,
    unmute_command,
)
from jobpilot.db.models import Company, JobPosting, ResumeProfile, User, UserCompanyPref
from jobpilot.embeddings.client import FakeEmbeddingsClient


def make_update(
    chat_id: int = 12345,
    user_id: int = 12345,
    text: str = "",
    callback_data: str | None = None,
) -> tuple[Any, Any]:
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user.id = user_id

    if callback_data:
        cbq = MagicMock()
        cbq.data = callback_data
        cbq.message = MagicMock()
        cbq.message.text = "Original alert text"
        cbq.answer = AsyncMock()
        cbq.edit_message_text = AsyncMock()
        cbq.edit_message_reply_markup = AsyncMock()
        update.callback_query = cbq
        update.message = None
    else:
        msg = MagicMock()
        msg.text = text
        msg.reply_text = AsyncMock()
        update.message = msg
        update.callback_query = None

    context = MagicMock()
    context.args = []
    return update, context


@pytest.mark.asyncio
async def test_bot_mute_and_unmute_commands(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory
    chat_id = 987654321

    async with session_maker() as session:
        user = User(email="test@user.com", telegram_chat_id=chat_id)
        comp = Company(name="Acme AI", ats="greenhouse", board_token="acme")
        session.add_all([user, comp])
        await session.commit()
        user_id = user.id
        comp_id = comp.id

    # 1. /mute Acme AI
    upd, ctx = make_update(chat_id=chat_id, text="/mute Acme AI")
    ctx.args = ["Acme", "AI"]
    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await mute_command(upd, ctx)

    upd.message.reply_text.assert_awaited_once()
    assert "Muted Acme AI" in upd.message.reply_text.call_args[0][0]

    # Check DB pref
    async with session_maker() as session:
        pref = await session.scalar(
            select(UserCompanyPref).where(
                UserCompanyPref.user_id == user_id,
                UserCompanyPref.company_id == comp_id,
            )
        )
        assert pref is not None
        assert pref.status == "muted"

    # 2. /unmute Acme AI
    upd2, ctx2 = make_update(chat_id=chat_id, text="/unmute Acme AI")
    ctx2.args = ["Acme", "AI"]
    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await unmute_command(upd2, ctx2)

    upd2.message.reply_text.assert_awaited_once()
    assert "Unmuted Acme AI" in upd2.message.reply_text.call_args[0][0]

    async with session_maker() as session:
        pref_after = await session.scalar(
            select(UserCompanyPref).where(
                UserCompanyPref.user_id == user_id,
                UserCompanyPref.company_id == comp_id,
            )
        )
        assert pref_after is not None
        assert pref_after.status == "watch"


@pytest.mark.asyncio
async def test_bot_mute_callback_query(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory
    chat_id = 987654321

    async with session_maker() as session:
        user = User(email="test@user.com", telegram_chat_id=chat_id)
        comp = Company(name="Scale Tech", ats="ashby", board_token="scaletech")
        session.add_all([user, comp])
        await session.commit()
        comp_id = comp.id

    upd, ctx = make_update(chat_id=chat_id, callback_data=f"mute:{comp_id}")
    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await handle_callback_query(upd, ctx)

    upd.callback_query.answer.assert_awaited_once()
    upd.callback_query.edit_message_text.assert_awaited_once()
    assert "Muted Scale Tech" in upd.callback_query.edit_message_text.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_bot_matches_command(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory
    chat_id = 555666777

    embedder = FakeEmbeddingsClient(dimension=64)
    vec = await embedder.embed_text("Machine Learning Engineer")

    async with session_maker() as session:
        user = User(email="ml_grad@stanford.edu", telegram_chat_id=chat_id)
        session.add(user)
        await session.flush()

        prof = ResumeProfile(
            user_id=user.id,
            structured_json={"skills": ["PyTorch"], "domains": ["Machine Learning"]},
            embedding=vec,
        )
        comp = Company(name="DeepMind", ats="greenhouse", board_token="deepmind")
        session.add_all([prof, comp])
        await session.flush()

        job = JobPosting(
            company_id=comp.id,
            external_id="dm-1",
            title="Research Scientist Intern",
            url="https://deepmind.google/jobs/1",
            is_open=True,
            embedding=vec,
        )
        session.add(job)
        await session.commit()

    upd, ctx = make_update(chat_id=chat_id, text="/matches")
    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await matches_command(upd, ctx)

    upd.message.reply_text.assert_awaited_once()
    assert "Top Open Job Matches" in upd.message.reply_text.call_args[0][0]
    assert "DeepMind" in upd.message.reply_text.call_args[0][0]
