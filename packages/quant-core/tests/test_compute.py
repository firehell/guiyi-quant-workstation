from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import sin

import numpy as np
import pytest
import talib

from guiyi_quant.compute import (
    REGISTRY,
    BarSeries,
    CompletedBar,
    FeatureRequest,
    SeriesIdentity,
    Status,
    advance,
    open_incremental,
    rebind_incremental,
)


SOURCE = SeriesIdentity("JM", "JM2701", "JM2701:17", "15m", "fixed-test-v1")
START = datetime(2026, 10, 30, 1, 15, tzinfo=UTC)


def bars(count: int = 100):
    rows = []
    for index in range(count):
        close = 110 + 0.05 * index + 3 * sin(index / 4.75)
        end = START + timedelta(minutes=15 * index)
        rows.append(CompletedBar(
            SOURCE.physical_contract, SOURCE.segment_id, end.date(), end.date().isoformat(),
            end, end + timedelta(seconds=1), end + timedelta(seconds=2),
            close - 1, close + 2, close - 2, close, float((index % 25) + 5), "VALID",
        ))
    return tuple(rows)


def calc(rows, name, **params):
    return REGISTRY.calculate(
        BarSeries(SOURCE, rows), [FeatureRequest(name, params)], use="research",
        as_of=rows[-1].available_at,
    )[0]


@pytest.mark.parametrize(
    "feature,options,function,columns,kwargs",
    [
        ("ema10", {}, talib.EMA, ("close",), {"timeperiod": 10}),
        ("ema21", {}, talib.EMA, ("close",), {"timeperiod": 21}),
        ("ema60", {}, talib.EMA, ("close",), {"timeperiod": 60}),
        ("macd", {}, talib.MACD, ("close",), {"fastperiod": 12, "slowperiod": 26, "signalperiod": 9}),
        ("atr", {}, talib.ATR, ("high", "low", "close"), {"timeperiod": 14}),
        ("stddev", {}, talib.STDDEV, ("close",), {"timeperiod": 20, "nbdev": 1}),
        ("boll", {}, talib.BBANDS, ("close",), {"timeperiod": 20, "nbdevup": 2, "nbdevdn": 2, "matype": 0}),
        ("hhv", {"period": 4}, talib.MAX, ("high",), {"timeperiod": 4}),
        ("llv", {"period": 4}, talib.MIN, ("low",), {"timeperiod": 4}),
        ("obv", {}, talib.OBV, ("close", "volume"), {}),
    ],
)
def test_registered_batch_values_are_raw_talib(feature, options, function, columns, kwargs):
    rows = bars()
    result = calc(rows, feature, **options)
    arrays = tuple(np.array([getattr(bar, field) for bar in rows]) for field in columns)
    expected = function(*arrays, **kwargs)
    if not isinstance(expected, tuple):
        expected = (expected,)
    keys = REGISTRY.definition(feature).outputs
    for index, point in enumerate(result.points):
        value = [output[index] for output in expected]
        if not np.isfinite(value).all():
            assert point.status is Status.WARMING
            assert point.values is None
        else:
            assert point.status is Status.READY
            assert [point.values[key] for key in keys] == value


def test_feature_whitelist_and_parameters_fail_explicitly():
    assert {
        feature_id for feature_id, definition in REGISTRY.definitions.items()
        if definition.category == "generic"
    } == {"ema10", "ema21", "ema60", "macd", "atr", "stddev", "boll", "hhv", "llv", "obv", "volume_ratio"}
    for name, options in (("sma", {}), ("hhv", {}), ("macd", {"slow": 9}), ("atr", {"period": True})):
        with pytest.raises(ValueError):
            calc(bars(3), name, **options)


