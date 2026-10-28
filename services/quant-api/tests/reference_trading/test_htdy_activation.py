from datetime import UTC, datetime, timedelta
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.htdy_activation import (
    ACCEPTANCE_ID, MODEL_VERSION, POLICY, apply_htdy_activation,
    htdy_identity, plan_htdy_activation, readback_htdy_activation,
    plan_operational_htdy_activation, apply_operational_htdy_activation,
)
from app.reference_trading.models import (
    ReferenceActionRow, ReferenceActivationReceipt, ReferenceBatch,
    ReferenceRevision, ReferenceStream,
)
from app.reference_trading.repository import RepositoryConflict
from app.reference_trading.repository import ReferenceRepository
from guiyi_quant.reference_trading import ReferenceState
from guiyi_quant.reference_trading.htdy import HtdyForwardState
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json

from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401

NOW = datetime(2026, 10, 28, 8, tzinfo=UTC)


@pytest.fixture(params=["sqlite", pytest.param("postgresql", marks=pytest.mark.isolated_postgresql)])
def factory(request):
    engine = (request.getfixturevalue("reference_postgresql") if request.param == "postgresql"
              else create_engine("sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def _plan(products=("rb", "cu"), *, start=NOW + timedelta(minutes=2)):
    return plan_htdy_activation(
        operational=products, recording_start=start, expires_at=NOW + timedelta(minutes=1),
        now=NOW, host="isolated-host", environment="isolated")


def _count(factory, model):
    with factory() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_scope_activation_is_atomic_flat_and_readback_exact(factory):
    plan = _plan()
    result = apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                                   operational={"rb", "cu"}, now=NOW)
    assert result["acceptance_id"] == ACCEPTANCE_ID
    assert len(result["routes"]) == 2
    assert readback_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                                    operational={"rb", "cu"}) == result
    with factory() as session:
        for product in ("rb", "cu"):
            identity = htdy_identity(product)
            stream = session.get(ReferenceStream, identity.stream_id)
            assert stream.enabled and stream.latest_seq == 1 and stream.activation_generation == 1
            assert stream.reference_model_version == MODEL_VERSION
            assert stream.observation_policy_version == POLICY
            revision = session.get(ReferenceRevision, (identity.stream_id, stream.active_revision_id))
            batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            checkpoint = adapter_checkpoint_from_json(batch.checkpoint_text,
                expected_stream=identity, expected_strategy_schema="htdy_first_seen_v1")
            assert checkpoint.strategy_state == HtdyForwardState(MODEL_VERSION, POLICY)
            assert checkpoint.reference_state == ReferenceState.flat(identity,
                recording_start=NOW + timedelta(minutes=2))
            assert checkpoint.computed_through is None
            assert batch.dependency_manifest["scope_plan_hash"] == plan["plan_hash"]
            assert session.scalar(select(func.count()).select_from(ReferenceActionRow)) == 0
            assert session.scalar(select(func.count()).select_from(ReferenceBatch).where(
                ReferenceBatch.kind == "capture")) == 0
    assert _count(factory, ReferenceActivationReceipt) == 2
    with pytest.raises(RepositoryConflict, match="ALREADY_EXISTS_READBACK_REQUIRED"):
        apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)


def test_second_route_failure_rolls_back_entire_scope(factory, monkeypatch):
    plan = _plan()
    original = ForwardActivation.apply
    calls = 0

    def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RepositoryConflict("INJECTED_SECOND_ROUTE")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ForwardActivation, "apply", fail_second)
    with pytest.raises(RepositoryConflict, match="INJECTED_SECOND_ROUTE"):
        apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)
    for model in (ReferenceStream, ReferenceRevision, ReferenceBatch, ReferenceActivationReceipt):
        assert _count(factory, model) == 0


