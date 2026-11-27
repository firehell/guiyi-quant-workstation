from datetime import UTC, date, datetime, time, timedelta
from hashlib import file_digest
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.retry import Retry
from sqlalchemy.engine import make_url

from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
from app.market_data.operational_universe import load_operational_products
from app.runtime_cohort import CohortError, apply_cohort, freeze_cohort, market_source_recovery_direction, validate
from app.runtime_market_source_handover import (
    old_observation_snapshot,
    preserve_stopped_observations,
    read_staged_observations,
    redis_instance,
    stage_new_observations,
    verify_preserved_observations,
)
from tests.data_foundation.test_tick_htdy_integration import disposable_market  # noqa: F401
from tests.test_runtime_cohort import Host

OLD_DAY = date(2026, 10, 23)
NEW_DAY = date(2026, 10, 26)


@pytest.fixture
def redis_pair():
    ports = [os.environ.get(name) for name in ("GUIYI_TEST_REDIS_PORT", "GUIYI_MARKET_TARGET_REDIS_PORT")]
    if None in ports:
        pytest.skip("requires two dedicated Redis instances")
    old_port, target_port = map(int, ports)
    assert old_port != target_port and all(1024 <= p <= 65535 and p != 6379 for p in (old_port, target_port))
    with Redis(host="127.0.0.1", port=old_port, decode_responses=True) as old, Redis(
        host="127.0.0.1", port=target_port, decode_responses=True, retry=Retry(NoBackoff(), 0),
    ) as target:
        assert old.dbsize() == target.dbsize() == 0 and redis_instance(old) != redis_instance(target)
        try:
            yield old, target
        finally:
            for redis in (old, target):
                for key in redis.scan_iter():
                    redis.delete(key)


@pytest.mark.isolated_postgresql
def test_source_retirement_preserves_60_old_terminals_and_stages_58_products(
    tmp_path, redis_pair, disposable_market, monkeypatch,  # noqa: F811
):
    from contextlib import contextmanager

    from sqlalchemy.orm import Session

    from app.db.readonly import readonly_transaction
    from app.market_data.day_preparation import VERSION, metadata_preparation_binding
    from app.market_data.live_market import RedisLiveStore
    from app.models import Contract, Exchange, Instrument, MainContractMap, TradingCalendar, TradingSession
    from app.runtime_market_cohort_host import MarketCohortHost

    engine, _ = disposable_market
    old, target = redis_pair
    products = load_operational_products()
    old_products = tuple(sorted((*products, "pd", "pt")))
    contracts = {product: f"{product.upper()}2701" for product in old_products}
    with Session(engine) as session:
        session.add(Exchange(code="GFEX", name="test"))
        session.flush()
        for offset in range((NEW_DAY - OLD_DAY).days + 2):
            day = OLD_DAY + timedelta(days=offset)
            session.add(TradingCalendar(
                exchange_code="GFEX", trade_date=day, is_trading_day=day in {OLD_DAY, NEW_DAY},
                has_night_session=False, provider="rqdata",
            ))
        session.add_all(Instrument(symbol=product, name=product, exchange_code="GFEX", is_active=True)
                        for product in old_products)
        session.flush()
        session.add_all(Contract(contract_code=contract, instrument_symbol=product, exchange_code="GFEX",
                                 listed_date=OLD_DAY, expired_date=NEW_DAY + timedelta(days=1), provider="rqdata")
                        for product, contract in contracts.items())
        session.flush()
        for day, scope in ((OLD_DAY, old_products), (NEW_DAY, products)):
            for product in scope:
                session.add(TradingSession(
                    exchange_code="GFEX", instrument_symbol=product, session_name="day",
                    start_time=time(9), end_time=time(15), effective_from=day, effective_to=day,
                    provider="rqdata",
                ))
                session.add(MainContractMap(symbol=product, trade_date=day, contract_code=contracts[product]))
        session.commit()

    @contextmanager
    def catalog_session(_settings):
        with Session(engine) as session, readonly_transaction(session, timeout_seconds=20):
            yield session, tmp_path

    monkeypatch.setenv("HOME", str(tmp_path))
    host = MarketCohortHost()
    monkeypatch.setattr(host, "_catalog_session", catalog_session)
    monkeypatch.setattr(host, "now", lambda: datetime.combine(OLD_DAY, time(7, 5), tzinfo=UTC))
    window, day, subscribed, windows, _, _ = host._authority({}, OLD_DAY, old_products)
    assert window["products"] == 60
    assert day == NEW_DAY
    assert tuple(subscribed) == products and len(subscribed) == 58
    assert all(windows[product][2:] == (None, ()) for product in ("pd", "pt"))
    host.directory.mkdir(parents=True)
    previous = host.directory / "market-day-metadata-preparation.json"
    with Session(engine) as session:
        previous.write_text(json.dumps({
            "version": VERSION,
            "binding_id": metadata_preparation_binding(session, tmp_path, old_products),
            "days": {NEW_DAY.isoformat(): {"status": "inflight"}},
        }))
    with pytest.raises(CohortError, match="METADATA_PREPARATION_READBACK_REQUIRED"):
        host._authority({}, OLD_DAY, old_products)
    assert previous.exists()
    terminals = host._terminals(windows, old_products, "1m")
    assert set(terminals) == set(old_products)
    for kind, consumers in (("source", ("live",)), ("completed", ("alert", "reference"))):
        stream = ObservationStream(old, kind=kind)
        for product, (contract, end) in terminals.items():
            tail = stream.append(ObservationEnvelope(
                f"{product}-terminal", OLD_DAY, end, f"live:bar:{product}:1m",
                {"contract": contract, "bar_end": end.isoformat()}, True,
            ))
        for consumer in consumers:
            stream.initialize(consumer, OLD_DAY, cursor=tail)
    proof = preserve_stopped_observations(
        old, OLD_DAY, alert_enabled=True, attempt=tmp_path, check_budget=lambda: None, terminals=terminals,
    )
    assert all(proof[kind][str(OLD_DAY)]["count"] == 60 for kind in ("source", "completed"))
    verify_preserved_observations(tmp_path, proof["archive_sha256"], check_budget=lambda: None)
    database = make_url("postgresql+psycopg://operator@127.0.0.1:5432/guiyi_quant")
    stage_new_observations(
        target, database, tmp_path, old_instance=proof["instance"], day=day, subscriptions=subscribed,
        alert_enabled=True, expected_instance=redis_instance(target),
    )
    assert RedisLiveStore(target).subscriptions(NEW_DAY) == subscribed


