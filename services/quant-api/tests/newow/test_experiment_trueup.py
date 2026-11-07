"""Test5 is a projection of the current product event and page chains."""
from dataclasses import replace

from guiyi_quant.newow.oscillation_experiments import ExperimentKind
from guiyi_quant.newow.oscillation_trueup import calculate_oscillation_series
from guiyi_quant.newow.page_performance import (
    PageAction, PageBar, PageSegment, build_page_performance_material,
    project_page_performance_material,
)
from app.market_data.newow.experiments import ExperimentQuery, NewowExperimentService
from app.market_data.newow.experiment_transport import experiment_response
from app.market_data.newow.snapshot_cache import SnapshotCache
from newow.test_experiments import NOW, Reader, make_bar


def query(bars):
    return NewowExperimentService(Reader(tuple(bars)), now=lambda: NOW).query(
        ExperimentQuery("rb", "1d", "osc-test5")
    )


def test_test5_reuses_product_signals_and_both_page_projections():
    source = tuple(make_bar(i) for i in range(12))
    result = query(source)
    segment = result["segments"][0]
    bars = tuple(replace(b.bar, segment_id=segment["segment_id"]) for b in source)
    steps = calculate_oscillation_series(bars)
    assert [(m["bar_end"], m["action"], m["reference_price"]) for m in result["markers"]] == [
        (bar.bar_end.isoformat(), signal.action.value, str(signal.price))
        for bar, step in zip(bars, steps, strict=True) for signal in step.signals
    ]
    material = build_page_performance_material(
        (PageSegment(segment["segment_id"], tuple(
            PageBar(b.bar_end.isoformat(), b.high, b.low, b.close,
                    b.observation_eligible, b.trading_day.isoformat()) for b in bars
        ), terminal_eligible=True, actions=tuple(
            PageAction(b.bar_end.isoformat(),
                       "buy" if s.action.value == "BUILD" else "sell", s.price)
            for b, step in zip(bars, steps, strict=True) for s in step.signals
        )),), "oscillation", period="1d", event_driven=True,
    )
    expected = project_page_performance_material(material, since="2026-01-01", through="2026-02-28")
    assert expected["ideal_open_count"] == 1
    assert expected["ordinary_interrupted_count"] == 0
    for mode, shared_mode in (("ordinary", "ordinary"), ("theoretical", "ideal")):
        actual, shared = segment[mode], expected[shared_mode]
        assert actual["dates"] == shared["dates"]
        assert actual["equity"] == shared["equity"]
        assert actual["summary"] == dict(
            cum_return_percentage_points=shared["summary"]["cumReturn"],
            accuracy_pct=str(shared["summary"]["accuracy"]),
            max_drawdown_percentage_points=shared["summary"]["maxDrawdown"],
            trade_count=shared["summary"]["tradeCount"],
        )
    assert segment["latest_state"]["holding"] is True
    assert not any(t["force_close"] for t in segment["ordinary"]["trades"])
    assert segment["ordinary"]["summary"]["trade_count"] == 1
    assert segment["ordinary"]["equity"][-1] != segment["ordinary"]["summary"]["cum_return_percentage_points"]
    assert segment["ordinary"]["page_version"] == "newow_unified_trueup_page_v1"
    assert "breakout_events" in result
    assert segment["theoretical"]["hindsight"] is True
    assert result["formula_version"] == "newow_oscillation_trueup_kernel111_v1"
    assert result["profile_id"] == "newow_experiment_trueup_v1"
    panel = experiment_response(result, SnapshotCache())
    assert panel["schema_version"] == "newow_experiment_detail_v3"


def test_test5_preserves_independent_physical_segments():
    result = query([make_bar(i) for i in range(12)] + [
        make_bar(i, "RB2705", "owner2") for i in range(12, 24)
    ])
    assert [s["status"] for s in result["segments"]] == ["ROLLOVER_INTERRUPTED", "CURRENT"]
    for segment in result["segments"]:
        for model in (segment["ordinary"], segment["theoretical"]):
            for trade in model["trades"]:
                assert trade["physical_contract"] == segment["physical_contract"]
                assert trade["segment_id"] == segment["segment_id"]
                assert trade["force_close"] is False


def test_test1_to_4_formula_versions_remain_frozen():
    for kind in (ExperimentKind.TEST1, ExperimentKind.TEST2, ExperimentKind.TEST3, ExperimentKind.TEST4):
        assert kind.formula_version == f"newow_{kind.value.replace('-', '_')}_page_v3379_v1"


def test_test5_trueup_hold_failure_and_posterior_use_same_event_chain():
    from newow.test_trueup import witness

    for failed in (False, True):
        source = tuple(replace(make_bar(i), bar=replace(
            make_bar(i).bar, open=b.open, high=b.high, low=b.low, close=b.close
        )) for i, b in enumerate(witness(failed)))
        result = query(source)
        segment = result["segments"][0]
        ordinary = segment["ordinary"]
        theoretical = segment["theoretical"]
        expected_exit = source[11 if failed else 12].bar.bar_end.isoformat()
        assert ordinary["summary"]["trade_count"] == 1
        assert [t["exit_bar_end"] for t in ordinary["trades"]] == [expected_exit]
        assert [t["exit_bar_end"] for t in theoretical["trades"]] == [expected_exit]
        assert ordinary["trades"][0]["exit_reference_price"] == ("119" if failed else "121")
        assert theoretical["trades"][0]["exit_reference_price"] == ("120" if failed else "121")
        # The legacy HHV path exits on index ten; Test5 must wait for kernel confirmation.
        assert not any(m["action"] == "CLEAR" and m["bar_end"] == source[10].bar.bar_end.isoformat()
                       for m in result["markers"])


def test_frozen_experiment_entry_points_reject_test5_even_without_bars():
    import pytest
    from guiyi_quant.newow.oscillation_experiments import calculate_experiment_series, run_experiment_reference
    for entry in (calculate_experiment_series, run_experiment_reference):
        with pytest.raises(ValueError, match="NEWOW_TEST5_REQUIRES_TRUEUP_PRODUCT"):
            entry((), ExperimentKind.TEST5)
