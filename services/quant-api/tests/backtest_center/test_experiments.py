"""Experiment orchestration and information boundaries over the durable Run repository."""

from datetime import date, timedelta
import sqlite3

import pytest
from pydantic import ValidationError

from app.backtest_center.contracts import BacktestError
from app.backtest_center.experiments import (
    ExperimentRequest,
    advance_experiments,
    create_experiment,
    list_experiments,
    read_experiment,
)
from app.backtest_center.store import RunStore

BASE = {
    "strategy_id": "newow_trend",
    "product": "fu",
    "contract": "FU2603",
    "warmup_start": "2026-01-02",
    "start": "2026-02-02",
    "end": "2026-02-03",
    "signal_frequency": "5m",
    "initial_capital": "100",
}
FOLD = {
    "train_warmup_start": "2026-01-02",
    "train_start": "2026-02-02",
    "train_end": "2026-02-03",
    "test_warmup_start": "2026-01-05",
    "test_start": "2026-02-04",
    "test_end": "2026-02-05",
}
LATER_FOLD = {
    "train_warmup_start": "2026-01-05",
    "train_start": "2026-02-04",
    "train_end": "2026-02-05",
    "test_warmup_start": "2026-01-06",
    "test_start": "2026-02-06",
    "test_end": "2026-02-09",
}


def request(kind="comparison", configs=None, folds=None, **extra):
    return ExperimentRequest.model_validate(
        {
            "request_key": "one-user-gesture",
            "kind": kind,
            "axes": ["commission"],
            "metric": "net_return",
            "configs": configs or [BASE, {**BASE, "commission_multiplier": "2"}],
            "folds": folds or [],
            **extra,
        }
    )


def publish(
    store,
    last_equity,
    *,
    failed=False,
    revision="native-v1",
    physical_digest="contract-v1",
    valuation_hour="15",
    opening=None,
    include_future=False,
    trades=(),
    terminal_position=None,
    effective_days=None,
    snapshot_days=True,
    native_settlement_repr=None,
):
    run = store.claim()
    assert run is not None
    run_id, config = run["run_id"], run["config"]
    if failed:
        store.finish_stopped(run_id, "PLUS_EXECUTION_MINUTES_MISSING")
        return run
    start, end = date.fromisoformat(config["start"]), date.fromisoformat(config["end"])
    opening = opening or f"{start - timedelta(days=1)}T21:00:00+08:00"
    days = effective_days or [start.isoformat(), end.isoformat()]
    store.admit(
        run_id,
        {
            "data_revision": revision,
            "input_sha256": f"{revision}:{config['warmup_start']}:{start}:{end}",
            "code_revision": "test-code",
            "code_sha256": "test-code-sha",
            "execution_policy": "test-execution",
            "data_files": {config["contract"] + ".h5": physical_digest},
            "engine": "test-engine",
            "qualification": "TRIAL",
            **({"evaluation_trading_days": days} if snapshot_days else {}),
        },
    )
    valuations = [
        {"at": f"{day}T{valuation_hour}:00:00+08:00", "equity": equity, "trading_day": day}
        for day, equity in zip(days, ("100", last_equity), strict=True)
    ]
    settlements = [
        {"at": row["at"], "trading_day": row["trading_day"],
         "after": {"native_equity": {"repr": native_settlement_repr or row["equity"]}}}
        for row in valuations
    ]
    if include_future:
        future = end + timedelta(days=1)
        valuations.append({"trading_day": str(future), "at": f"{future}T15:00:00+08:00", "equity": "500"})
    store.publish(
        run_id,
        {
            "summary": {"metrics": {"trade_count": {"value": str(len(trades))}, "net_return": {"value": "999"}}},
            "report": {
                "evaluation_trading_days": days,
                "evaluation_initial_position": "FLAT",
                "evaluation_initial_equity": "100",
                "first_evaluation_session_open": opening,
                "terminal_position": terminal_position,
                "native_settlements": settlements,
            },
            "equity": valuations,
            "trades": list(trades),
        },
    )
    return run