class IsolatedHost(Host):
    def __init__(self, tmp, old_redis, target_redis):
        super().__init__(tmp)
        self.old_redis, self.target = old_redis, target_redis
        self.database = make_url("postgresql+psycopg://operator@127.0.0.1:5432/guiyi_quant")
        self.canonical = tmp
        self.subscriptions = {p: f"{p.upper()}2701" for p in load_operational_products()}
        self.active_writer = "old"
        self.stage_count = 0
        self.lost_replies = 0
        self.seed_old()

    def seed_old(self):
        event = ObservationEnvelope("old", OLD_DAY, self.now(), "live:bar:rb:1m", {"source": "bar"}, True)
        old_source = ObservationStream(self.old_redis, kind="source")
        old_completed = ObservationStream(self.old_redis, kind="completed")
        old_source.initialize("live", OLD_DAY, cursor=old_source.append(event))
        tail = old_completed.append(event)
        for consumer in ("alert", "reference"):
            old_completed.initialize(consumer, OLD_DAY, cursor=tail)

    def freeze_market_source_handover(self, old, new, window):
        return {
            "old_instance": redis_instance(self.old_redis), "target_instance": redis_instance(self.target),
            "old_day": str(OLD_DAY), "target_day": str(NEW_DAY),
            "catalog_sha256": "a" * 64, "tqkq_sha256": "b" * 64, "subing_sha256": "c" * 64,
        }

    def check_market_source_plan(self, plan):
        assert self.freeze_market_source_handover(None, None, None) == plan["market_source_handover"]

    def stop_old(self, plan, proof):
        super().stop_old(plan, proof)
        self.active_writer = None

    def target_arguments(self, plan):
        intent = plan["market_source_handover"]
        return dict(expected_instance=intent["target_instance"], day=NEW_DAY,
                    subscriptions=self.subscriptions, alert_enabled=True)

    def preserve_market_source(self, plan, proof, attempt):
        assert self.in_guard and self.active_writer is None
        return preserve_stopped_observations(
            self.old_redis, OLD_DAY, alert_enabled=True, attempt=attempt, check_budget=lambda: None,
        )

    def stage_market_source(self, plan, proof, retained):
        assert self.in_guard and self.active_writer is None
        attempt = self.directory / "cohort-attempts" / plan["plan_sha256"]
        persisted = json.loads((attempt / "state.json").read_text())
        assert persisted["phase"] == "market_source_stage"
        assert persisted["effects"]["market_source_preserve"] == retained
        self.stage_count += 1
        parse_response = self.target.parse_response

        def lose_stage_reply(connection, command, **options):
            value = parse_response(connection, command, **options)
            if self.failure == "redis_unknown" and command == "EVAL":
                self.lost_replies += 1
                raise RedisConnectionError("response lost after staging")
            return value

        with patch.object(self.target, "parse_response", lose_stage_reply):
            return stage_new_observations(
                self.target, self.database, self.canonical, old_instance=retained["instance"],
                **self.target_arguments(plan),
            )

    def check_staged_market_source(self, plan, proof, retained, staged):
        old = old_observation_snapshot(self.old_redis, OLD_DAY, alert_enabled=True, check_budget=lambda: None)
        assert old == {k: v for k, v in retained.items() if k != "archive_sha256"}
        assert read_staged_observations(
            self.target, self.database, self.canonical, **self.target_arguments(plan),
        ) == staged

    def verify_market_source_restore(self, plan, effects):
        self.calls.append("verify_restore")
        assert self.active_writer != "tick"
        if "market_source_stage" in effects:
            self.check_staged_market_source(
                plan, None, effects["market_source_preserve"], effects["market_source_stage"],
            )

    def market_source_consumers_ready(self, plan, proof):
        assert self.active_writer is None
        return self.consumers_ready(plan, proof)

    def verify_market_source(self, plan, proof):
        assert self.active_writer == "tick"
        return self.verify(plan, proof)

    def start_feed(self, plan):
        assert self.active_writer is None
        super().start_feed(plan)
        self.active_writer = "tick"

    def restore_old(self, plan):
        super().restore_old(plan)
        self.active_writer = "old"


def _plan(host):
    return freeze_cohort(host, candidate_root=host.root, tag="v1.16.5", commit="e" * 40, market_source=True)


@pytest.mark.parametrize("failure", [None, "install", "redis_unknown", "cas_unknown", "verify"])
def test_two_redis_handover_preserves_original_and_never_retries(tmp_path, redis_pair, failure):
    host = IsolatedHost(tmp_path, *redis_pair)
    plan = _plan(host)
    host.failure = failure
    if failure:
        with pytest.raises(CohortError):
            apply_cohort(host, plan)
    else:
        assert apply_cohort(host, plan)["status"] == "switched"

    attempt = host.directory / "cohort-attempts" / plan["plan_sha256"]
    state = json.loads((attempt / "state.json").read_text())
    assert state["phase"] == {
        None: "switched", "install": "cancelled", "redis_unknown": "restore_unknown",
        "cas_unknown": "outcome_unknown", "verify": "outcome_unknown",
    }[failure]
    assert host.stage_count == 1
    assert host.lost_replies == (1 if failure == "redis_unknown" else 0)
    assert "restore_old" in host.calls if failure == "install" else "restore_old" not in host.calls
    assert ("halt_unknown" in host.calls) == (failure in {"cas_unknown", "verify"})
    assert ("verify_restore" in host.calls) == (failure == "install")
    if failure in {"redis_unknown", "cas_unknown", "verify"}:
        direction = "target_readback_required" if failure == "redis_unknown" else "forward_only"
        assert market_source_recovery_direction(plan, state, host.registry) == direction
    if failure == "cas_unknown":
        for phase in ("committing", "committed", "consumers", "feed"):
            assert market_source_recovery_direction(plan, {**state, "phase": phase}, host.registry) == "forward_only"
        assert market_source_recovery_direction(plan, {**state, "phase": "committing"}, host.old) == "binding_readback_required"
    with pytest.raises(CohortError):
        apply_cohort(host, plan)
    assert host.stage_count == 1
    original = attempt / "old-observation-originals.jsonl"
    with original.open("rb") as stream:
        retained_hash = file_digest(stream, "sha256").hexdigest()
    assert len(original.read_bytes().splitlines()) == 2
    assert state["effects"]["market_source_preserve"]["archive_sha256"] == retained_hash
    verify_preserved_observations(attempt, retained_hash, check_budget=lambda: None)
    with original.open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(CohortError, match="MARKET_SOURCE_ORIGINALS_DRIFT"):
        verify_preserved_observations(attempt, retained_hash, check_budget=lambda: None)
    assert ObservationStream(host.old_redis, kind="source").tail(OLD_DAY) != "0-0"
    assert ObservationStream(host.target, kind="source").cursor("live", NEW_DAY) == "0-0"
    assert not host.target.exists("live:observations:registered:completed:reference")
    # Independent readback can prove the staged write after an unknown reply.
    assert read_staged_observations(host.target, host.database, host.canonical, **host.target_arguments(plan))
    with pytest.raises(CohortError, match="COHORT_MARKET_SOURCE_RECOVERY_REQUIRED"):
        validate(plan, host.now())


