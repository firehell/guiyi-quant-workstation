from datetime import UTC, date, datetime, timedelta

import pytest

from app.market_data.contract_preparation import ContractPreparation, PreparationDemand, PreparationPlan

NOW = datetime(2026, 10, 26, 13, tzinfo=UTC)
DAY = date(2026, 10, 27)


def demand(frequencies=("5m",), through=date(2026, 10, 26), fingerprint="scope"):
    return PreparationDemand("rb", "RB2701", DAY, date(2026, 1, 1), date(2027, 1, 16), through,
                             frequencies, fingerprint)


def system(tmp_path, *, demands=None, result=None, ready=True, busy=False, clock=None, costs=(1, 100)):
    calls = []
    demands = demands if demands is not None else [demand()]
    def plan(item, frequency, check):
        calls.append(("plan", frequency))
        check()
        return PreparationPlan("a" * 64, *costs)
    def apply(item, frequency, frozen, reserve, check):
        if busy:
            return {"status": "busy"}
        reserve()
        calls.append(("apply", frequency))
        check()
        if isinstance(result, BaseException):
            raise result
        return result or {"status": "passed", "applied": 1}
    def readback(item, frequency):
        calls.append(("readback", frequency))
        return ready
    service = ContractPreparation(state_path=tmp_path / "state.json", binding_id="test", discover=lambda now: demands,
                                  plan=plan, apply=apply, readback=readback, monotonic=clock)
    return service, calls


def test_discovery_deduplicates_after_restart_and_readiness_requires_readback(tmp_path):
    service, calls = system(tmp_path)
    service.tick(NOW)
    assert calls == [("plan", "5m"), ("apply", "5m"), ("readback", "5m")]
    assert next(iter(service.snapshot()["requests"].values()))["units"]["5m"]["status"] == "READY"
    restarted, calls = system(tmp_path)
    restarted.tick(NOW)
    assert calls == []


def test_lease_busy_consumes_no_attempt_or_budget(tmp_path):
    service, _ = system(tmp_path, busy=True)
    service.tick(NOW)
    item = next(iter(service.snapshot()["requests"].values()))["units"]["5m"]
    assert item["status"] == "WAITING_LEASE"
    assert item["attempts"] == 0
    assert service.snapshot()["budgets"] == {}


@pytest.mark.parametrize("result", [{"status": "partial", "applied": 1}, {"status": "failed"}, ValueError("PROVIDER_SECRET_URL")])
def test_failed_partial_unknown_never_retry(tmp_path, result):
    service, _ = system(tmp_path, result=result)
    service.tick(NOW)
    restarted, calls = system(tmp_path)
    restarted.tick(NOW + timedelta(hours=2))
    assert calls == []
    item = next(iter(restarted.snapshot()["requests"].values()))["units"]["5m"]
    assert item["status"] == "READBACK_REQUIRED"