def test_comparison_persists_request_and_checks_control_conditions(tmp_path):
    store = RunStore(tmp_path / "results.sqlite3")
    chosen = create_experiment(store, request())
    replayed = create_experiment(RunStore(store.path), request())
    assert chosen == replayed
    with pytest.raises(BacktestError, match="EXPERIMENT_REQUEST_KEY_CONFLICT"):
        create_experiment(store, request(metric="max_drawdown"))
    assert list_experiments(store, kind="walk_forward", limit=10, offset=0)["total"] == 0
    assert list_experiments(store, kind="comparison", limit=10, offset=0)["total"] == 1
    experiment_id = chosen["experiment_id"]
    assert read_experiment(store, experiment_id)["status"] == "QUEUED"
    assert store.list(limit=10, offset=0)["total"] == 0
    advance_experiments(store)
    publish(store, "105")
    publish(store, "110", revision="native-v2")
    advance_experiments(store)
    result = read_experiment(store, experiment_id)
    assert result["status"] == "INSUFFICIENT"
    assert result["comparison"]["condition_differences"] == ["data_revision", "input_sha256"]
    assert result["members"][0]["metrics"]["net_return"] == "0.05"
    assert result["comparison"]["ranked_member_ids"] == []


def test_restart_reuses_run_committed_before_experiment_update(tmp_path, monkeypatch):
    store = RunStore(tmp_path / "results.sqlite3")
    experiment_id = create_experiment(store, request())["experiment_id"]
    submit = store.submit

    def lost_ack(*args, **kwargs):
        submit(*args, **kwargs)
        raise sqlite3.OperationalError

    monkeypatch.setattr(store, "submit", lost_ack)
    with pytest.raises(sqlite3.OperationalError):
        advance_experiments(store)
    only_run = store.list(limit=10, offset=0)["items"][0]["run_id"]
    restarted = RunStore(store.path)
    advance_experiments(restarted)
    assert restarted.list(limit=10, offset=0)["total"] == 2
    state = read_experiment(restarted, experiment_id)
    assert state["members"][0]["run_id"] == only_run
    publish(restarted, "102")
    publish(restarted, "103", failed=True)
    advance_experiments(restarted)
    result = read_experiment(restarted, experiment_id)
    assert result["comparison"]["failed_members"] == 1
    assert result["members"][1]["diagnostic"] == "PLUS_EXECUTION_MINUTES_MISSING"
    assert result["comparison"]["ranked_member_ids"] == []


@pytest.mark.parametrize("test_close", ["1", "180"])
def test_oos_selection_commits_before_test_and_cannot_see_test_close(tmp_path, test_close):
    store = RunStore(tmp_path / "results.sqlite3")
    experiment_id = create_experiment(store, request("oos", folds=[FOLD]))["experiment_id"]
    advance_experiments(store)
    terminal_position = {
        "contract": "FU2603",
        "direction": "LONG",
        "quantity": 1,
        "mark_price": "2103",
        "marked_at": "2026-02-03T15:00:00+08:00",
        "unrealized_pnl": "6",
    }
    publish(
        store,
        "106",
        trades=({"trade_id": "open-at-train-boundary", "position_effect": "OPEN"},),
        terminal_position=terminal_position,
    )
    publish(store, "103")
    advance_experiments(store)
    selected = read_experiment(store, experiment_id)
    fold = selected["folds"][0]
    assert fold["status"] == "SELECTED" and fold["selected_at"]
    assert fold["selection_cutoff"] == "2026-02-03T17:00:00+08:00"
    assert fold["selection_valuation_at"] == "2026-02-03T15:00:00+08:00"
    assert fold["boundary_policy"] == "settlement_mark_then_flat_start_v1"
    assert fold["training_boundary_position"] == terminal_position
    assert selected["members"][-1]["run_id"] is None
    assert store.list(limit=10, offset=0)["total"] == 2

    advance_experiments(RunStore(store.path))
    run = publish(
        store,
        test_close,
        trades=(
            {"trade_id": "test-only-open", "position_effect": "OPEN"},
            {"trade_id": "test-only-close", "position_effect": "CLOSE", "price": test_close},
        ),
    )
    assert run["config"]["commission_multiplier"] == "1"
    assert run["config"]["start"] == FOLD["test_start"]
    assert run["config"]["end"] == FOLD["test_end"]
    advance_experiments(store)
    evidence = read_experiment(store, experiment_id)["evidence"]
    assert evidence["status"] == "SUCCEEDED"
    assert evidence["missing_folds"] == []
    assert [p["trading_day"] for p in evidence["curve"]] == [FOLD["test_start"], FOLD["test_end"]]
    assert evidence["folds"][0]["selected_member_id"] == selected["members"][0]["member_id"]
    assert evidence["folds"][0]["test_initial_position"] == "FLAT"