@pytest.mark.parametrize("failure", ["before_replace", "after_replace", "after_commit", "forward_pointer_write", "forward_pointer_sync"])
def test_macos_recovery_reads_actual_registry_after_interrupted_cas(tmp_path, redis_pair, monkeypatch, failure):
    from contextlib import contextmanager, ExitStack
    from hashlib import sha256

    from app.market_data.aggregation import SessionWindow
    from app.reference_trading.recovery_campaign import digest
    from app import runtime_bindings as bindings
    from app.runtime_cohort import registry, terminal_cohort_state
    from app.runtime_handover import _write
    from app.runtime_market_cohort_host import MarketCohortHost
    from app.runtime_market_forward_recovery import forward_completed, recover_market_source_forward

    home = tmp_path / "isolated-home"
    monkeypatch.setenv("HOME", str(home))
    native = MarketCohortHost()
    monkeypatch.setattr("app.runtime_market_forward_recovery._bound_operational_products",
                        lambda _registry: load_operational_products())
    native.directory.mkdir(mode=0o700, parents=True)
    old, target = redis_pair
    redis_urls = [f"redis://127.0.0.1:{client.connection_pool.connection_kwargs['port']}/0"
                  for client in (old, target)]
    stable = (f'GUIYI_CANONICAL_DATA_ROOT="{tmp_path}"\n'
              'DATABASE_URL=postgresql+psycopg://operator@127.0.0.1:5432/guiyi_quant\n').encode()
    original = stable + f"REDIS_URL={redis_urls[0]}\n".encode()
    proposed = stable + f"REDIS_URL={redis_urls[1]}\n# guiyi-market-source: rqdata_tick\n".encode()
    native._private_original(native.project_config, original)
    native._target_config_sha = sha256(proposed).hexdigest()
    accounts = {"tqkq": {"pid": 1234, "helper_pid": 1235}, "subing": {"pid": 1236}}
    old_end = datetime(2026, 10, 23, 7, tzinfo=UTC)
    old_session = (SessionWindow(old_end - timedelta(minutes=1), old_end),)

    class NativeRegistryHost(IsolatedHost):
        def seed_old(self):
            for kind, consumers in (("source", ("live",)), ("completed", ("alert", "reference"))):
                stream = ObservationStream(old, kind=kind)
                for product, contract in self.subscriptions.items():
                    tail = stream.append(ObservationEnvelope(
                        product, OLD_DAY, old_end, f"live:bar:{product}:1m",
                        {"contract": contract, "bar_end": old_end.isoformat()}, True,
                    ))
                for consumer in consumers:
                    stream.initialize(consumer, OLD_DAY, cursor=tail)

        def bindings(self):
            return bindings.read_bindings(home=home)

        def binding_hash(self):
            return bindings.bindings_sha256(home=home)

        def protected(self, old):
            return {"files": {str(native.project_config): sha256(original).hexdigest()}}

        def freeze_market_source_handover(self, old_registry, new, window):
            intent = super().freeze_market_source_handover(old_registry, new, window)
            journals = old_observation_snapshot(old, OLD_DAY, alert_enabled=True, check_budget=lambda: None)
            return {**intent, **{f"{name}_sha256": digest(row) for name, row in accounts.items()},
                    "host_sha256": digest({"old_config": sha256(original).hexdigest(),
                                           "target_config": native._target_config_sha, "journals": journals})}

        def stop_old(self, plan, proof):
            super().stop_old(plan, proof)
            return {"old_pids_exited": True, "accounts": accounts}

        def install(self, plan, attempt):
            super().install(plan, attempt)
            copies = attempt / "originals"
            copies.mkdir(mode=0o700)
            native._private_original(copies / "000.bin", original)
            native._private_original(copies / "index.json", json.dumps({"files": [
                {"source": str(native.project_config), "file": "000.bin"},
            ]}).encode())
            native._replace_plist(native.project_config, proposed)

        def stage_market_source(self, plan, proof, retained):
            binding = super().stage_market_source(plan, proof, retained)
            return {"binding": binding, "config_sha256": native._target_config_sha}

        def check_staged_market_source(self, plan, proof, retained, staged):
            super().check_staged_market_source(plan, proof, retained, staged["binding"])

        def commit(self, plan):
            assert self.in_guard and self.active_writer is None
            assert json.loads((self.directory / "cohort-release.json").read_text())["phase"] == "committing"
            self.calls.append("commit")
            return native.commit(plan)

    host = NativeRegistryHost(tmp_path, old, target)
    host.directory = native.directory
    monkeypatch.setattr(native, "_assert_stopped", lambda _plan: host.active_writer is None or pytest.fail("writer active"))
    bindings.write_bindings(host.old, home=home, expected_sha256=None)
    plan = _plan(host)
    host.failure = "verify" if failure in {"after_commit", "forward_pointer_write", "forward_pointer_sync"} else None
    raw_replace = os.replace
    registry_path = bindings.registry_path(home)
    replace_count = 0

    def replace_registry(src, dst):
        nonlocal replace_count
        if dst != registry_path:
            return raw_replace(src, dst)
        replace_count += 1
        if failure == "before_replace":
            raise OSError("isolated registry replace rejected")
        return raw_replace(src, dst)

    with monkeypatch.context() as faults:
        faults.setattr(bindings.os, "replace", replace_registry)
        if failure == "after_replace":
            write_registry = bindings.write_bindings

            def lose_cas_reply(*args, **kwargs):
                write_registry(*args, **kwargs)
                raise OSError("isolated reply lost after fsync")

            faults.setattr(bindings, "write_bindings", lose_cas_reply)
        with pytest.raises(CohortError, match="COHORT_OUTCOME_UNKNOWN_READBACK_REQUIRED"):
            apply_cohort(host, plan)

    supplied = native.directory / "cohort-attempts" / plan["plan_sha256"] / "plan.json"
    registry_image = registry_path.read_bytes()
    recovery = MarketCohortHost().read_market_source_recovery(supplied)
    assert recovery["registry"] == ("legacy" if failure == "before_replace" else "target")
    assert recovery["direction"] == ("binding_readback_required" if failure == "before_replace" else "forward_only")
    assert recovery["active_configuration"] == "target"
    assert bindings.read_bindings(home=home) == (host.old if failure == "before_replace" else registry(plan["new"]))
    state_path = supplied.with_name("state.json")
    state = json.loads(state_path.read_text())
    interrupted = {**state, "phase": "committing"}
    _write(state_path, interrupted)  # Private state persisted just ahead of the global pointer.
    interrupted_raw = state_path.read_bytes()
    observed = MarketCohortHost().read_market_source_recovery(supplied)
    assert observed["direction"] == recovery["direction"]
    assert (observed["private_phase"], observed["pointer_phase"]) == ("committing", "outcome_unknown")
    with pytest.raises(CohortError, match="COHORT_RECOVERY_READBACK_REQUIRED"):
        apply_cohort(host, plan)
    assert "restore_old" not in host.calls and host.calls.count("commit") == replace_count == 1
    assert registry_path.read_bytes() == registry_image

    successor = MarketCohortHost()
    if failure == "before_replace":
        with pytest.raises(CohortError, match="MARKET_SOURCE_FORWARD_CAS_UNPROVEN"):
            recover_market_source_forward(successor, supplied)
        return

    @contextmanager
    def guards(_plan):
        with ExitStack() as locks:
            successor._account_guards = locks
            yield

    for name in ("tqkq-simulation", "subing-paper"):
        folder = successor.directory / name
        folder.mkdir(mode=0o700)
        successor._private_original(folder / "owner.lock", b"")
    new = registry(plan["new"])
    calls = []
    loaded = set()

    def start(binding):
        assert binding == new.services[binding.service] and binding.service not in loaded
        loaded.add(binding.service)
        calls.append(binding.service)

    def read_accounts(plan, proof):
        assert "market-feed" not in loaded and successor._accounts == accounts
        calls.append("account_readback")
        return {"accounts": "verified"}

    def verify(plan, proof):
        assert "market-feed" in loaded
        if failure == "after_commit":
            raise CohortError("ISOLATED_VERIFICATION_FAILURE")
        calls.append("verify")
        return {"continuous_identity": "matched"}

    for name, replacement in {
        "guards": guards, "assert_new_installed": lambda _new: None,
        "verify_release": lambda *args: None, "check_schema_compatibility": lambda _plan: None,
        "check_controller_catalog": lambda _settings: None,
        "assert_protected": lambda _plan: None, "_pid_absent": lambda _pid: True,
        "_verify_stopped_accounts": lambda _plan, _windows: None,
        "_account_absent": lambda _name: True, "definition_absent": lambda binding: binding.service not in loaded,
        "_authority": lambda *_args: (None, NEW_DAY, None, {
            name: (contract, old_session, contract, ()) for name, contract in host.subscriptions.items()
        }, None, None),
        "_target_arguments": lambda *_args: {**host.target_arguments(plan), "database": host.database,
                                             "canonical": host.canonical},
        "start": start, "market_source_consumers_ready": read_accounts, "verify_market_source": verify,
        "restore_calendars": lambda _plan: calls.append("calendars"),
        "halt_unknown": lambda _plan: calls.append("halt_unknown"),
    }.items():
        monkeypatch.setattr(successor, name, replacement)
    if failure == "after_replace":
        # A stale native account preimage cannot effect any launch.
        with monkeypatch.context() as drift:
            def drifted_account(*_args):
                raise CohortError("MARKET_SOURCE_STOPPED_TQ_CONFIG_DRIFT")

            drift.setattr(successor, "_verify_stopped_accounts", drifted_account)
            with pytest.raises(CohortError, match="MARKET_SOURCE_STOPPED_TQ_CONFIG_DRIFT"):
                recover_market_source_forward(successor, supplied)
            assert not calls
        candidate_source = ObservationStream(target, kind="source")
        candidate_source.append(ObservationEnvelope(
            "unverified-new-observation", NEW_DAY, host.now(), "live:bar:rb:1m", {}, True,
        ))
        with pytest.raises(CohortError, match="MARKET_SOURCE_FORWARD_TARGET_NOT_PRISTINE"):
            recover_market_source_forward(successor, supplied)
        assert not calls
        target.delete(candidate_source.key(NEW_DAY), candidate_source.identity_key(NEW_DAY))
        assert recover_market_source_forward(successor, supplied)["status"] == "recovered"
        assert calls[-4:] == ["account_readback", "market-feed", "verify", "calendars"]
        assert forward_completed(successor, plan, interrupted)
    else:
        if failure in {"forward_pointer_write", "forward_pointer_sync"}:
            def lose_pointer(path, value):
                if path.name == "cohort-release.json" and value.get("phase") == "switched":
                    if failure == "forward_pointer_sync":
                        _write(path, value)
                    raise OSError("isolated forward pointer write rejected")
                _write(path, value)

            monkeypatch.setattr("app.runtime_market_forward_recovery._write", lose_pointer)
            if failure == "forward_pointer_sync":
                def fail_sync(_path):
                    raise OSError("isolated persistent directory sync error")

                monkeypatch.setattr("app.runtime_market_forward_recovery._sync_published", fail_sync)
        with pytest.raises(CohortError, match="MARKET_SOURCE_FORWARD_READBACK_REQUIRED"):
            recover_market_source_forward(successor, supplied)
        assert calls[-1] == "halt_unknown" and "market-feed" in calls
        assert MarketCohortHost().read_market_source_recovery(supplied)["same_generation_recovery"] == "readback_required"
        pointer = json.loads((successor.directory / "cohort-release.json").read_text())
        assert not terminal_cohort_state(successor.directory, pointer)
        expected_error = "MARKET_SOURCE_FORWARD_CAS_UNPROVEN" if failure == "forward_pointer_sync" else "MARKET_SOURCE_FORWARD_ATTEMPT_CONSUMED"
        with pytest.raises(CohortError, match=expected_error):
            recover_market_source_forward(successor, supplied)
    assert state_path.read_bytes() == interrupted_raw
    assert registry_path.read_bytes() == registry_image


