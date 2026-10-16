from __future__ import annotations

import pytest

from app.api.newow_reference_parts import _annualized, _curve_points, _drawdown, project_reference_part
from app.market_data.newow.product_service import ProductServiceQuery


def _value():
    return {
        "performance_since": "2025-01-01", "performance_through": "2026-01-01",
        "actual_available_through": "2026-01-01", "reference_cutoff": "2026-01-01T07:00:00Z",
        "reference_input_sha256": "a" * 64, "history_coverage": "FULL",
        "executable": False, "auto_order": False,
        "allowed_uses": ["page_parity_reference", "research_display"],
        "summary": {"closed_count": 0}, "unavailable_days": [], "coverage_intervals": [],
        "items": [{"reference_trade_id": str(index)} for index in range(60)],
        "next_before": "cursor", "curve_trades": [],
        "page_performance": {
            "version": "newow_page_performance_v3379_v2",
            "source_version": "3.3.79", "source_sha256": "b" * 64,
            "input_sha256": "c" * 64, "source_evidence_sha256": None,
            "ordinary": {"dates": ["2025-01-01T07:00:00Z", "2025-01-02T07:00:00Z"],
                         "trading_days": ["2025-01-01", "2025-01-02"],
                         "segment_ids": ["a", "a"], "equity": ["0", "3"],
                         "summary": {"cumReturn": "3", "accuracy": 0,
                                     "maxDrawdown": "0", "tradeCount": 0},
                         "period": "1d", "drawdown_kind": "peak_difference",
                         "trades": []},
            "ideal": None,
        },
    }


def test_reference_parts_return_only_requested_payload():
    source = _value()
    overview = project_reference_part(source, "overview", "page_ordinary")
    curve = project_reference_part(source, "curve", "page_ordinary")
    history = project_reference_part(source, "history", "closed")
    assert len(overview["recent_items"]) == 0
    assert "items" not in overview and "curve" not in overview
    assert [point["value"] for point in curve["curve"]["points"]] == ["0", "3"]
    assert [point["position"] for point in curve["curve"]["points"]] == [0, 1]
    assert "summary" not in curve and "items" not in curve
    assert len(history["items"]) == 50 and history["next_before"] == "cursor"
    assert "summary" not in history and "curve" not in history
    assert {part["reference_input_sha256"] for part in (overview, curve, history)} == {"a" * 64}
    same_history = project_reference_part(source, "history", "page_ordinary")
    assert overview["result_hash"] == curve["result_hash"] == same_history["result_hash"]
    assert overview["record_since"] == "2025-01-01"
    assert overview["records_window_limited"] is False


@pytest.mark.parametrize("mode", ["page_ordinary", "closed"])
def test_panel_is_exact_overview_and_selected_curve_from_one_result(mode):
    source = _value()
    args = dict(snapshot_token="token", as_of="2026-01-01T07:00:00Z")
    panel = project_reference_part(source, "panel", mode, **args)
    overview = project_reference_part(source, "overview", mode, **args)
    curve = project_reference_part(source, "curve", mode, **args)
    assert panel == {**overview, "reference_part": "panel", "curve": curve["curve"]}
    assert panel["result_hash"] == curve["result_hash"]
    assert "items" not in panel and "next_before" not in panel
    assert ProductServiceQuery(product="rb", strategy="trend", frequency="1d",
                               section="reference", reference_part="panel", reference_mode=mode)


def test_record_window_limit_is_explicit_without_changing_full_result_hash():
    source = _value()
    source["record_since"] = "2025-01-02"
    source["records_window_limited"] = True
    overview = project_reference_part(source, "overview", "closed", snapshot_token="token", as_of="2026-01-01T07:00:00Z")
    curve = project_reference_part(source, "curve", "closed", snapshot_token="token", as_of="2026-01-01T07:00:00Z")
    assert overview["record_since"] == "2025-01-02"
    assert curve["records_window_limited"] is True
    assert overview["result_hash"] == curve["result_hash"]


