from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.backtest_center.errors import BacktestError
from app.backtest_center.incremental import VERSION, Continuation, cost_prefix, execution_identity
from app.backtest_center.worker import Settings, Worker, _checkpoint_mac, _local_key

FIRST = date(2026, 1, 9)
NEXT = date(2026, 1, 12)
SETTLEMENT = "2026-01-09T15:30:00+08:00"
NIGHT = datetime.fromisoformat("2026-01-09T21:00:00+08:00")


def test_resume_requires_unchanged_market_costs_and_next_session():
    costs = SimpleNamespace(rows={FIRST: {"fee": "1"}}, margin_at_settlement={FIRST: {"margin": "0.15"}})
    packet = SimpleNamespace(
        days={FIRST: None, NEXT: None}, prefix_by_day={FIRST: "stable", NEXT: "extended"},
        sessions=[SimpleNamespace(day=NEXT, start=NIGHT)],
    )
    identity = execution_identity({"end": FIRST.isoformat(), "contract": "FU2603"}, packet, costs)
    assert identity == execution_identity({"end": NEXT.isoformat(), "contract": "FU2603"}, packet, costs)
    source = {
        "run_id": "source",
        "checkpoint": {"version": VERSION, "through": FIRST.isoformat(), "settled_at": SETTLEMENT,
                       "market_prefix": "stable", "cost_prefix": cost_prefix(costs, FIRST),
                       "execution_identity": identity},
        "result": {"equity": [{"trading_day": FIRST.isoformat()}],
                   "report": {"native_settlements": [{"at": SETTLEMENT, "trading_day": FIRST.isoformat()}]}},
    }
    assert Continuation.verify(source, packet, costs, identity).through == FIRST
    packet.sessions.clear()
    with pytest.raises(BacktestError, match="BACKTEST_INCREMENTAL_NO_NEW_TRADING_DAY"):
        Continuation.verify(source, packet, costs, identity)
    packet.sessions.append(SimpleNamespace(day=NEXT, start=NIGHT))
    for field in ("market_prefix", "cost_prefix", "execution_identity"):
        changed = {**source, "checkpoint": {**source["checkpoint"], field: "changed"}}
        with pytest.raises(BacktestError, match="BACKTEST_INCREMENTAL_PREFIX_CHANGED"):
            Continuation.verify(changed, packet, costs, identity)


def test_worker_binds_opaque_state_to_local_key_source_snapshot_and_result(tmp_path):
    source_id, result, snapshot = "source", {"equity": [{"equity": "99"}]}, {"code_sha256": "original"}
    archived = {"run": {"snapshot": snapshot}, "result": result}
    store = SimpleNamespace(path=tmp_path / "private.sqlite", extension_source=lambda _: archived)
    worker = Worker(Settings(store.path, None, None), store)
    checkpoint = {"native": {"portfolio": "opaque"}, "through": FIRST.isoformat()}
    key = _local_key(worker.checkpoint_key, create=True)
    archived["checkpoint"] = {**checkpoint, "hmac": _checkpoint_mac(key, source_id, snapshot, result, checkpoint)}
    assert worker._continuation(source_id) == ({"run_id": source_id, "result": result, "checkpoint": checkpoint}, snapshot)
    for field, value in (
        ("run", {"snapshot": {"code_sha256": "edited"}}),
        ("result", {"equity": [{"equity": "100"}]}),
        ("checkpoint", {**archived["checkpoint"], "native": {"portfolio": "edited"}}),
    ):
        original = archived[field]
        archived[field] = value
        with pytest.raises(BacktestError, match="BACKTEST_CHECKPOINT_UNAUTHENTICATED"):
            worker._continuation(source_id)
        archived[field] = original
    worker.checkpoint_key.unlink()
    with pytest.raises(BacktestError, match="BACKTEST_CHECKPOINT_UNAUTHENTICATED"):
        worker._continuation(source_id)