def test_zero_volume_reference_and_invalid_prefix():
    rows = tuple(replace(bar, volume=0.0) for bar in bars(6))
    rows += bars(8)[6:]
    points = calc(rows, "volume_ratio").points
    assert all(point.status is Status.WARMING for point in points[:5])
    assert all(point.status is Status.UNKNOWN for point in points[5:7])
    assert points[7].values["value"] == pytest.approx(rows[7].volume / (rows[6].volume / 5))
    dirty = (*rows[:6], replace(rows[6], volume=None), rows[7])
    points = calc(dirty, "volume_ratio").points
    assert [point.diagnostic for point in points[6:]] == ["INPUT_MISSING", "INPUT_PREFIX_INTERRUPTED"]


def test_owner_availability_and_cache_prefix_boundary():
    rows = bars(25)
    with pytest.raises(ValueError, match="BAR_OWNER_CHANGED"):
        BarSeries(SOURCE, (*rows[:-1], replace(rows[-1], physical_contract="JM2705")))
    proof = rows[-1].available_at
    rows = (replace(rows[0], available_at=proof), *rows[1:])
    series = BarSeries(SOURCE, rows)
    request = FeatureRequest("ema10")
    assert REGISTRY.calculate(series, [request], as_of=proof - timedelta(seconds=1), use="web")[0].points == ()
    cache = {}
    left, same = REGISTRY.calculate(series, [request, request], as_of=proof, use="web", result_cache=cache)
    assert left is same
    assert all(point.available_at == proof for point in left.points)
    shorter = BarSeries(SOURCE, rows[1:])
    assert REGISTRY.result_identity(shorter, request, proof) != left.identity


@pytest.mark.parametrize(
    "feature,options",
    [("ema21", {}), ("macd", {}), ("atr", {}), ("stddev", {}), ("boll", {}),
     ("hhv", {"period": 12}), ("llv", {"period": 12}), ("obv", {}), ("volume_ratio", {})],
)
def test_batch_incremental_and_restart_numeric_parity(feature, options):
    rows = bars()
    request = FeatureRequest(feature, options)
    expected = calc(rows, feature, **options).points
    state = open_incremental(BarSeries(SOURCE, ()), request, as_of=START, mode="live", use="simulation")
    for index, bar in enumerate(rows):
        state, point = advance(state, SOURCE, bar)
        assert point.status == expected[index].status
        assert point.diagnostic == expected[index].diagnostic
        if point.values is not None:
            assert dict(point.values) == pytest.approx(dict(expected[index].values), rel=1e-9, abs=1e-9)
        if index in (5, 58):
            restored = open_incremental(
                BarSeries(SOURCE, rows[:index + 1]), request,
                as_of=bar.available_at, mode="live", use="simulation",
            )
            assert restored.prefix_digest == state.prefix_digest
            assert dict(restored.last_point.values or {}) == pytest.approx(dict(point.values or {}), abs=1e-9)
            state = restored
    assert advance(state, SOURCE, rows[-1]) == (state, state.last_point)
    with pytest.raises(ValueError, match="STATE_INPUT_OUT_OF_ORDER_OR_REVISED"):
        advance(state, SOURCE, replace(rows[-1], volume=51))
    with pytest.raises(ValueError, match="STATE_SCHEMA_INCOMPATIBLE"):
        advance(replace(state, state_schema_version="prior"), SOURCE, rows[-1])
    new_source = replace(SOURCE, source_revision="next")
    rebound = rebind_incremental(state, BarSeries(new_source, rows))
    assert rebound.identity == new_source
    with pytest.raises(ValueError, match="STATE_PREFIX_CHANGED"):
        rebind_incremental(state, BarSeries(new_source, (replace(rows[0], volume=50), *rows[1:])))


def test_pivot_marks_confirmation_boundary_and_is_prefix_invariant():
    rows = bars()
    left_right = {"left": 2, "right": 3}
    result = calc(rows, "swing_pivot", **left_right)
    assert result.markers
    positions = {bar.bar_end: index for index, bar in enumerate(rows)}
    for marker in result.markers:
        pivot = positions[marker.occurred_at]
        confirming_bar = rows[pivot + 3]
        assert marker.confirmation_bar_end == confirming_bar.bar_end
        assert marker.confirmed_at == confirming_bar.confirmed_at
        assert marker.available_at == confirming_bar.available_at
        assert marker not in calc(rows[:pivot + 3], "swing_pivot", **left_right).markers
    for name in ("trend_direction", "support_resistance", "breakout", "retest"):
        full = calc(rows, name)
        partial = calc(rows[:55], name)
        assert partial.points == full.points[:55]
        assert partial.markers == tuple(m for m in full.markers if m.available_at <= rows[54].available_at)