def test_legacy_backlog_blocks_before_target_stage(tmp_path, redis_pair):
    host = IsolatedHost(tmp_path, *redis_pair)
    event = ObservationEnvelope("unconsumed", OLD_DAY, datetime.now(UTC), "live:bar:rb:1m", {}, True)
    ObservationStream(host.old_redis, kind="completed").append(event)
    with pytest.raises(CohortError, match="COHORT_PRECONDITION_CANCELLED"):
        apply_cohort(host, _plan(host))
    assert host.stage_count == 0 and host.target.dbsize() == 0
    assert "commit" not in host.calls and host.active_writer == "old"


def test_old_market_terminal_proof_ignores_neither_missing_route_nor_wrong_contract(redis_pair):
    old, _ = redis_pair
    end = datetime(2026, 10, 23, 7, tzinfo=UTC)
    for kind, consumers in (("source", ("live",)), ("completed", ("alert", "reference"))):
        stream = ObservationStream(old, kind=kind)
        tail = stream.append(ObservationEnvelope(
            "known", OLD_DAY, end, "live:bar:rb:1m", {"contract": "RB2701", "bar_end": end.isoformat()}, True,
        ))
        for consumer in consumers:
            stream.initialize(consumer, OLD_DAY, cursor=tail)
    options = {"alert_enabled": True, "check_budget": lambda: None}
    assert old_observation_snapshot(old, OLD_DAY, terminals={"rb": ("RB2701", end)}, **options)["source"]
    for terminals in ({"rb": ("RB2705", end)}, {"rb": ("RB2701", end), "jm": ("JM2701", end)}):
        with pytest.raises(CohortError, match="MARKET_SOURCE_OLD_TERMINAL_UNPROVEN"):
            old_observation_snapshot(old, OLD_DAY, terminals=terminals, **options)


