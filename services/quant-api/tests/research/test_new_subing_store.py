import pytest

from app.new_subing_research.store import (
    ResultStoreError,
    list_results,
    page_result,
    publish_result,
    read_result,
)


def packet():
    return {
        "schema_version": 1,
        "metadata": {
            "product": "AL", "scenario": "baseline", "status": "COMPLETED",
            "strategy_code": "new_subing_v1", "formula_version": "new_subing_formula_v1",
            "profile_id": "new_subing_fixed_v1", "risk_profile_version": "new_subing_risk_v1",
            "execution_profile_version": "new_subing_next_1m_open_v1",
            "code_revision": "a" * 40, "requested_since": "2024-10-14",
            "requested_through": "2026-10-09", "input_snapshot_hash": "b" * 64,
            "execution_facts_hash": "c" * 64, "source": "historical_replay",
            "auto_order": False, "case_parity": "PENDING", "oos_status": "NOT_PROVEN",
        },
        "summary": {"status": "COMPLETED", "initial_cash": "100000", "final_equity": "100010", "account_return_pct": "0.01", "max_drawdown_pct": "0", "closed_trades": 0, "total_fees": "0", "ending_qty": 0, "annual_eligible": True},
        "decisions": [{"decision_id": "d1", "at": "2025-01-01T09:00:00+08:00", "action": "REJECT", "side": "LONG", "reason": "NO_OI", "target_qty": 0, "facts": {}}],
        "trades": [], "equity": [], "diagnostics": {},
    }


def v2_packet(cash="100000"):
    item = packet()
    item["metadata"].update(
        strategy_code="new_subing_v2", formula_version="new_subing_formula_v2",
        profile_id="new_subing_stage_v2_100k" if cash == "100000" else "new_subing_stage_v2_1m",
        risk_profile_version="new_subing_risk_v2",
        execution_profile_version="new_subing_next_1m_open_v2",
        account_model_version="new_subing_layers_v2", initial_cash=cash,
    )
    item["summary"].update(initial_cash=cash, final_equity=cash)
    return item


def test_v2_identity_binds_cash_and_account_model_without_changing_v1(tmp_path):
    from app.new_subing_research.store import _run_id
    original = packet()
    v1_id = _run_id(original)
    assert v1_id == "1597ec28c6ce186d335fa410fc85b41b4dd9c7a887de572de92fc75df5b44a01"
    assert _run_id({**original, "metadata": {**original["metadata"], "initial_cash": "100000"}}) == v1_id
    first = publish_result(tmp_path, v2_packet())
    million = publish_result(tmp_path, v2_packet("1000000"))
    assert first["metadata"]["run_id"] != million["metadata"]["run_id"]
    assert read_result(tmp_path, million["metadata"]["run_id"]) == million
    assert _run_id(original) == v1_id


@pytest.mark.parametrize("change", [
    {"initial_cash": None}, {"initial_cash": "1000000"},
    {"account_model_version": None}, {"account_model_version": "wrong"},
    {"profile_id": "new_subing_stage_v2_1m"},
    {"strategy_code": ["new_subing_v2"]},
    {"status": ["COMPLETED"]},
    {"product": ["AL"]},
    {"formula_version": "new_subing_formula_v1"},
])
def test_v2_unsafe_identity_refused(tmp_path, change):
    item = v2_packet()
    item["metadata"].update(change)
    with pytest.raises(ResultStoreError, match="RESULT_SCHEMA_INVALID"):
        publish_result(tmp_path, item)


def test_publish_is_indexed_immutable_and_paged(tmp_path):
    item = publish_result(tmp_path, packet())
    run_id = item["metadata"]["run_id"]
    assert len(run_id) == 64
    assert read_result(tmp_path, run_id) == item
    assert list_results(tmp_path)[0]["run_id"] == run_id
    assert page_result(tmp_path, run_id, "decisions", limit=1)["items"] == item["decisions"]
    with pytest.raises(ResultStoreError):
        publish_result(tmp_path, packet())


def test_missing_root_and_unknown_run_are_explicit(tmp_path):
    assert list_results(tmp_path / "missing") == []
    with pytest.raises(ResultStoreError):
        read_result(tmp_path / "missing", "a" * 64)
    with pytest.raises(ResultStoreError):
        read_result(tmp_path, "../index.json")