def test_breakout_uses_previous_range_and_retest_requires_later_bar():
    flat = tuple(
        replace(bar, open=100, high=101, low=99, close=100)
        for bar in bars(25)
    )
    rows = (
        *flat[:21],
        replace(flat[21], open=100, high=110, low=100, close=108),
        replace(flat[22], open=103, high=106, low=101, close=105),
        *flat[23:],
    )
    event, = calc(rows, "breakout").markers
    assert event.occurred_at == rows[21].bar_end
    assert event.price == 101.5
    assert not calc(rows, "breakout", min_volume_ratio=100).markers
    retest, = calc(rows, "retest").markers
    assert retest.kind == "retest_confirmed"
    assert retest.occurred_at == rows[22].bar_end


def test_manifest_pins_result_state_formulas_and_display_permissions():
    from guiyi_quant.compute.manifest import (
        COMPUTE_CONTRACT_VERSION, RESULT_SCHEMA_VERSION, STATE_SCHEMA_VERSION, manifest, require_contract,
    )
    from guiyi_quant.compute.owned import owned_indicator

    require_contract(compute=COMPUTE_CONTRACT_VERSION, result=RESULT_SCHEMA_VERSION, state=STATE_SCHEMA_VERSION)
    with pytest.raises(ValueError, match="QUANT_CORE_CONTRACT_INCOMPATIBLE"):
        require_contract(compute=COMPUTE_CONTRACT_VERSION, result="unknown")
    with pytest.raises(ValueError, match="FEATURE_USE_NOT_ALLOWED"):
        owned_indicator("newow.zhaoyao_mirror", frequency="1d", use="backtest")
    with pytest.raises(ValueError, match="FEATURE_USE_NOT_ALLOWED"):
        owned_indicator("newow.cup_handle", frequency="1d", use="backtest")
    with pytest.raises(ValueError, match="FEATURE_USE_NOT_ALLOWED"):
        owned_indicator("newow.cup_handle", frequency="1m", use="web")
    cup_definition = owned_indicator("newow.cup_handle", frequency="1d", use="web")
    with pytest.raises(TypeError, match="unexpected keyword argument 'component'"):
        cup_definition.calculate(None, (), component="zhaoyao_mirror", as_of=None)
    with pytest.raises(ValueError, match="FEATURE_USE_NOT_ALLOWED"):
        owned_indicator("range_detector_lux", frequency="1m", use="simulation")
    manifest_features = manifest()["features"]
    assert manifest_features["macd"]["formula_version"] == "talib_macd_12_26_9_v1"
    assert manifest_features["newow.zhaoyao_mirror"]["repainting"] is True
    cup = manifest_features["newow.cup_handle"]
    assert cup["allowed_uses"] == ["web"] and cup["repainting"] is False
    assert cup["output_schema_version"] == "newow_cup_handle_witnesses_v1"
    assert {"witness_id", "confirmed_at", "profile_identity"}.issubset(cup["outputs"])
    assert manifest_features["subing_ths_15m"]["formula_version"] == "subing_ths_15m_v3"


