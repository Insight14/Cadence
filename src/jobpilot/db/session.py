"""Database session and engine management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from jobpilot.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return or create singleton async engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=(settings.log_level.upper() == "DEBUG"),
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            connect_args={
                "prepared_statement_cache_size": 0,
                "statement_cache_size": 0,
            },
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return or create singleton async sessionmaker."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def async_session_factory() -> AsyncSession:
    """Instantiate a new AsyncSession."""
    factory = get_session_factory()
    return factory()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for obtaining an async db session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
