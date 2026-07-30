"""Database-backed authentication replay claims for local service processes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import AuthReplayClaimRecord


class DatabaseReplayStore:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        retention: timedelta = timedelta(hours=1),
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._retention = retention

    async def claim(
        self,
        *,
        authenticator_id: str,
        nonce_hash: str,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> bool:
        now = self._clock()
        try:
            async with self._sessions() as session, session.begin():
                session.add(
                    AuthReplayClaimRecord(
                        id=str(uuid4()),
                        authenticator_id=authenticator_id,
                        nonce_hash=bytes.fromhex(nonce_hash),
                        request_fingerprint=bytes.fromhex(request_fingerprint),
                        created_at=now,
                        expires_at=expires_at,
                        retention_until=expires_at + self._retention,
                    )
                )
                await session.flush()
            return True
        except (IntegrityError, ValueError):
            return False