@pytest.mark.parametrize(("frequency", "formula_version"), (
    ("5m", "subing_ths_5m_v1"),
    ("15m", "subing_ths_15m_v3"),
    ("30m", "subing_ths_30m_v1"),
    ("60m", "subing_ths_60m_v1"),
    ("1d", "subing_ths_1d_v1"),
    ("1w", "subing_ths_1w_v1"),
))
def test_owned_subing_preserves_period_identity_and_matches_the_existing_step(frequency, formula_version):
    from guiyi_quant.compute.owned import (
        SUBING_THS_OBSERVATION_USE, SUBING_THS_REFERENCE_USE, subing_ths_state_step,
    )
    from guiyi_quant.indicators.subing_ths import SubingThs15mKernel

    legacy = SubingThs15mKernel()
    expected_state = legacy.initial_state()
    initial, observe = subing_ths_state_step(frequency, use=SUBING_THS_OBSERVATION_USE)
    replay_initial, replay = subing_ths_state_step(frequency, use=SUBING_THS_REFERENCE_USE)
    observed_state, replayed_state = initial(), replay_initial()
    for bar in bars(90):
        end = bar.bar_end.isoformat()
        expected_state, expected = legacy.step(expected_state, bar.close, bar_end=end)
        observed_state, observation = observe(observed_state, bar.close, bar_end=end)
        replayed_state, replay_result = replay(replayed_state, bar.close, bar_end=end)
        assert expected_state == observed_state == replayed_state
        assert observation.formula_version == formula_version
        assert observation == replay_result
        assert replace(observation, formula_version=legacy.formula_version) == expected


def test_registered_htdy_and_subing_do_not_grant_new_consumers():
    from guiyi_quant.compute.owned import SUBING_THS_OBSERVATION_USE, owned_indicator, subing_ths_state_step

    for feature, frequency, use in (
        ("htdy_original", "60m", "backtest"),
        ("subing_ths_1d", "1d", "simulation"),
        ("subing_ths_1d", "15m", SUBING_THS_OBSERVATION_USE),
    ):
        with pytest.raises(ValueError, match="FEATURE_USE_NOT_ALLOWED"):
            owned_indicator(feature, frequency=frequency, use=use)
    with pytest.raises(ValueError, match="UNSUPPORTED_OWNED_FEATURE"):
        owned_indicator("htdy_strict", frequency="60m", use="backtest")
    with pytest.raises(ValueError, match="UNSUPPORTED_OWNED_FEATURE"):
        subing_ths_state_step("1m", use=SUBING_THS_OBSERVATION_USE)


def test_subing_paper_registry_exposes_only_its_existing_period_dependencies():
    from guiyi_quant.compute.manifest import manifest
    from guiyi_quant.compute.owned import SUBING_PAPER_FACTOR_USE, owned_indicator, subing_paper_factors
    from guiyi_quant.indicators import subing_trend

    for frequency in ("1d", "60m"):
        trend, = subing_paper_factors(frequency)
        assert trend.step is subing_trend.step
        assert trend.initial_state("JM2701", frequency) == subing_trend.initial_state("JM2701", frequency)
        assert trend.formula_version == subing_trend.VERSION
    with pytest.raises(ValueError, match="SUBING_PAPER_FACTOR_FREQUENCY_UNSUPPORTED"):
        subing_paper_factors("1m")

    expected = {"trend", "macd", "volume", "price", "pullback", "range", "structure", "exit_facts"}
    features = manifest()["features"]
    for definition in subing_paper_factors("30m"):
        expected.remove(definition.feature_id.removeprefix("subing_paper."))
        assert definition is owned_indicator(definition.feature_id, frequency="30m", use=SUBING_PAPER_FACTOR_USE)
        assert definition.repainting is False
        assert features[definition.feature_id]["allowed_uses"] == [SUBING_PAPER_FACTOR_USE]
        for use in ("web", "backtest", "simulation", "subing_reference", "subing_ths_observation"):
            with pytest.raises(ValueError, match="FEATURE_USE_NOT_ALLOWED"):
                owned_indicator(definition.feature_id, frequency="30m", use=use)
    assert not expected
    with pytest.raises(ValueError, match="FEATURE_USE_NOT_ALLOWED"):
        owned_indicator("subing_paper.macd", frequency="60m", use=SUBING_PAPER_FACTOR_USE)