def test_corruption_and_symlink_fail_closed(tmp_path):
    item = publish_result(tmp_path, packet())
    run_id = item["metadata"]["run_id"]
    (tmp_path / f"{run_id}.json").write_text("{}")
    with pytest.raises(ResultStoreError):
        read_result(tmp_path, run_id)
    other = tmp_path / "other"
    other.mkdir()
    (other / "index.json").symlink_to(tmp_path / "index.json")
    with pytest.raises(ResultStoreError):
        list_results(other)


def test_cursor_bound_to_result_sha_and_kind(tmp_path):
    payload = packet()
    payload["decisions"] = payload["decisions"] * 3
    item = publish_result(tmp_path, payload)
    run_id = item["metadata"]["run_id"]
    page = page_result(tmp_path, run_id, "decisions", limit=1)
    assert page["next_cursor"]
    assert len(page_result(tmp_path, run_id, "decisions", limit=1, cursor=page["next_cursor"])["items"]) == 1
    with pytest.raises(ResultStoreError):
        page_result(tmp_path, run_id, "trades", cursor=page["next_cursor"])
    with pytest.raises(ResultStoreError):
        page_result(tmp_path, run_id, "decisions", limit=201)


def test_invalid_packet_refused(tmp_path):
    bad = packet()
    bad["summary"]["final_equity"] = float("nan")
    with pytest.raises(ResultStoreError):
        publish_result(tmp_path, bad)
    assert not tmp_path.exists() or not list(tmp_path.iterdir())


def test_blocked_gap_packet_keeps_unknown_hashes_and_no_fabricated_metrics(tmp_path):
    payload = packet()
    payload["metadata"]["status"] = "DATA_INSUFFICIENT"
    payload["metadata"]["input_snapshot_hash"] = None
    payload["metadata"]["execution_facts_hash"] = None
    payload["summary"] = {"status": "DATA_INSUFFICIENT"}
    payload["decisions"] = []
    payload["diagnostics"] = {"reason": "DATASET_OR_PARTITION_MISSING"}
    frozen = publish_result(tmp_path, payload)
    assert read_result(tmp_path, frozen["metadata"]["run_id"])["summary"] == {"status": "DATA_INSUFFICIENT"}


def test_incomplete_complete_packet_is_rejected(tmp_path):
    payload = packet()
    payload["summary"].pop("final_equity")
    with pytest.raises(ResultStoreError):
        publish_result(tmp_path, payload)


def test_indexed_directory_is_reported_as_corrupt_not_raw_io_error(tmp_path):
    item = publish_result(tmp_path, packet())
    run_id = item["metadata"]["run_id"]
    (tmp_path / f"{run_id}.json").unlink()
    (tmp_path / f"{run_id}.json").mkdir()
    with pytest.raises(ResultStoreError):
        read_result(tmp_path, run_id)


def test_same_input_identity_conflicts_when_result_output_drifts(tmp_path):
    first = packet()
    publish_result(tmp_path, first)
    drifted = packet()
    drifted["summary"]["final_equity"] = "99999"
    with pytest.raises(ResultStoreError, match="RESULT_EXISTS"):
        publish_result(tmp_path, drifted)


@pytest.mark.parametrize("status", ["UNKNOWN", "READY", "COMPLETE"])
def test_unknown_status_refused(tmp_path, status):
    payload = packet()
    payload["metadata"]["status"] = status
    payload["summary"]["status"] = status
    with pytest.raises(ResultStoreError):
        publish_result(tmp_path, payload)


@pytest.mark.parametrize("key,value", [("final_equity", "NaN"), ("account_return_pct", "Infinity"), ("total_fees", "bad"), ("closed_trades", 1.5), ("ending_qty", True)])
def test_nonfinite_decimal_and_noninteger_count_refused(tmp_path, key, value):
    payload = packet()
    payload["summary"][key] = value
    with pytest.raises(ResultStoreError):
        publish_result(tmp_path, payload)


def test_symlinked_parent_and_fifo_index_fail_closed(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ResultStoreError):
        publish_result(link / "results", packet())
    fifo_root = tmp_path / "fifo-results"
    fifo_root.mkdir()
    import os
    os.mkfifo(fifo_root / "index.json")
    with pytest.raises(ResultStoreError):
        list_results(fifo_root)


def test_fifo_parent_is_rejected_before_read(tmp_path):
    import os
    parent = tmp_path / "fifo-parent"
    os.mkfifo(parent)
    with pytest.raises(ResultStoreError):
        list_results(parent / "nested")