@pytest.mark.parametrize(("kind", "contract"), [("source", "RB2705"), ("completed", "RB2701")])
def test_old_market_terminal_proof_rejects_two_distinct_originals_at_frozen_end(redis_pair, kind, contract):
    old, _ = redis_pair
    end = datetime(2026, 10, 23, 7, tzinfo=UTC)
    for stream_kind, consumers in (("source", ("live",)), ("completed", ("alert", "reference"))):
        stream = ObservationStream(old, kind=stream_kind)
        tail = stream.append(ObservationEnvelope(
            "expected", OLD_DAY, end, "live:bar:rb:1m", {"contract": "RB2701", "bar_end": end.isoformat()}, True,
        ))
        if stream_kind == kind:
            tail = stream.append(ObservationEnvelope(
                "duplicate", OLD_DAY, end, "live:bar:rb:1m", {"contract": contract, "bar_end": end.isoformat()}, True,
            ))
        for consumer in consumers:
            stream.initialize(consumer, OLD_DAY, cursor=tail)

    with pytest.raises(CohortError, match="MARKET_SOURCE_OLD_TERMINAL_UNPROVEN"):
        old_observation_snapshot(old, OLD_DAY, alert_enabled=True, check_budget=lambda: None,
                                 terminals={"rb": ("RB2701", end)})


def test_old_market_retention_byte_budget_is_combined_and_enforced_before_stop(tmp_path, redis_pair, monkeypatch):
    old, _ = redis_pair
    IsolatedHost(tmp_path, *redis_pair)
    options = dict(alert_enabled=True, check_budget=lambda: None)
    snapshot = preserve_stopped_observations(old, OLD_DAY, attempt=tmp_path, **options)
    original = tmp_path / "old-observation-originals.jsonl"
    assert old_observation_snapshot(old, OLD_DAY, **options) == {
        key: value for key, value in snapshot.items() if key != "archive_sha256"
    }
    rows = original.read_bytes().splitlines(keepends=True)
    assert len(rows) == 2
    limit = len(b"".join(rows)) - 1
    assert max(map(len, rows)) <= limit
    monkeypatch.setattr("app.runtime_market_source_handover._MAX_RETAINED_BYTES", limit)
    with pytest.raises(CohortError, match="MARKET_SOURCE_RETENTION_LIMIT"):
        old_observation_snapshot(old, OLD_DAY, **options)


def test_macos_market_configuration_preserves_pinned_account_parser_and_other_settings(tmp_path):
    from app.runtime_market_cohort_host import _market_config_pair

    old, target = (tmp_path / name for name in ("project.env", "market-tick.env"))
    stable = (f'GUIYI_CANONICAL_DATA_ROOT="{tmp_path}"\n'
              'DATABASE_URL=postgresql+psycopg://test@127.0.0.1:25491/guiyi_quant\n').encode()
    old.write_bytes(stable + b"REDIS_URL=redis://127.0.0.1:26391/0\n")
    target.write_bytes(stable + b"REDIS_URL=redis://127.0.0.1:26392/0\n# guiyi-market-source: rqdata_tick\n")
    for path in (old, target):
        path.chmod(0o600)
    assert _market_config_pair(old, target)[3]["REDIS_URL"] == "redis://127.0.0.1:26392/0"
    target.write_bytes(target.read_bytes() + b"# unrelated change\n")
    with pytest.raises(CohortError, match="MARKET_SOURCE_CONFIG_TRANSITION_INVALID"):
        _market_config_pair(old, target)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS process socket readback")