def test_subing_paper_state_creation_preserves_the_fixed_model_parameters_and_optional_outputs():
    from decimal import Decimal

    from guiyi_quant.compute.manifest import manifest
    from guiyi_quant.compute.owned import subing_paper_factors
    from guiyi_quant.indicators import subing_macd, subing_range, subing_trend
    from guiyi_quant.subing_recent_structure import Bar

    factors = {item.feature_id.removeprefix("subing_paper."): item for item in subing_paper_factors("30m")}
    for factor, original, overrides in (
        ("trend", subing_trend.initial_state, {"ema_period": 19}),
        ("macd", subing_macd.initial_state, {"periods": (10, 26, 9)}),
        ("range", subing_range.initial_state, {"profile": "fixed"}),
    ):
        initializer = factors[factor].initial_state
        assert initializer("JM2701", "30m") == original("JM2701", "30m")
        with pytest.raises(TypeError):
            initializer("JM2701", "30m", **overrides)
    for factor in ("macd", "range", "volume", "pullback", "structure"):
        with pytest.raises(ValueError, match="SUBING_PAPER_FACTOR_FREQUENCY_UNSUPPORTED"):
            factors[factor].initial_state("JM2701", "1d")

    pullback = factors["pullback"]
    structure = factors["structure"]
    bar = Bar(START, Decimal(101), Decimal(99), Decimal(100))
    _, gap = structure.step(structure.initial_state("JM2701", "30m"), bar, contract="JM2701", valid=False)
    _, observed = structure.step(structure.initial_state("JM2701", "30m"), bar, contract="JM2701")
    assert set(gap) == set(structure.outputs)
    assert set(observed) == set((*structure.outputs, *structure.optional_outputs))
    for side in ("LONG", "SHORT"):
        initial = pullback.initial_state("JM2701", "30m", side=side)
        inputs = dict(contract="JM2701", bar_end=START, high=bar.high, low=bar.low, close=bar.close,
                      atr14=Decimal(2), trend_direction="NEUTRAL", side=side)
        _, warming = pullback.step(initial, ema21=None, **inputs)
        _, observed = pullback.step(initial, ema21=bar.close, **inputs)
        assert set(warming) == set(pullback.outputs)
        assert set(observed) == set((*pullback.outputs, *pullback.optional_outputs))
    by_feature = manifest()["features"]
    for definition in (pullback, structure):
        assert by_feature[definition.feature_id]["optional_outputs"] == definition.optional_outputs


def test_same_revision_and_window_bounds_distinguish_bar_members():
    rows = bars(16)
    first = BarSeries(SOURCE, (*rows[:3], *rows[4:]))
    second = BarSeries(SOURCE, (*rows[:12], *rows[13:]))
    cache = {}
    request = (FeatureRequest("ema10"),)
    as_of = rows[-1].available_at
    original, = REGISTRY.calculate(first, request, as_of=as_of, use="web", result_cache=cache)
    actual, = REGISTRY.calculate(second, request, as_of=as_of, use="web", result_cache=cache)
    expected, = REGISTRY.calculate(second, request, as_of=as_of, use="web")
    assert original.identity.input_digest != actual.identity.input_digest
    assert original.points[-1].values != actual.points[-1].values
    assert actual == expected


def test_dependency_formula_change_cannot_reuse_derived_cache():
    from guiyi_quant.compute import ComputeRegistry

    rows = bars()
    series = BarSeries(SOURCE, rows)
    as_of = rows[-1].available_at
    request = (FeatureRequest("trend_direction"),)
    cache = {}
    baseline, = REGISTRY.calculate(series, request, as_of=as_of, use="web", result_cache=cache)
    revised_ema = replace(REGISTRY.definition("ema21"), formula_version="new_ema_v2")
    revised = ComputeRegistry(
        revised_ema if definition.feature_id == "ema21" else definition
        for definition in REGISTRY.definitions.values()
    )
    actual, = revised.calculate(series, request, as_of=as_of, use="web", result_cache=cache)
    assert actual.identity.formula_version == baseline.identity.formula_version
    assert actual.identity.dependency_hash != baseline.identity.dependency_hash
    assert actual.points == baseline.points