def test_hash_scope_and_expiry_drift_fail_closed(factory):
    plan = _plan()
    with pytest.raises(RepositoryConflict, match="PLAN_HASH_CONFLICT"):
        apply_htdy_activation(factory, plan, expected_plan_hash="0" * 64,
                              operational={"rb", "cu"}, now=NOW)
    with pytest.raises(RepositoryConflict, match="SCOPE_DRIFT"):
        apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                              operational={"rb"}, now=NOW)
    with pytest.raises(RepositoryConflict, match="PLAN_EXPIRED"):
        apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                              operational={"rb", "cu"}, now=NOW + timedelta(minutes=1, seconds=1))
    changed = {**plan, "host": "other-host"}
    with pytest.raises(RepositoryConflict, match="PLAN_HASH_CONFLICT"):
        apply_htdy_activation(factory, changed, expected_plan_hash=plan["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)
    for model in (ReferenceStream, ReferenceRevision, ReferenceBatch, ReferenceActivationReceipt):
        assert _count(factory, model) == 0


def test_lock_wait_past_expiry_rolls_back_without_seed(factory, monkeypatch):
    from app.reference_trading import htdy_activation

    plan = _plan()
    times = iter((0.0, 0.0, 90.0))  # entry, preflight, acquired lock
    monkeypatch.setattr(htdy_activation, "monotonic", lambda: next(times))
    with pytest.raises(RepositoryConflict, match="PLAN_EXPIRED"):
        apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)
    for model in (ReferenceStream, ReferenceRevision, ReferenceBatch, ReferenceActivationReceipt):
        assert _count(factory, model) == 0


@pytest.mark.parametrize("advance_after", [1, 2])
def test_elapsed_deadline_rolls_back_every_route(factory, monkeypatch, advance_after):
    from app.reference_trading import htdy_activation

    plan = _plan()
    clock = {"elapsed": 0.0}
    monkeypatch.setattr(htdy_activation, "monotonic", lambda: clock["elapsed"])
    original = ForwardActivation.apply
    calls = 0

    def advance_after_first(self, *args, **kwargs):
        nonlocal calls
        result = original(self, *args, **kwargs)
        calls += 1
        if calls == advance_after:
            clock["elapsed"] = 90.0
        return result

    monkeypatch.setattr(ForwardActivation, "apply", advance_after_first)
    with pytest.raises(RepositoryConflict, match="PLAN_EXPIRED"):
        apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)
    for model in (ReferenceStream, ReferenceRevision, ReferenceBatch, ReferenceActivationReceipt):
        assert _count(factory, model) == 0


def test_plan_requires_ten_second_commit_margin():
    with pytest.raises(ValueError, match="PLAN_INVALID"):
        _plan(start=NOW + timedelta(minutes=1, seconds=5))