def test_macos_uses_target_redis_socket_and_native_account_watermark(redis_pair, tmp_path):
    from app.runtime_market_account_readback import tq_watermark
    from app.runtime_market_cohort_host import _connects_to
    from guiyi_quant.htdy_account_execution import model
    from guiyi_quant.htdy_account_execution.reducer import start
    from guiyi_quant.htdy_account_execution.store import LocalStore
    from guiyi_quant.trading_universe import TRADING_PRODUCTS, TRADING_SCOPE_VERSION
    from tests.unit.tq_simulation.test_execution import A, rb

    old, target = redis_pair
    account = tmp_path / "account.sqlite"
    products = tuple(name.upper() for name in TRADING_PRODUCTS)
    old_end = datetime(2026, 10, 23, 7, tzinfo=UTC)
    new_end = datetime(2026, 10, 26, 7, tzinfo=UTC)
    activated = old_end - timedelta(hours=1)
    store = LocalStore(account, start(A, products, activated, rb(activated)),
                       execution_identity="TQKQ:" + A + ":htdy_tqkq_v1")

    def expected(end):
        return {name.lower(): (name + "2701", end) for name in products}

    def record(close, previous):
        observed = close + timedelta(seconds=2)
        for product in products:
            identifier = f"{product}:{close.isoformat()}"
            signal = model.Signal(identifier, product, product + "2701", close, observed, previous, (), "b" * 64)
            assert not store.execute(identifier, signal).effects
        assert not store.execute("readback:" + close.isoformat(), rb(observed)).effects

    port = target.connection_pool.connection_kwargs["port"]
    channels = [f"live:bar:{name}:60m" for name in TRADING_PRODUCTS]
    checking_old = old_end + timedelta(seconds=3)
    checking_new = new_end + timedelta(seconds=3)
    try:
        store.execute("scope", model.TqKqTradingScopeV1(activated, products, TRADING_SCOPE_VERSION))
        for product in products:
            store.execute("owner:" + product, model.Owner(product, product + "2701", activated, "owner:" + product))
        record(old_end, None)
        assert tq_watermark(account, A, expected(old_end), checking_old)["status"] == "verified"
        assert tq_watermark(account, A, expected(old_end), checking_new)["status"] == "blocked"
        assert tq_watermark(account, A, expected(old_end), checking_new, stopped=True)["status"] == "verified"
        with subprocess.Popen([sys.executable, "-c", """
import sys
from redis import Redis
with Redis(host='127.0.0.1', port=int(sys.argv[1])) as client, client.pubsub() as pubsub:
    pubsub.subscribe(*sys.argv[2:])
    for _ in sys.argv[2:]:
        assert pubsub.get_message(timeout=3)['type'] == 'subscribe'
    print('ready', flush=True)
    sys.stdin.read()
""", str(port), *channels], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as owner:
            try:
                assert owner.stdout.readline().strip() == "ready"
                # Docker Desktop may translate the host socket to another TCP tuple.
                subscriptions = [row for row in target.client_list() if int(row["sub"]) == len(channels)]
                assert len(subscriptions) == 1
                assert _connects_to(target, owner.pid) == (subscriptions[0]["laddr"] == f"127.0.0.1:{port}")
                assert not _connects_to(old, owner.pid)
                # Redis connectivity by itself does not advance the native tip.
                assert tq_watermark(account, A, expected(new_end), checking_old)["status"] == "blocked"
                record(new_end, old_end)
            finally:
                owner.stdin.close()
        assert tq_watermark(account, A, expected(new_end), checking_new)["status"] == "verified"
        assert tq_watermark(account, A, expected(old_end), checking_new)["status"] == "blocked"
    finally:
        store.close()


@pytest.mark.parametrize(("subscribers", "verified"), [
    ([{"addr": "127.0.0.1:30100", "laddr": "127.0.0.1:16400", "db": 0, "sub": 16}], True),
    ([{"addr": "127.0.0.1:30100", "laddr": "127.0.0.1:16400", "db": 6, "sub": 16}], False),
    ([{"addr": "127.0.0.1:30101", "laddr": "127.0.0.1:16400", "db": 0, "sub": 16}], False),
    ([{"addr": "192.168.0.2:30100", "laddr": "192.168.0.3:6379", "db": 0, "sub": 16}], False),
])
def test_macos_redis_socket_requires_same_pid_tcp_tuple_and_database(monkeypatch, subscribers, verified):
    from types import SimpleNamespace

    from app import runtime_market_cohort_host as host

    monkeypatch.setattr(host, "command_result", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout="n127.0.0.1:30100->127.0.0.1:16400\n",
    ))
    redis = SimpleNamespace(
        connection_pool=SimpleNamespace(connection_kwargs={"host": "127.0.0.1", "port": 16400}),
        client_list=lambda: subscribers,
        pubsub_numsub=lambda *channels: [(channel, 1) for channel in channels],
    )
    assert host._connects_to(redis, 123) is verified


@pytest.mark.parametrize("late", [False, True])
def test_target_first_completed_minutes_use_exact_session_and_indexed_original(tmp_path, redis_pair, late):
    from decimal import Decimal

    from app.market_data.aggregation import SessionWindow
    from app.market_data.domain import CanonicalBar
    from app.market_data.live_market import _bar_payload
    from app.market_data.observation_stream import completed_observation_id
    from app.runtime_market_source_handover import read_first_completed_minutes

    _, target = redis_pair
    subscriptions = {product: f"{product.upper()}2701" for product in load_operational_products()}
    stage_new_observations(
        target, make_url("postgresql+psycopg://operator@127.0.0.1:5432/guiyi_quant"), tmp_path,
        expected_instance=redis_instance(target), old_instance=redis_instance(redis_pair[0]),
        day=NEW_DAY, subscriptions=subscriptions, alert_enabled=True,
    )
    night = datetime(2026, 10, 25, 13, 1, tzinfo=UTC)
    day = night + timedelta(hours=12)
    expected = {product: (contract, day if product == "ec" else night) for product, contract in subscriptions.items()}
    sessions = {product: (contract, (SessionWindow(end - timedelta(minutes=1), end + timedelta(hours=1)),))
                for product, (contract, end) in expected.items()}
    stream = ObservationStream(target, kind="completed")
    generation = "rqdata-tick:" + "a" * 32 + ":1"

    def append(product, contract, end, *, delay=2):
        identity = completed_observation_id(NEW_DAY, contract, "1m", end)
        confirmed = end + timedelta(seconds=delay)
        price = Decimal("10")
        bar = CanonicalBar(end, NEW_DAY, price, price, price, price, Decimal("2"), None, None)
        stream_id = stream.append(ObservationEnvelope(
            identity, NEW_DAY, end, f"live:bar:{product}:1m", _bar_payload(bar, contract=contract), delay <= 30,
            raw_received_at=end, confirmed_at=confirmed, source_generation=generation,
        ))
        return identity, stream_id

    rb_end = night + timedelta(minutes=1)
    rb_identity, rb_stream_id = append("rb", subscriptions["rb"], rb_end)
    first = read_first_completed_minutes(target, NEW_DAY, sessions=sessions, now=night + timedelta(minutes=2))
    assert first["status"] == "first_completed_incomplete"
    assert first["products"]["ec"]["status"] == "pending"
    assert first["products"]["au"]["status"] == "missing"
    assert first["products"]["rb"]["status"] == "verified"
    assert first["products"]["rb"]["opening_is_first"] is False

    for product, (contract, end) in expected.items():
        if product != "rb":
            append(product, contract, end, delay=31 if late and product == "ec" else 2)
    now = day + timedelta(minutes=1)
    final = read_first_completed_minutes(target, NEW_DAY, sessions=sessions, now=now)
    assert final["status"] == ("first_completed_incomplete" if late else "first_completed_verified")
    assert final["products"]["ec"]["status"] == ("late" if late else "verified")
    assert set(final["products"]) == set(load_operational_products())
    assert final["products"]["rb"] == {
        "status": "verified", "contract": subscriptions["rb"], "bar_end": rb_end.isoformat(),
        "opening_bar_end": night.isoformat(), "opening_is_first": False,
        "observation_id": rb_identity, "stream_id": rb_stream_id, "source_generation": generation,
        "confirmed_at": (rb_end + timedelta(seconds=2)).isoformat(),
    }
    assert stream.cursor("alert", NEW_DAY) == "0-0"
    target.xdel(stream.key(NEW_DAY), rb_stream_id)
    with pytest.raises(CohortError, match="MARKET_SOURCE_TARGET_COMPLETED_PREFIX_UNPROVEN"):
        read_first_completed_minutes(target, NEW_DAY, sessions=sessions, now=now)


