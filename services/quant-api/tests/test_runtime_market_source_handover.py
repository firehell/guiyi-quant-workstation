from datetime import UTC, date, datetime
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
def test_macos_uses_the_owner_socket_on_the_actual_target_redis(redis_pair):
    from app.runtime_market_cohort_host import _connects_to
    from guiyi_quant.trading_universe import TRADING_PRODUCTS

    old, target = redis_pair
    port = target.connection_pool.connection_kwargs["port"]
    channels = [f"live:bar:{name}:60m" for name in TRADING_PRODUCTS]
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
            assert _connects_to(target, owner.pid)
            assert not _connects_to(old, owner.pid)
        finally:
            owner.stdin.close()


def test_macos_restores_exact_config_after_known_pre_cas_failure_with_expired_apply_budget(tmp_path, redis_pair, monkeypatch):
    from hashlib import sha256
    from time import monotonic

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
