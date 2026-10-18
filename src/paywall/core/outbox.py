"""Transactional outbox: events are written in the same transaction as the change they describe.

If the transaction rolls back, the event never existed; if it commits, the event is guaranteed to
be delivered later (at least once), even if the process crashes right after the commit.
"""

from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from paywall.db.models import OutboxEvent
from paywall.observability import request_id_var


async def emit(session: AsyncSession, event_type: str, payload: dict[str, Any]) -> None:
    await session.execute(
        insert(OutboxEvent).values(
            event_type=event_type, payload=payload, request_id=request_id_var.get()
        )
    )
