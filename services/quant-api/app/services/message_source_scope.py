"""Cheap API snapshot identity proof using the existing forward message scope."""

from sqlalchemy import select
from app.db.readonly import readonly_transaction
from app.reference_trading.models import ReferenceRevision, ReferenceStream
from app.reference_trading.messages import FREQUENCIES, STRATEGIES
from app.reference_trading.query import QueryConflict


def _scope_statement(product=None, strategy=None, frequency=None):
    scope_statement = (
        select(
            ReferenceStream.stream_id,
            ReferenceStream.active_revision_id,
            ReferenceStream.health,
            ReferenceRevision.status,
        )
        .select_from(ReferenceStream)
        .outerjoin(
            ReferenceRevision,
            (ReferenceRevision.stream_id == ReferenceStream.stream_id)
            & (ReferenceRevision.revision_id == ReferenceStream.active_revision_id),
        )
        .where(
            ReferenceStream.recording_mode == "forward_observation",
            ReferenceStream.strategy_code.in_([f"newow_{s}" for s in STRATEGIES]),
            ReferenceStream.frequency.in_(FREQUENCIES),
        )
    )
    if product:
        scope_statement = scope_statement.where(
            ReferenceStream.product == product.lower()
        )
    if strategy:
        scope_statement = scope_statement.where(
            ReferenceStream.strategy_code == f"newow_{strategy}"
        )
    if frequency:
        scope_statement = scope_statement.where(ReferenceStream.frequency == frequency)
    return scope_statement


def read_message_scope(factory, *, product=None, strategy=None, frequency=None):
    """Read only active source identities, without scanning calculation batches."""
    with factory() as session, readonly_transaction(session, timeout_seconds=20):
        rows = session.execute(
            _scope_statement(product, strategy, frequency).limit(10001)
        ).all()
        if len(rows) > 10000:
            raise QueryConflict("QUERY_BUDGET_EXCEEDED")
        return sorted(tuple(row) for row in rows)