def test_wrong_frequency_model_and_scope_size_rejected(factory):
    with pytest.raises(ValueError, match="SCOPE_INVALID"):
        _plan(tuple(f"p{n}" for n in range(61)))
    with pytest.raises(ValueError, match="SCOPE_INVALID"):
        _plan(("rb", "RB"))
    with pytest.raises(ValueError, match="NOT_60"):
        plan_operational_htdy_activation(
            operational={"rb", "cu"}, recording_start=NOW + timedelta(minutes=2),
            expires_at=NOW + timedelta(minutes=1), now=NOW,
            host="isolated-host", environment="isolated")
    plan = _plan()
    with pytest.raises(RepositoryConflict, match="NOT_60"):
        apply_operational_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                                          operational={"rb", "cu"}, now=NOW)
    malformed = {**plan, "stream_ids": ["other", *plan["stream_ids"][1:]]}
    malformed["plan_hash"] = manifest_sha256({k: v for k, v in malformed.items() if k != "plan_hash"})
    with pytest.raises(RepositoryConflict, match="SCOPE_DRIFT"):
        apply_htdy_activation(factory, malformed, expected_plan_hash=malformed["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)
    malformed = {**plan, "frequency": "15m"}
    malformed["plan_hash"] = manifest_sha256({k: v for k, v in malformed.items() if k != "plan_hash"})
    with pytest.raises(RepositoryConflict, match="SCOPE_DRIFT"):
        apply_htdy_activation(factory, malformed, expected_plan_hash=malformed["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)
    malformed = {**plan, "reference_model_version": "unapproved"}
    malformed["plan_hash"] = manifest_sha256({k: v for k, v in malformed.items() if k != "plan_hash"})
    with pytest.raises(RepositoryConflict, match="SCOPE_DRIFT"):
        apply_htdy_activation(factory, malformed, expected_plan_hash=malformed["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)
    malformed = {**plan, "version": "other"}
    malformed["plan_hash"] = manifest_sha256({k: v for k, v in malformed.items() if k != "plan_hash"})
    with pytest.raises(RepositoryConflict, match="SCOPE_DRIFT"):
        apply_htdy_activation(factory, malformed, expected_plan_hash=malformed["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)
    assert _count(factory, ReferenceStream) == 0


def test_existing_enabled_same_family_different_identity_blocks_scope(factory):
    alternative = replace(htdy_identity("rb"), observation_policy_version="prior_policy_v1")
    repository = ReferenceRepository(factory)
    repository.ensure_stream(alternative)
    with factory() as session, session.begin():
        row = session.get(ReferenceStream, alternative.stream_id)
        row.enabled = True
    plan = _plan()
    with pytest.raises(RepositoryConflict, match="DUPLICATE_ROUTE"):
        apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                              operational={"rb", "cu"}, now=NOW)
    assert _count(factory, ReferenceStream) == 1
    assert _count(factory, ReferenceActivationReceipt) == 0


def test_complete_sixty_route_scope_starts_in_future_without_capture():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    products = tuple(chr(97 + first) + chr(97 + second)
                     for first in range(3) for second in range(20))
    plan = plan_operational_htdy_activation(
        operational=products, recording_start=NOW + timedelta(minutes=2),
        expires_at=NOW + timedelta(minutes=1), now=NOW,
        host="isolated-host", environment="isolated")
    result = apply_operational_htdy_activation(
        factory, plan, expected_plan_hash=plan["plan_hash"], operational=products, now=NOW)
    assert len(result["routes"]) == 60
    assert _count(factory, ReferenceStream) == 60
    assert _count(factory, ReferenceActivationReceipt) == 60
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceBatch).where(
            ReferenceBatch.kind == "capture")) == 0
        assert session.scalar(select(func.count()).select_from(ReferenceActionRow)) == 0
    assert readback_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                                    operational=products) == result


def test_cli_plan_uses_current_operational_scope_and_never_connects(tmp_path, capsys):
    from scripts.reference_trading_htdy_activation import main

    current = datetime.now(UTC)
    target = tmp_path / "htdy-plan.json"
    assert main([
        "plan", "--recording-start", (current + timedelta(hours=1)).isoformat(),
        "--expires-at", (current + timedelta(minutes=30)).isoformat(),
        "--host", "isolated-host", "--environment", "isolated",
        "--output", str(target),
    ]) == 0
    generated = json.loads(target.read_text(encoding="utf-8"))
    assert len(generated["products"]) == len(generated["stream_ids"]) == 60
    assert generated["frequency"] == "60m"
    assert json.loads(capsys.readouterr().out)["plan_hash"] == generated["plan_hash"]


@pytest.mark.isolated_postgresql
def test_concurrent_scope_activation_has_one_winner(reference_postgresql):  # noqa: F811
    Base.metadata.create_all(reference_postgresql)
    factory = sessionmaker(reference_postgresql)
    plan = _plan()
    barrier = Barrier(2)

    def attempt():
        barrier.wait()
        try:
            apply_htdy_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
                                  operational={"rb", "cu"}, now=NOW)
            return "activated"
        except RepositoryConflict as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result() for future in (pool.submit(attempt), pool.submit(attempt))]
    assert sorted(outcomes) == ["HTDY_ACTIVATION_ALREADY_EXISTS_READBACK_REQUIRED", "activated"]
    assert _count(factory, ReferenceStream) == 2
    assert _count(factory, ReferenceActivationReceipt) == 2
