from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.reference_trading.subing_activation import plan_subing_activation, apply_subing_activation
from app.reference_trading.models import ReferenceStream, ReferenceBatch
from app.reference_trading.repository import RepositoryConflict

from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401

NOW = datetime(2026, 10, 26, 8, tzinfo=UTC)

@pytest.mark.parametrize('backend', ['sqlite', pytest.param('postgresql', marks=pytest.mark.isolated_postgresql)])
@pytest.mark.parametrize('period', ['5m','15m','30m','60m','1d','1w'])
def test_six_period_activation_is_atomic_flat_and_exact(period, backend, request):
    engine = request.getfixturevalue("reference_postgresql") if backend == "postgresql" else create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    plan = plan_subing_activation('rb',period,operational={'rb'},start=NOW+timedelta(minutes=2),
        expiry=NOW+timedelta(minutes=1),now=NOW,host='local',environment='isolated')
    result = apply_subing_activation(factory,plan,expected_plan_hash=plan['plan_hash'],operational={'rb'},now=NOW)
    with factory() as s:
        row = s.get(ReferenceStream,result['stream_id'])
        assert row.enabled and row.observation_policy_version == 'subing_physical_prefix_forward_v2'
        assert row.latest_seq == 1
        assert s.scalar(select(func.count()).select_from(ReferenceBatch).where(ReferenceBatch.kind == 'seed_seal')) == 1
        assert s.scalar(select(func.count()).select_from(ReferenceBatch).where(ReferenceBatch.kind == 'capture')) == 0
    with pytest.raises(RepositoryConflict,match='ALREADY_EXISTS'):
        apply_subing_activation(factory,plan,expected_plan_hash=plan['plan_hash'],operational={'rb'},now=NOW)
    with pytest.raises(RepositoryConflict,match='PLAN_HASH_CONFLICT'):
        apply_subing_activation(factory,plan,expected_plan_hash='0'*64,operational={'rb'},now=NOW)