@pytest.mark.parametrize("invalid", ["payload", "confirmation", "index"])
def test_target_first_completed_rejects_unproved_payload_confirmation_or_identity(redis_pair, invalid):
    from decimal import Decimal

    from app.market_data.aggregation import SessionWindow
    from app.market_data.domain import CanonicalBar
    from app.market_data.live_market import RedisLiveStore, _bar_payload
    from app.market_data.observation_stream import completed_observation_id
    from app.runtime_market_source_handover import read_first_completed_minutes

    _, target = redis_pair
    end = datetime(2026, 10, 26, 1, 1, tzinfo=UTC)
    sessions = {"rb": ("RB2701", (SessionWindow(end - timedelta(minutes=1), end),))}
    RedisLiveStore(target).set_subscriptions(NEW_DAY, {"rb": "RB2701"})
    price = Decimal("10")
    bar = CanonicalBar(end, NEW_DAY, price, price, price, price, Decimal("2"), None, None)
    data = _bar_payload(bar, contract="RB2701")
    if invalid == "payload":
        del data["volume"]
    stream = ObservationStream(target, kind="completed")
    identity = completed_observation_id(NEW_DAY, "RB2701", "1m", end)
    stream.append(ObservationEnvelope(
        identity, NEW_DAY, end, "live:bar:rb:1m", data, True,
        raw_received_at=end, confirmed_at=end + timedelta(seconds=1 if invalid == "confirmation" else 2),
        source_generation="rqdata-tick:" + "a" * 32 + ":1",
    ))
    if invalid == "index":
        target.hdel(stream.identity_key(NEW_DAY), identity)
    with pytest.raises(CohortError, match="MARKET_SOURCE_TARGET_FIRST_MINUTE_UNPROVEN"):
        read_first_completed_minutes(target, NEW_DAY, sessions=sessions, now=end + timedelta(seconds=5))


def test_macos_restores_exact_config_after_known_pre_cas_failure_with_expired_apply_budget(tmp_path, redis_pair, monkeypatch):
    from hashlib import sha256
    from time import monotonic

    from app.market_data.aggregation import SessionWindow
    from app.runtime_market_cohort_host import MarketCohortHost, _market_config_pair

    fixture = IsolatedHost(tmp_path, *redis_pair)
    plan = _plan(fixture)
    native = MarketCohortHost()
    native.directory = fixture.directory
    private = native.project_config
    candidate = native.target_config
    old_redis_url, target_redis_url = [f"redis://127.0.0.1:{r.connection_pool.connection_kwargs['port']}/0"
                                      for r in redis_pair]
    stable = (f'GUIYI_CANONICAL_DATA_ROOT="{tmp_path}"\n'
              'DATABASE_URL=postgresql+psycopg://test@127.0.0.1:25491/guiyi_quant\n').encode()
    original = stable + f"REDIS_URL={old_redis_url}\n".encode()
    proposed = stable + f"REDIS_URL={target_redis_url}\n# guiyi-market-source: rqdata_tick\n".encode()
    native._private_original(private, original)
    native._private_original(candidate, proposed)
    plan["protected"] = {"files": {str(private): sha256(original).hexdigest()}}
    _, native._old_settings, _, _ = _market_config_pair(private, candidate)
    native._target_config_sha = sha256(proposed).hexdigest()
    native._old_terminals = None
    start = datetime(2026, 10, 26, 1, tzinfo=UTC)
    native._old_windows = {
        product: (contract, (), contract, (SessionWindow(start, start + timedelta(hours=1)),))
        for product, contract in fixture.subscriptions.items()
    }
    native.deadline = monotonic() + 30
    attempt = native._attempt(plan)
    attempt.mkdir(mode=0o700, parents=True)
    native._old_journal = old_observation_snapshot(fixture.old_redis, OLD_DAY, alert_enabled=True, check_budget=lambda: None)
    monkeypatch.setattr(native, "_assert_stopped", lambda _plan: None)
    monkeypatch.setattr(native, "_target_arguments", lambda *_: {
        **fixture.target_arguments(plan), "database": fixture.database, "canonical": fixture.canonical,
    })
    retained = native.preserve_market_source(plan, None, attempt)
    fixture.target.connection_pool.disconnect()
    staged = native.stage_market_source(plan, None, retained)
    originals = attempt / "originals"
    originals.mkdir(mode=0o700)
    native._private_original(originals / "000.bin", original)
    native._private_original(originals / "index.json", json.dumps({"files": [
        {"source": str(private), "file": "000.bin"},
    ]}).encode())
    native._replace_plist(private, proposed)
    native.deadline = monotonic() - 1
    native.verify_market_source_restore(plan, {"market_source_preserve": retained, "market_source_stage": staged})
    assert private.read_bytes() == original
    assert fixture.target.dbsize() > 0


def test_ordinary_controller_refuses_sealed_cross_instance_plan(tmp_path):
    with pytest.raises(CohortError, match="COHORT_MARKET_SOURCE_HANDOVER_REQUIRED"):
        _plan(Host(tmp_path))



def test_ordinary_apply_rejects_cross_instance_plan(tmp_path, redis_pair):
    host = IsolatedHost(tmp_path, *redis_pair)
    frozen = _plan(host)
    # Bind the ordinary host contract to the same control directory and identity
    # without inheriting any cross-instance callbacks.
    ordinary = object.__new__(Host)
    ordinary.__dict__.update(host.__dict__)
    with pytest.raises(CohortError, match="COHORT_MARKET_SOURCE_HANDOVER_REQUIRED"):
        apply_cohort(ordinary, frozen)
    assert not host.calls


