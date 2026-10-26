"""Real PostgreSQL startup proof for original flat seeds, with no runtime writes."""

import pytest
from sqlalchemy import event, select

from app.reference_trading import worker_entry
from app.reference_trading.models import (
    ReferenceActivationReceipt, ReferenceBatch, ReferenceRevision, ReferenceStream,
)
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401
from tests.reference_trading.test_worker_entry import _initialized_route, _never_evaluate_initialization


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("frequency", ("5m", "15m", "30m", "60m", "1d", "1w"))
def test_original_flat_seed_warmup_uses_read_only_snapshot_and_changes_no_facts(reference_postgresql, frequency):  # noqa: F811
    factory, repository, result = _initialized_route(reference_postgresql, frequency)
    tables = (ReferenceStream, ReferenceRevision, ReferenceBatch, ReferenceActivationReceipt)
    def snapshot():
        with factory() as session:
            return [[dict(row) for row in session.execute(select(model.__table__)).mappings()] for model in tables]
    before = snapshot()
    statements = []
    def observe(connection, _cursor, statement, _parameters, _context, _many):
        statements.append((statement, connection.get_execution_options().get("isolation_level")))
    event.listen(reference_postgresql, "before_cursor_execute", observe)
    try:
        assert worker_entry._warmup_saved_capture(repository, result["stream_id"],
            _never_evaluate_initialization()) == "initialized"
    finally:
        event.remove(reference_postgresql, "before_cursor_execute", observe)
    assert snapshot() == before
    assert any(statement == "SET TRANSACTION READ ONLY" for statement, _ in statements)
    assert all(isolation == "REPEATABLE READ" for _, isolation in statements)
    assert not any(statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE "))
        for statement, _ in statements)
