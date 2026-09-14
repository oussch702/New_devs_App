import logging
from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)


class DatabasePool:
    def __init__(self):
        self.engine = None
        self.session_factory = None

    async def initialize(self):
        """Create one async-compatible pool for the application's lifetime."""
        if self.engine is not None:
            return

        database_url = make_url(settings.database_url)
        if database_url.get_backend_name() not in {"postgresql", "postgres"}:
            raise ValueError("DATABASE_URL must point to PostgreSQL")
        database_url = database_url.set(drivername="postgresql+asyncpg")
        self.engine = create_async_engine(
            database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
            pool_pre_ping=True,
            pool_recycle=settings.database_pool_recycle,
            connect_args={"timeout": 5, "command_timeout": 30},
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )
        logger.info("Revenue database connection pool initialized")

    async def close(self):
        """Dispose pooled connections and allow a later application restart."""
        if self.engine is not None:
            try:
                await self.engine.dispose()
            finally:
                self.engine = None
                self.session_factory = None

    def get_session(self) -> AsyncSession:
        """Return a session context manager; opening it is not a coroutine."""
        if self.session_factory is None:
            raise RuntimeError("Database pool not initialized")
        return self.session_factory()


db_pool = DatabasePool()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with db_pool.get_session() as session:
        yield session