@pytest.mark.parametrize("key, db", [
    ("live:feed:heartbeat", 0),
    ("live:observations:cursor:source:live:2026-10-22", 0),
    ("foreign", 1),
])
def test_staged_readback_rejects_any_extra_key(tmp_path, redis_pair, key, db):
    host = IsolatedHost(tmp_path, *redis_pair)
    plan = _plan(host)
    stage_new_observations(host.target, host.database, host.canonical,
                           old_instance=redis_instance(host.old_redis), **host.target_arguments(plan))
    port = host.target.connection_pool.connection_kwargs["port"]
    with Redis(host="127.0.0.1", port=port, db=db) as other:
        other.set(key, "unexpected")
        try:
            with pytest.raises(CohortError, match="MARKET_SOURCE_STAGED_BASELINE_UNPROVEN"):
                read_staged_observations(host.target, host.database, host.canonical, **host.target_arguments(plan))
        finally:
            other.delete(key)


def test_lua_checks_target_identity_in_same_operation_as_write(tmp_path, redis_pair):
    from app.market_data.market_foundation_scope import stage_empty_formal_tick_namespace

    host = IsolatedHost(tmp_path, *redis_pair)
    with pytest.raises(ValueError, match="MARKET_TICK_INITIAL_INSTANCE_DRIFT"):
        stage_empty_formal_tick_namespace(
            host.target, host.database, host.canonical, day=NEW_DAY, subscriptions=host.subscriptions,
            alert_enabled=True, expected_run_id=host.old_redis.info("server")["run_id"],
        )
    assert host.target.dbsize() == 0


def test_missing_middle_row_and_index_are_still_detected(tmp_path, redis_pair):
    host = IsolatedHost(tmp_path, *redis_pair)
    source = ObservationStream(host.old_redis, kind="source")
    original = source.tail(OLD_DAY)
    successor = source.append(ObservationEnvelope(
        "next", OLD_DAY, host.now(), "live:bar:rb:1m", {}, True,
    ))
    source.ack("live", OLD_DAY, expected_cursor=original, next_id=successor)
    host.old_redis.xdel(source.key(OLD_DAY), original)
    host.old_redis.hdel(source.identity_key(OLD_DAY), "old")
    with pytest.raises(CohortError, match="MARKET_SOURCE_RETENTION_GAP"):
        old_observation_snapshot(host.old_redis, OLD_DAY, alert_enabled=True, check_budget=lambda: None)



def test_staging_refuses_redis_client_with_transparent_retries(tmp_path, redis_pair):
    host = IsolatedHost(tmp_path, *redis_pair)
    port = host.target.connection_pool.connection_kwargs["port"]
    with Redis(host="127.0.0.1", port=port) as retrying:
        with pytest.raises(ValueError, match="MARKET_TICK_INITIAL_RETRY_FORBIDDEN"):
            stage_new_observations(
                retrying, host.database, host.canonical, old_instance=redis_instance(host.old_redis),
                **host.target_arguments(_plan(host)),
            )
    assert host.target.dbsize() == 0


def test_macos_account_job_rejects_program_override(tmp_path, monkeypatch):
    import plistlib
    from app import runtime_market_macos as macos

    label = macos.SUBING_PAPER_LABEL
    agents = tmp_path / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    args = ("/bin/bash", "expected-script")
    (agents / f"{label}.plist").write_bytes(plistlib.dumps({
        "Label": label, "ProgramArguments": list(args), "Program": "/usr/bin/false",
        "WorkingDirectory": str(tmp_path),
    }))
    def launchd(*_args, **_kwargs):
        pytest.fail("unexpected launchd read for invalid installed launcher")
    monkeypatch.setattr(macos, "read_launchd_service", launchd)
    with pytest.raises(CohortError, match="MARKET_HANDOFF_ACCOUNT_LAUNCHER_MISMATCH"):
        macos._job(tmp_path, label, args, tmp_path)


def test_macos_account_job_recognizes_exact_definition_waiting_for_its_first_pid(tmp_path, monkeypatch):
    import plistlib
    from app import runtime_market_macos as macos

    label = macos.SUBING_PAPER_LABEL
    agents = tmp_path / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    args = ("/bin/bash", "expected-script")
    (agents / f"{label}.plist").write_bytes(plistlib.dumps({
        "Label": label, "ProgramArguments": list(args), "WorkingDirectory": str(tmp_path),
    }))
    output = (f"gui/501/{label} = {{\n\tstate = spawn scheduled\n\tprogram = /bin/bash\n"
              f"\tworking directory = {tmp_path}\n\targuments = {{\n\t\t/bin/bash\n"
              "\t\texpected-script\n\t}\n\tenvironment = {\n\t}\n}")
    monkeypatch.setattr(macos, "read_launchd_service", lambda *_args, **_kwargs: output)
    with pytest.raises(CohortError, match="MARKET_HANDOFF_ACCOUNT_STARTING"):
        macos._job(tmp_path, label, args, tmp_path)


def test_macos_unknown_outcome_attempts_each_account_stop_independently(tmp_path, monkeypatch):
    from dataclasses import asdict

    from app.runtime_cohort_host import CohortHost
    from app.runtime_market_cohort_host import MarketCohortHost, _ACCOUNTS

    fixture = Host(tmp_path)
    native = MarketCohortHost()
    native.directory = fixture.directory
    native._successor_start_requests = ["tqkq", "subing"]
    plan = {"new": asdict(fixture.old)}
    monkeypatch.setattr(native, "bindings", lambda: fixture.old)
    monkeypatch.setattr(CohortHost, "halt_unknown", lambda *_args: None)
    subing_label, subing_folder = _ACCOUNTS["subing"]
    directory = native.directory / subing_folder
    directory.mkdir(mode=0o700)
    native._private_original(directory / "owner.lock", b"")
    requests = []

    def launch(action, target):
        requests.append((action, target.rsplit("/", 1)[1]))
        if target.endswith(_ACCOUNTS["tqkq"][0]):
            raise OSError("isolated TQ launchctl failure")

    monkeypatch.setattr(native, "launch", launch)
    monkeypatch.setattr(native, "_account_absent", lambda name: name == "subing" and ("bootout", subing_label) in requests)
    assert native.halt_unknown(plan)["account_stops"] == {"tqkq": "unproven", "subing": "stopped"}
    assert requests[-2:] == [("disable", subing_label), ("bootout", subing_label)]
