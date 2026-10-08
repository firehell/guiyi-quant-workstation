"""D1 warm-up quality facts remain inputs, but cannot interrupt owner references."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.planning import HistoricalStreamRequest
from app.reference_trading.newow_fusion import SavedFusionSources
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import (
    DataInterruption,
    ProductFrequency,
    ProductStrategy,
)
from guiyi_quant.newow.product_identity import (
    futures_adaptation_version,
    REFERENCE_MODEL_VERSION,
)
from guiyi_quant.reference_trading import BoundaryReason, StreamIdentity

POLICY = "owner_eligible_quality_boundary_v1"


def snapshot(frequency="1d", owner_start_index=2):
    from newow.product_fixtures import ProductCases

    case = ProductCases().primitive_input("trend", frequency)
    bars = tuple(
        replace(item, bar=replace(item.bar, observation_eligible=index >= 2))
        for index, item in enumerate(case.bars[:5])
    )
    gaps = tuple(
        DataInterruption(
            "rb",
            ProductFrequency(frequency),
            bars[0].bar.physical_contract,
            bars[0].bar.segment_id,
            bars[index].bar.trading_day,
            bars[index].bar.bar_end + timedelta(seconds=1),
            f"quality-{index}",
        )
        for index in ((1, 3) if frequency in ("1d", "1w") else ())
    )
    owner = SimpleNamespace(
        contract=bars[0].bar.physical_contract,
        start_trading_day=bars[owner_start_index].bar.trading_day,
        end_trading_day=bars[-1].bar.trading_day,
    )
    source = SimpleNamespace(
        source_identity="canonical", input_policy_version="fixture"
    )
    read = SimpleNamespace(
        replay_bars=bars,
        data_interruptions=gaps,
        boundaries=(),
        owners=(owner,),
        lifecycle_evidence=(),
        input_quality_policy=case.identity.input_quality_policy,
        sources={ProductFrequency(frequency): source},
    )
    reader = SimpleNamespace(
        load=lambda *args: read,
        historical_metadata_evidence=lambda **kw: {
            "schema_version": "metadata",
            "calendar": ["verified"],
        },
    )
    identity = case.identity
    stream = StreamIdentity(
        strategy_code="newow_trend",
        formula_versions=identity.formula_versions,
        profile_id=identity.profile_id,
        reference_model_version=REFERENCE_MODEL_VERSION,
        futures_adaptation_version=futures_adaptation_version(
            frequency, identity.input_quality_policy
        ),
        product="rb",
        frequency=frequency,
        series_kind="actual_dominant",
        recording_mode="historical_replay",
        observation_policy_version=None,
    )
    request = HistoricalStreamRequest(
        stream,
        bars[0].bar.trading_day,
        bars[-1].bar.trading_day,
        bars[-1].bar.bar_end + timedelta(days=1),
    )
    return (
        MarketDataHistoricalInputReader(
            newow_reader=reader, subing_service=None
        )._read_newow(request),
        bars,
        gaps,
    )


def test_daily_prewarm_gap_not_projected_but_raw_facts_and_calculation_reset_preserved():
    result, bars, gaps = snapshot()
    projected = [
        boundary
        for item in result.bars
        for boundary in item.boundaries
        if boundary.reason is BoundaryReason.DATA_INTERRUPTED
    ]
    assert [boundary.bar_end for boundary in projected] == [gaps[1].effective_at]
    assert len(result.dependency_manifest["data_interruptions"]) == 2
    replay = [item for item in result.bars if item.strategy_input]
    assert len(replay) == len(bars)
    assert replay[1].calculation_segment_id != replay[2].calculation_segment_id
    assert result.dependency_manifest["reference_boundary_policy_version"] == POLICY


def test_weekly_source_policy_is_unchanged():
    result, _, gaps = snapshot("1w")
    assert "reference_boundary_policy_version" not in result.dependency_manifest
    projected = [b.bar_end for item in result.bars for b in item.boundaries]
    assert projected == [gaps[1].effective_at]


@pytest.mark.parametrize("saved_policy", [None, "old_policy", POLICY])
def test_saved_daily_fusion_requires_current_projection_policy(saved_policy):
    from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
    from guiyi_quant.newow.product_identity import InputQualityPolicy
    from datetime import UTC, date, datetime

    policy = InputQualityPolicy.DAILY_V2
    expected = {
        "reader": "newow_product_reader_v2",
        "query_since": "2023-01-01",
        "quality_policy": policy.value,
        "reference_boundary_policy_version": POLICY,
    }
    actual = {**expected}
    if saved_policy is None:
        actual.pop("reference_boundary_policy_version")
    else:
        actual["reference_boundary_policy_version"] = saved_policy

    class Query:
        def streams(self, **kwargs):
            return [{"stream_id": kwargs["strategy"]}]

        def summary(self, *args, **kwargs):
            return {"revision_id": "saved", "seq": 1, "snapshot": "saved"}

        def historical_actions(self, *args, **kwargs):
            yield from ()

    loader = SavedFusionSources.__new__(SavedFusionSources)
    loader._query = Query()
    loader._check_cancelled = None
    loader._persisted = SimpleNamespace(
        _manifest=lambda stream_id, *args: (
            build_product_identity(
                "rb",
                ProductStrategy(stream_id.removeprefix("newow_")),
                ProductFrequency.DAILY,
                input_quality_policy=policy,
            ),
            actual,
        )
    )
    request = SimpleNamespace(
        identity=build_fusion_stream_identity("rb", "1d", input_quality_policy=policy),
        since=date(2023, 1, 1),
        through=date(2026, 10, 8),
        as_of=datetime(2026, 10, 8, 8, tzinfo=UTC),
    )
    if saved_policy == POLICY:
        _, dependencies = loader(request, expected)
        assert len(dependencies) == 2
    else:
        with pytest.raises(
            ValueError, match="REFERENCE_FUSION_SOURCE_SNAPSHOT_CONFLICT"
        ):
            loader(request, expected)


def test_owned_daily_gap_before_first_eligible_bar_still_projects():
    result, _, gaps = snapshot(owner_start_index=0)
    projected = [b.bar_end for item in result.bars for b in item.boundaries]
    assert projected == [gap.effective_at for gap in gaps]


@pytest.mark.parametrize("frequency", ["5m", "15m", "30m", "60m"])
def test_intraday_source_policy_is_unchanged(frequency):
    result, _, _ = snapshot(frequency)
    assert "reference_boundary_policy_version" not in result.dependency_manifest


def test_daily_policy_participates_in_source_digest():
    from app.reference_trading.contracts import manifest_sha256

    result, _, _ = snapshot()
    old = dict(result.dependency_manifest)
    old.pop("reference_boundary_policy_version")
    assert result.source_token == manifest_sha256(result.dependency_manifest)
    assert result.source_token != manifest_sha256(old)


def test_daily_owner_filter_keeps_rollover_and_fails_unproven_owner():
    from app.reference_trading.inputs import _daily_owner_reference_boundaries
    from guiyi_quant.reference_trading import ReferenceBoundary

    result, bars, _ = snapshot()
    stream = result.stream
    owner = SimpleNamespace(
        contract=bars[0].bar.physical_contract,
        start_trading_day=bars[2].bar.trading_day,
        end_trading_day=bars[-1].bar.trading_day,
    )
    boundary = ReferenceBoundary(
        stream,
        BoundaryReason.ROLLOVER,
        bars[0].bar.physical_contract,
        bars[0].bar.segment_id,
        bars[0].calculation_segment_id,
        bars[-1].bar.bar_end,
        bars[-1].bar.trading_day,
    )
    assert _daily_owner_reference_boundaries([boundary], bars, [owner]) == [boundary]
    unknown = replace(
        boundary, reason=BoundaryReason.DATA_INTERRUPTED, owner_segment_id="unknown"
    )
    with pytest.raises(ValueError, match="REFERENCE_BOUNDARY_CONTEXT_MISSING"):
        _daily_owner_reference_boundaries([unknown], bars, [owner])