@pytest.mark.parametrize("clock_test", [False, True])
def test_oos_rejects_valuation_leakage_and_clock_overlap(tmp_path, clock_test):
    store = RunStore(tmp_path / "results.sqlite3")
    experiment_id = create_experiment(store, request("oos", folds=[FOLD]))["experiment_id"]
    advance_experiments(store)
    publish(store, "110", include_future=not clock_test, valuation_hour="22" if clock_test else "15")
    publish(store, "105")
    advance_experiments(store)
    evidence = read_experiment(store, experiment_id)["evidence"]
    assert evidence["status"] == "INSUFFICIENT"
    assert evidence["missing_folds"] == [1]
    assert evidence["curve"] == []
    reason = evidence["folds"][0]["diagnostic"]
    assert reason == (
        "EXPERIMENT_TRAINING_SETTLEMENT_AFTER_CUTOFF" if clock_test else "EXPERIMENT_TRAINING_NOT_COMPARABLE"
    )


def test_walk_forward_marks_failed_folds_without_double_counting(tmp_path):
    store = RunStore(tmp_path / "results.sqlite3")
    experiment_id = create_experiment(store, request("walk_forward", folds=[FOLD, LATER_FOLD]))["experiment_id"]
    advance_experiments(store)
    for equity in ("105", "103", "104", "107"):
        publish(store, equity)
    advance_experiments(store)
    advance_experiments(store)
    assert publish(store, "110")["config"]["commission_multiplier"] == "1"
    assert publish(store, "110", failed=True)["config"]["commission_multiplier"] == "2"
    advance_experiments(store)
    result = read_experiment(store, experiment_id)
    assert result["evidence"]["missing_folds"] == [2]
    assert result["evidence"]["metrics"]["trading_days"] == 2
    assert result["evidence"]["metrics"]["net_return"] == "0.1"
    assert result["folds"][1]["status"] == "INSUFFICIENT"
    with pytest.raises(ValidationError, match="EXPERIMENT_FOLDS_OVERLAP_OR_UNORDERED"):
        request("walk_forward", folds=[FOLD, {**LATER_FOLD, "train_end": "2026-02-04", "test_start": "2026-02-05"}])


def test_test_session_must_open_after_frozen_cutoff(tmp_path):
    store = RunStore(tmp_path / "results.sqlite3")
    experiment_id = create_experiment(store, request("oos", folds=[FOLD]))["experiment_id"]
    advance_experiments(store)
    publish(store, "110")
    publish(store, "105")
    advance_experiments(store)
    advance_experiments(store)
    publish(store, "110", opening="2026-02-03T16:00:00+08:00")
    advance_experiments(store)
    evidence = read_experiment(store, experiment_id)["evidence"]
    assert evidence["status"] == "INSUFFICIENT"
    assert evidence["curve"] == []
    assert evidence["folds"][0]["diagnostic"] == "EXPERIMENT_TRAIN_TEST_CLOCK_OVERLAP"


