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