@pytest.mark.parametrize("field,value", [("account_return_pct", "0"), ("final_equity", "100000"), ("max_drawdown_pct", "0"), ("total_fees", "0"), ("annual_eligible", True)])
def test_blocked_trace_cannot_claim_performance(tmp_path, field, value):
    payload = packet()
    payload["metadata"]["status"] = "EXECUTION_FACTS_MISSING"
    payload["metadata"]["input_snapshot_hash"] = None
    payload["metadata"]["execution_facts_hash"] = None
    payload["summary"] = {"status": "EXECUTION_FACTS_MISSING", field: value}
    with pytest.raises(ResultStoreError):
        publish_result(tmp_path, payload)


def test_blocked_run_identity_includes_typed_gap(tmp_path):
    first = packet()
    first["metadata"].update(status="DATA_INSUFFICIENT", input_snapshot_hash=None, execution_facts_hash=None)
    first["summary"] = {"status": "DATA_INSUFFICIENT"}
    first["diagnostics"] = {"gap": {"code": "DATASET_OR_PARTITION_MISSING", "contract": "AL2411"}}
    second = {**first, "diagnostics": {"gap": {"code": "DATASET_OR_PARTITION_MISSING", "contract": "AL2412"}}}
    first_id = publish_result(tmp_path, first)["metadata"]["run_id"]
    second_id = publish_result(tmp_path, second)["metadata"]["run_id"]
    assert first_id != second_id


def test_full_equity_curve_keeps_original_points_extrema_boundaries_and_hash(tmp_path):
    from datetime import datetime, timedelta, timezone
    from app.new_subing_research.store import equity_curve
    payload = packet()
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    payload['equity'] = [dict(at=(start + timedelta(minutes=i)).isoformat(), equity=str(i % 17),
                              physical_contract='AL2501' if i < 1500 else 'AL2502') for i in range(3000)]
    payload['equity'][125]['equity'] = '-999'
    payload['equity'][2200]['equity'] = '999'
    frozen = publish_result(tmp_path, payload)
    run_id = frozen['metadata']['run_id']
    curve = equity_curve(tmp_path, run_id, max_points=40)
    assert curve['run_id'] == run_id and curve['sha256'] == page_result(tmp_path, run_id, 'equity')['sha256']
    assert curve['total'] == 3000 and curve['sampled'] is True
    assert len(curve['items']) <= 40
    assert curve['items'][0] == payload['equity'][0] and curve['items'][-1] == payload['equity'][-1]
    for index in [125, 1499, 1500, 2200]:
        assert payload['equity'][index] in curve['items']
    assert all(item in payload['equity'] for item in curve['items'])
    with pytest.raises(ResultStoreError, match='RESULT_HASH_MISMATCH'):
        equity_curve(tmp_path, run_id, expected_sha256='0' * 64)
    assert read_result(tmp_path, run_id)['summary'] == frozen['summary']


def test_equity_boundary_budget_fails_closed_and_empty_is_explicit(tmp_path):
    from app.new_subing_research.store import equity_curve
    payload = packet()
    payload['equity'] = [dict(at=f'2025-01-01T00:{i:02d}:00+00:00', equity=str(i), physical_contract=str(i)) for i in range(10)]
    frozen = publish_result(tmp_path, payload)
    with pytest.raises(ResultStoreError, match='CURVE_BOUNDARY_BUDGET_EXCEEDED'):
        equity_curve(tmp_path, frozen['metadata']['run_id'], max_points=4)
    other = tmp_path / 'empty'
    frozen = publish_result(other, packet())
    assert equity_curve(other, frozen['metadata']['run_id'])['items'] == []


@pytest.mark.parametrize('rows', [
    [{'at': 'bad', 'equity': '1'}],
    [{'at': '2025-01-01T00:00:00+00:00', 'equity': 'NaN'}],
    [{'at': '2025-01-02T00:00:00+00:00', 'equity': '1'}, {'at': '2025-01-01T00:00:00+00:00', 'equity': '1'}],
])
def test_curve_refuses_invalid_time_values_or_order(tmp_path, rows):
    from app.new_subing_research.store import equity_curve
    payload = packet()
    payload['equity'] = rows
    frozen = publish_result(tmp_path, payload)
    with pytest.raises(ResultStoreError, match='CURVE_FACTS_INVALID'):
        equity_curve(tmp_path, frozen['metadata']['run_id'])