def test_experiment_api_mutation_and_evidence_are_local_and_readable(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.backtest_experiments import router, get_store

    app = FastAPI()
    store = RunStore(tmp_path / "results.sqlite3")
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: store
    path = "/api/v1/backtests/experiments"
    payload = request("oos", folds=[FOLD]).model_dump(mode="json")
    with TestClient(app) as client:
        assert client.post(path, json=payload, headers={"Origin": "https://example.net"}).status_code == 403
        response = client.post(path, json=payload)
        assert response.status_code == 202
        experiment_id = response.json()["experiment_id"]
        assert client.post(path, json=payload).json()["experiment_id"] == experiment_id
        assert client.get(f"{path}?kind=oos").json()["total"] == 1
        assert client.get(f"{path}/{experiment_id}/evidence").status_code == 409
        assert store.list(limit=10, offset=0)["total"] == 0

        advance_experiments(store)
        publish(store, "110", failed=True)
        publish(store, "105", failed=True)
        advance_experiments(store)
        assert client.get(f"{path}/{experiment_id}").json()["status"] == "INSUFFICIENT"
        data = client.get(f"{path}/{experiment_id}/evidence")
        assert data.status_code == 200
        assert data.json()["scope"] == "historical_research"
        assert data.json()["missing_folds"] == [1]
        assert len(data.json()["run_ids"]) == 2


def test_oos_retains_test_run_when_minute_file_revision_changed(tmp_path):
    store = RunStore(tmp_path / "results.sqlite3")
    experiment_id = create_experiment(store, request("oos", folds=[FOLD]))["experiment_id"]
    advance_experiments(store)
    publish(store, "110")
    publish(store, "105")
    advance_experiments(store)
    advance_experiments(store)
    test = publish(store, "110", physical_digest="contract-v2")
    advance_experiments(store)
    evidence = read_experiment(store, experiment_id)["evidence"]
    assert evidence["status"] == "INSUFFICIENT"
    assert test["run_id"] in evidence["run_ids"]
    assert evidence["curve"] == []
    assert evidence["folds"][0]["diagnostic"] == "EXPERIMENT_TRAIN_TEST_INPUT_DRIFT"


@pytest.mark.parametrize("bad_terms", [{"valuation_hour": "09"}, {"snapshot_days": False},
                                       {"native_settlement_repr": "1000"}])
def test_b4_requires_a_frozen_native_settlement_match(tmp_path, bad_terms):
    store = RunStore(tmp_path / "results.sqlite3")
    chosen = create_experiment(store, request())
    advance_experiments(store)
    invalid = publish(store, "105", **bad_terms)["run_id"]
    publish(store, "104")
    advance_experiments(store)
    result = read_experiment(store, chosen["experiment_id"])
    assert result["comparison"]["ranked_member_ids"] == []
    assert result["members"][0]["status"] == "INSUFFICIENT"
    assert result["evidence"]["status"] == "INSUFFICIENT"
    assert invalid in result["evidence"]["run_ids"]


def test_comparison_rejects_different_effective_days_within_the_same_requested_window(tmp_path):
    store = RunStore(tmp_path / "results.sqlite3")
    base = {**BASE, "end": "2026-02-05"}
    chosen = create_experiment(store, request(configs=[base, {**base, "commission_multiplier": "2"}]))
    advance_experiments(store)
    publish(store, "106", effective_days=["2026-02-02", "2026-02-05"])
    publish(store, "104", effective_days=["2026-02-03", "2026-02-05"])
    advance_experiments(store)
    result = read_experiment(store, chosen["experiment_id"])
    assert result["comparison"]["condition_differences"] == ["evaluation_trading_days"]
    assert result["evidence"]["comparison"]["ranked_member_ids"] == []


def test_legacy_comparison_gets_strict_evidence_without_rewriting_its_record(tmp_path):
    import json

    from app.backtest_center.codec import encode

    store = RunStore(tmp_path / "results.sqlite3")
    chosen = create_experiment(store, request())
    advance_experiments(store)
    publish(store, "108")
    publish(store, "104")
    advance_experiments(store)
    current = read_experiment(store, chosen["experiment_id"])
    legacy = {**current, "evidence": None}
    path = store.path.with_name(store.path.name + ".experiments.sqlite3")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE experiments SET state=?", (encode(legacy),))
    result = read_experiment(store, chosen["experiment_id"])
    assert result["evidence"] == current["evidence"]
    with sqlite3.connect(path) as db:
        assert json.loads(db.execute("SELECT state FROM experiments").fetchone()[0])["evidence"] is None