def test_inflight_crash_reserves_before_provider_and_restart_never_retries(tmp_path):
    service, _ = system(tmp_path, result=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        service.tick(NOW)
    restarted, calls = system(tmp_path)
    restarted.tick(NOW)
    assert calls == []
    assert next(iter(restarted.snapshot()["requests"].values()))["units"]["5m"]["status"] == "READBACK_REQUIRED"


def test_only_source_not_ready_receives_one_retry_after_hour(tmp_path):
    result = {"status": "failed", "applied": 0, "reason": "RQDATA_NOT_READY"}
    service, calls = system(tmp_path, result=result)
    service.tick(NOW)
    service.tick(NOW + timedelta(minutes=59))
    assert len([x for x in calls if x[0] == "apply"]) == 1
    service.tick(NOW + timedelta(hours=1))
    service.tick(NOW + timedelta(hours=2))
    assert len([x for x in calls if x[0] == "apply"]) == 2


def test_frequency_failure_does_not_hide_intraday_readiness(tmp_path):
    service, _ = system(tmp_path, demands=[demand(("5m", "1w"))], ready=False)
    def applied(item, frequency, frozen, reserve, check):
        reserve()
        return {"status": "failed", "applied": 0} if frequency == "1w" else {"status": "passed"}
    service.apply = applied
    service.readback = lambda item, frequency: frequency == "5m"
    service.tick(NOW)
    units = next(iter(service.snapshot()["requests"].values()))["units"]
    assert units["5m"]["status"] == "READY"
    assert units["1w"]["status"] == "READBACK_REQUIRED"


def test_contract_and_day_budget_reserved_before_source(tmp_path):
    service, calls = system(tmp_path, demands=[demand(("5m", "15m"))], costs=(40, 100))
    service.tick(NOW)
    assert len([x for x in calls if x[0] == "apply"]) == 1
    units = next(iter(service.snapshot()["requests"].values()))["units"]
    assert units["15m"]["status"] == "BUDGET_EXCEEDED"


def test_request_only_records_hint_and_cannot_expand_discovery(tmp_path):
    service, calls = system(tmp_path, demands=[])
    service.request("cu", "CU2701", DAY, ("1w",))
    assert calls == []
    service.tick(NOW)
    assert calls == []
    assert service.snapshot()["requests"] == {}


def test_elapsed_budget_checked_before_source(tmp_path):
    times = iter([0, 1201, 1201])
    service, calls = system(tmp_path, clock=lambda: next(times))
    service.tick(NOW)
    assert not any(x[0] == "apply" for x in calls)


def test_state_binding_mismatch_and_corrupt_state_fail_closed(tmp_path):
    service, _ = system(tmp_path)
    service.tick(NOW)
    other, calls = system(tmp_path)
    other.binding_id = "other"
    assert other.tick(NOW) == "CONTRACT_PREPARATION_STATE_INVALID"
    assert calls == []


def test_success_receipt_without_independent_readback_is_not_ready(tmp_path):
    service, _ = system(tmp_path, ready=False)
    service.tick(NOW)
    unit = next(iter(service.snapshot()["requests"].values()))["units"]["5m"]
    assert unit["status"] == "READBACK_REQUIRED"
    assert unit["reason"] == "CONTRACT_PREPARATION_READBACK_FAILED"


def test_shared_minute_source_failure_cannot_retry_via_other_consumer_frequency(tmp_path):
    service, calls = system(tmp_path, demands=[demand(("5m", "15m"))], result={"status": "partial", "applied": 1})
    service.tick(NOW)
    assert len([item for item in calls if item[0] == "apply"]) == 1
    units = next(iter(service.snapshot()["requests"].values()))["units"]
    assert units["15m"]["reason"] == "PRIOR_ATTEMPT_UNRESOLVED"


def test_advancing_cutoff_cannot_clear_unknown_attempt(tmp_path):
    original = demand()
    service, _ = system(tmp_path, demands=[original], result={"status": "failed"})
    service.tick(NOW)
    next_cutoff = PreparationDemand("rb", "RB2701", date(2026, 10, 28), original.listed_date,
                                    original.expired_date, date(2026, 10, 27), ("5m",), "scope")
    restarted, calls = system(tmp_path, demands=[next_cutoff])
    restarted.tick(NOW + timedelta(days=1))
    assert calls == []


def test_day_budget_is_shared_by_independent_contracts(tmp_path):
    demands = [PreparationDemand(product, contract, DAY, date(2026, 1, 1), date(2027, 1, 16),
                                  date(2026, 10, 26), ("1d",), "scope")
               for product, contract in (("rb", "RB2701"), ("cu", "CU2701"), ("al", "AL2701"), ("jm", "JM2701"), ("j", "J2701"))]
    service, calls = system(tmp_path, demands=demands, costs=(64, 100))
    service.tick(NOW)
    assert len([item for item in calls if item[0] == "apply"]) == 4
    assert service.snapshot()["budgets"][DAY.isoformat()]["requests"] == 256


def test_expected_bar_budget_exhaustion_has_no_source_attempt(tmp_path):
    service, calls = system(tmp_path, costs=(1, 2_000_001))
    service.tick(NOW)
    assert not any(item[0] == "apply" for item in calls)
    assert service.snapshot()["budgets"] == {}


def test_snapshot_rejects_tampered_identity_before_planning(tmp_path):
    import json
    service, _ = system(tmp_path)
    service.tick(NOW)
    state = service.snapshot()
    next(iter(state["requests"].values()))["identity"]["contract"] = "RB2705"
    service.path.write_text(json.dumps(state))
    restarted, calls = system(tmp_path)
    assert restarted.tick(NOW) == "CONTRACT_PREPARATION_STATE_INVALID"
    assert calls == []


def test_superseded_ready_records_archive_without_losing_attempt_evidence(tmp_path):
    original = demand()
    service, _ = system(tmp_path, demands=[original])
    service.tick(NOW)
    later = PreparationDemand("rb", "RB2701", date(2026, 10, 28), original.listed_date,
                              original.expired_date, date(2026, 10, 27), original.frequencies, "scope")
    service.discover = lambda now: (later,)
    service.tick(NOW + timedelta(days=1))
    state = service.snapshot()
    assert set(state["requests"]) == {later.key}
    scope_key, proof = next(iter(state["archives"].items()))
    archived = service._read_archive(scope_key, proof)
    assert archived["request_key"] == original.key
    assert archived["record"]["units"]["5m"]["history"][0]["plan_sha256"] == "a" * 64
    assert archived["previous"] is None
    # Restart never re-executes the retained latest READY cutoff.
    restarted, calls = system(tmp_path, demands=[later])
    restarted.tick(NOW + timedelta(days=1))
    assert calls == []


def test_archive_corruption_blocks_new_mutation_and_keeps_current_record(tmp_path):
    original = demand()
    service, _ = system(tmp_path, demands=[original])
    service.tick(NOW)
    later = PreparationDemand("rb", "RB2701", date(2026, 10, 28), original.listed_date,
                              original.expired_date, date(2026, 10, 27), original.frequencies, "scope")
    service.discover = lambda now: (later,)
    service.tick(NOW + timedelta(days=1))
    proof = next(iter(service.snapshot()["archives"].values()))
    path = service.archive_root / proof["file"]
    path.chmod(0o600)
    path.write_text("{}")
    restarted, calls = system(tmp_path, demands=[later])
    assert restarted.tick(NOW + timedelta(days=1)) == "CONTRACT_PREPARATION_STATE_INVALID"
    assert calls == []


def test_failed_archive_write_never_removes_online_proof(tmp_path, monkeypatch):
    original = demand()
    service, _ = system(tmp_path, demands=[original])
    service.tick(NOW)
    later = PreparationDemand("rb", "RB2701", date(2026, 10, 28), original.listed_date,
                              original.expired_date, date(2026, 10, 27), original.frequencies, "scope")
    service.discover = lambda now: (later,)
    def fail(*args):
        raise ValueError("CONTRACT_PREPARATION_ARCHIVE_INVALID")
    monkeypatch.setattr(service, "_archive", fail)
    assert service.tick(NOW + timedelta(days=1)) == "CONTRACT_PREPARATION_ARCHIVE_INVALID"
    assert set(service.snapshot()["requests"]) == {original.key, later.key}


def test_retry_retains_first_attempt_hash_and_failure(tmp_path):
    service, _ = system(tmp_path, result={"status": "failed", "applied": 0, "reason": "RQDATA_NOT_READY"})
    service.tick(NOW)
    service.tick(NOW + timedelta(hours=1))
    unit = next(iter(service.snapshot()["requests"].values()))["units"]["5m"]
    assert len(unit["history"]) == 2
    assert unit["history"][0]["reason"] == "RQDATA_NOT_READY"
    assert unit["history"][0]["status"] == "WAITING_SOURCE"
    assert unit["history"][1]["status"] == "READBACK_REQUIRED"


def test_shared_source_wait_does_not_block_its_own_one_hour_retry(tmp_path):
    service, calls = system(tmp_path, demands=[demand(("5m", "15m"))])
    first = True
    def applied(item, frequency, frozen, reserve, check):
        nonlocal first
        reserve()
        calls.append(("apply", frequency))
        if first:
            first = False
            return {"status": "failed", "applied": 0, "reason": "RQDATA_NOT_READY"}
        return {"status": "passed", "applied": 1}
    service.apply = applied
    service.tick(NOW)
    unit = next(iter(service.snapshot()["requests"].values()))["units"]["15m"]
    assert unit["status"] == "WAITING_DEPENDENCY"
    assert unit["attempts"] == 0
    service.tick(NOW + timedelta(hours=1))
    units = next(iter(service.snapshot()["requests"].values()))["units"]
    assert units["5m"]["status"] == units["15m"]["status"] == "READY"
    assert [item for item in calls if item[0] == "apply"] == [("apply", "5m"), ("apply", "5m"), ("apply", "15m")]


def test_native_noop_requires_readback_and_does_not_spend_provider_budget(tmp_path):
    service, calls = system(tmp_path, result={"status": "noop", "applied": 0}, costs=(0, 0))
    service.tick(NOW)
    unit = next(iter(service.snapshot()["requests"].values()))["units"]["5m"]
    assert unit["status"] == "READY"
    assert calls[-1] == ("readback", "5m")
    assert service.snapshot()["budgets"][DAY.isoformat()]["requests"] == 0


def test_ready_hint_forces_fresh_readonly_readback_and_never_reapplies(tmp_path):
    service, calls = system(tmp_path)
    service.tick(NOW)
    calls.clear()
    service.request("rb", "RB2701", DAY, ("5m",))
    service.readback = lambda *args: False
    service.tick(NOW)
    assert calls == []  # Even native planning/apply would be an unintended retry.
    unit = next(iter(service.snapshot()["requests"].values()))["units"]["5m"]
    assert unit["status"] == "READBACK_REQUIRED"
    assert unit["reason"] == "CONTRACT_PREPARATION_READY_INPUT_DRIFT"
    restarted, calls = system(tmp_path)
    restarted.request("rb", "RB2701", DAY, ("5m",))
    restarted.tick(NOW + timedelta(hours=2))
    assert calls == []
