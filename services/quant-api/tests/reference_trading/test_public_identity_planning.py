"""Large identity reads keep planning bounded without relaxing corruption checks."""
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.db.readonly import readonly_transaction
from app.reference_trading.contracts import SnapshotIdentity
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401


class MissingActionsSession:
    def __init__(self, dialect):
        self.dialect = dialect
        self.statements = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))

    def execute(self, statement):
        self.statements.append(str(statement))
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))


def missing_trades(count):
    return [SimpleNamespace(entry_action_id=f'missing-{i}', exit_action_id=None) for i in range(count)]


@pytest.mark.parametrize('dialect,count,custom', [('postgresql', 1001, True), ('postgresql', 200, False), ('sqlite', 1001, False)])
def test_large_missing_identity_still_fails_closed(dialect, count, custom):
    session = MissingActionsSession(dialect)
    with pytest.raises(QueryConflict, match='TRADE_ACTION_CORRUPT'):
        HistoricalReferenceQuery._public_trade_ids(session, SnapshotIdentity('stream', 'revision', 1), missing_trades(count))
    assert any('SET LOCAL plan_cache_mode = force_custom_plan' in value for value in session.statements) is custom
    assert not any('UPDATE ' in value or 'INSERT ' in value or 'DELETE ' in value for value in session.statements)


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("propagate", [False, True])
def test_custom_plan_choice_ends_with_readonly_transaction(reference_postgresql, propagate):  # noqa: F811
    from sqlalchemy.orm import Session
    # Only the isolated fixture owns DDL; this query writes no rows or global config.
    with Session(reference_postgresql) as session:
        with readonly_transaction(session):
            before = session.scalar(text('SHOW plan_cache_mode'))
        if propagate:
            with pytest.raises(QueryConflict, match='TRADE_ACTION_CORRUPT'):
                with readonly_transaction(session):
                    HistoricalReferenceQuery._public_trade_ids(session, SnapshotIdentity('missing', 'missing', 1), missing_trades(1001))
        else:
            with readonly_transaction(session):
                with pytest.raises(QueryConflict, match='TRADE_ACTION_CORRUPT'):
                    HistoricalReferenceQuery._public_trade_ids(session, SnapshotIdentity('missing', 'missing', 1), missing_trades(1001))
                assert session.scalar(text('SHOW plan_cache_mode')) == 'force_custom_plan'
        with readonly_transaction(session):
            assert session.scalar(text('SHOW plan_cache_mode')) == before