def test_page_history_cursor_rejects_old_result_generation():
    source = _value()
    source["page_performance"]["ordinary"]["trades"] = [
        {"buyDate": "2025-01-01", "sellDate": "2025-01-02", "segment_id": "a", "pct": str(index)}
        for index in range(53)
    ]
    first = project_reference_part(source, "history", "page_ordinary", snapshot_token="token", as_of="2026-01-01T07:00:00Z")
    assert len(first["items"]) == 50 and first["next_before"]
    second = project_reference_part(source, "history", "page_ordinary", history_before=first["next_before"], snapshot_token="token", as_of="2026-01-01T07:00:00Z")
    assert len(second["items"]) == 3 and second["next_before"] is None
    source["reference_input_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="NEWOW_CURSOR_GENERATION_CONFLICT"):
        project_reference_part(source, "history", "page_ordinary", history_before=first["next_before"], snapshot_token="token", as_of="2026-01-01T07:00:00Z")


def test_curve_sampling_keeps_gap_owner_boundary_and_extrema():
    source = [{"value": str(index), "segment_id": "a", "status": "FLAT"}
              for index in range(2200)]
    source[1000]["value"] = "-4000"
    source[1050]["value"] = "5000"
    source[1100]["status"] = "INTERRUPTED"
    for index in range(1200, 2200):
        source[index]["segment_id"] = "b"
    projected = _curve_points(source)
    assert projected["sampled"] and projected["total_points"] == 2200
    assert len(projected["points"]) <= 2000
    assert projected["points"][0]["position"] == 0
    assert projected["points"][-1]["position"] == 2199
    for original in (source[0], source[-1], source[1000], source[1050],
                     source[1099], source[1100], source[1101], source[1199], source[1200]):
        assert any(all(point.get(key) == value for key, value in original.items())
                   for point in projected["points"])


def test_sampling_preserves_null_and_calculation_boundaries_without_status_flags():
    source = [{"value": str(index), "segment_id": "same-owner",
               "calculation_segment_id": "before" if index < 1500 else "after"}
              for index in range(2400)]
    source[899]["value"] = None
    sampled = _curve_points(source)
    positions = {point["position"] for point in sampled["points"]}
    assert {0, 898, 899, 900, 1499, 1500, 2399} <= positions
    assert len(sampled["points"]) <= 2000


def test_curve_budget_rejects_too_many_mandatory_boundaries():
    source = [{"value": str(index), "segment_id": str(index), "status": "FLAT"}
              for index in range(2001)]
    with pytest.raises(ValueError, match="NEWOW_REFERENCE_CURVE_BUDGET_EXCEEDED"):
        _curve_points(source)


def test_annualized_invalid_or_overflow_returns_null_and_drawdown_rounds_half_up():
    assert _annualized("nan", "1", 365) is None
    assert _annualized("0", "inf", 365) is None
    assert _annualized("0", "100", 0.001) is None
    assert _drawdown([{"value": "0"}, {"value": "-0.005"}]) == "0.01"


def test_empty_closed_curve_does_not_annualize_zero_total():
    source = _value()
    source["summary"]["sum_return_percentage_points"] = "0"
    curve = project_reference_part(source, "curve", "closed")["curve"]
    assert curve["annualized_pct"] is None
    assert curve["metrics"]["closed_count"] == 0


def test_holding_annualizes_valid_endpoints_and_preserves_null_gaps():
    source = _value()
    source["holding_curve"] = {
        "model_version": "newow_reference_marked_curve_v1",
        "points": [
            {"bar_end": "2025-01-01T00:00:00Z", "marked_return_percentage_points": None},
            {"bar_end": "2025-01-02T00:00:00Z", "marked_return_percentage_points": "0"},
            {"bar_end": "2025-01-03T00:00:00Z", "marked_return_percentage_points": None},
            {"bar_end": "2025-01-04T00:00:00Z", "marked_return_percentage_points": "1"},
            {"bar_end": "2025-01-05T00:00:00Z", "marked_return_percentage_points": None},
        ],
    }
    curve = project_reference_part(source, "curve", "holding")["curve"]
    assert [point["value"] for point in curve["points"]] == [None, "0", None, "1", None]
    assert curve["annualized_pct"] == _annualized("0", "1", 2)
    assert curve["metrics"]["return_percentage_points"] == "1"


@pytest.mark.parametrize("part", ["curve", "panel"])
def test_split_query_rejects_mixed_history_and_curve_parameters(part):
    with pytest.raises(ValueError, match="NEWOW_SECTION_PARAMETER_INVALID"):
        ProductServiceQuery("rb", "trend", "1d", section="reference",
                            reference_part=part, reference_mode="closed",
                            history_before="old")
    with pytest.raises(ValueError, match="NEWOW_SECTION_PARAMETER_INVALID"):
        ProductServiceQuery("rb", "trend", "1d", section="reference",
                            reference_part=part, reference_mode="fusion_closed")
