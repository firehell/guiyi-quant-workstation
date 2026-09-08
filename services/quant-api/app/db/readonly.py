"""A fresh bounded read-only transaction shared by local diagnostic consumers."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session


class ReadOnlyTransactionError(ValueError):
    code = "READ_ONLY_TRANSACTION_INVALID"


@contextmanager
def readonly_transaction(
    session: Session, *, timeout_seconds: int = 300
) -> Iterator[Session]:
    """Require a fresh clean session, forbid autoflush/writes, always rollback."""
    if (
        type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= 3600
        or session.in_transaction()
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise ReadOnlyTransactionError
    try:
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": str(timeout_seconds * 1000)},
            )
            if session.scalar(text("SHOW transaction_read_only")) != "on":
                raise ReadOnlyTransactionError
        elif dialect == "sqlite":
            session.execute(text("PRAGMA query_only = ON"))
            if session.scalar(text("PRAGMA query_only")) != 1:
                raise ReadOnlyTransactionError
        else:
            raise ReadOnlyTransactionError
        with session.no_autoflush:
            yield session
            if session.new or session.dirty or session.deleted:
                raise ReadOnlyTransactionError
    finally:
        session.rollback()
