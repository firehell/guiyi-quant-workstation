from __future__ import annotations

import importlib
import json
import os
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.market_data.newow.product_reader import NewowProductReader
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import (
    ProductBar,
    ProductFrequency,
    ProductIdentity,
    ProductStrategy,
)
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector


def _api():
    module = importlib.import_module("guiyi_quant.newow.page_comparator")
    required = (
        "ComparatorOwnerSegment",
        "PageComparatorSourceBars",
        "VerifiedPageComparatorEvidence",
        "compare_page_windows",
    )
    missing = tuple(name for name in required if not hasattr(module, name))
    assert not missing, f"page comparator typed API is not implemented: {missing}"
    return module


def _identity(frequency: str = "1d") -> ProductIdentity:
    return ProductIdentity(
        "rb",
        ProductStrategy.OSCILLATION,
        ProductFrequency(frequency),
        (
            "newow_oscillation_hhv_llv10_page_v1",
            "newow_hhv_llv_channel_page_v1",
        ),
    )


def _bars(
    rows: tuple[tuple[str, str, str], ...],
    *,
    frequency: str = "1d",
    contract: str = "RB2605",
    segment_id: str = "rb:RB2605:owner",
    start: date = date(2026, 1, 1),
) -> tuple[ProductBar, ...]:
    result = []
    for index, (high, low, close) in enumerate(rows):
        if frequency == "60m":
            trading_day = start + timedelta(days=index // 4)
            bar_end = datetime.combine(trading_day, datetime.min.time(), UTC) + (
                timedelta(hours=2 + index % 4)
            )
        else:
            step = 7 if frequency == "1w" else 1
            trading_day = start + timedelta(days=index * step)
            bar_end = datetime.combine(trading_day, datetime.min.time(), UTC) + (
                timedelta(hours=7)
            )
        result.append(
            ProductBar(
                NewowDailyBar(
                    product="rb",
                    physical_contract=contract,
                    segment_id=segment_id,
                    trading_day=trading_day,
                    bar_end=bar_end,
                    open=Decimal(close),
                    high=Decimal(high),
                    low=Decimal(low),
                    close=Decimal(close),
                    volume=100,
                    open_interest=200,
                    source_identity=f"owned:page-comparator:{segment_id}:{index}",
                    observation_eligible=True,
                    completed=True,
                ),
                ProductFrequency(frequency),
            )
        )
    return tuple(result)


def _constant_bars(
    count: int,
    *,
    frequency: str = "1d",
    contract: str = "RB2605",
    segment_id: str = "rb:RB2605:owner",
    start: date = date(2026, 1, 1),
) -> tuple[ProductBar, ...]:
    return _bars(
        (("100", "100", "100"),) * count,
        frequency=frequency,
        contract=contract,
        segment_id=segment_id,
        start=start,
    )


def _owner(module, bars: tuple[ProductBar, ...]):
    first = bars[0].bar
    last = bars[-1].bar
    return module.ComparatorOwnerSegment(
        product=first.product,
        physical_contract=first.physical_contract,
        segment_id=first.segment_id,
        start_trading_day=first.trading_day,
        end_trading_day=last.trading_day,
    )


def test_comparator_without_evidence_returns_an_explicit_gap(product_cases) -> None:
    case = product_cases.primitive_input("oscillation", "1d")
    try:
        module = importlib.import_module("guiyi_quant.newow.page_comparator")
    except ModuleNotFoundError:
        pytest.fail("page comparator is not implemented", pytrace=False)

    result = module.compare_page_windows(
        case.identity,
        case.bars,
        evidence=None,
        authoritative_segments=(_owner(module, case.bars),),
        as_of=datetime(2026, 12, 31, tzinfo=UTC),
    )

    assert result.status == "evidence_required"
    assert result.evidence_status == "EVIDENCE_REQUIRED"
    assert result.reason_code == "NEWOW_PAGE_COMPARATOR_EVIDENCE_REQUIRED"
    assert result.value is None
    assert result.identity.frequency is ProductFrequency.DAILY


def test_verified_evidence_binds_all_four_originals_and_rejects_substitution() -> None:
    module = _api()
    evidence = module.VerifiedPageComparatorEvidence()

    assert evidence.builder_sha256 == (
        "a4491db837d710d3eda3b3d7b82ceae93b08d4b6418ae814c9649e0ef2ef23e0"
    )
    assert evidence.oracle_sha256 == (
        "ec353dd6608da2ed99d6a2cc582d4fc629aa5704c88e558d87aed7b23772b3bb"
    )
    assert evidence.input_sha256 == (
        "15473f0ebe577081eabdd24b663ce13374f8caf1a53997321f38b6af17424bb4"
    )
    assert evidence.page_source_sha256 == (
        "cd962170085dc2145fbaebf28a47ce6764b9f519e6032b54a896e37f0c9d0cf9"
    )
    for changes in (
        {"oracle_sha256": "0" * 64},
        {"evidence_kind": "browser_render"},
        {"browser_render_status": "AVAILABLE"},
    ):
        with pytest.raises(ValueError, match="NEWOW_PAGE_COMPARATOR_EVIDENCE_IDENTITY"):
            replace(evidence, **changes)


def test_inclusive_extrema_clear_then_reenter_and_zero_is_a_loss() -> None:
    module = _api()
    bars = _constant_bars(20)

    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, bars),),
        as_of=bars[-1].bar.bar_end,
    )

    assert result.status == "ready"
    assert result.evidence_status == "RESEARCH_EVIDENCE_ONLY"
    assert result.value.page_source_kernel_page_parity is True
    assert result.value.futures_adapter_page_parity is False
    assert result.value.in_sample is True
    assert result.value.executable is False
    segment = result.value.segments[0]
    window10 = {row.window: row for row in segment.results}[10]
    assert window10.trades[0].entry_bar_end == bars[9].bar.bar_end
    assert window10.trades[0].exit_bar_end == bars[10].bar.bar_end
    assert window10.trades[1].entry_bar_end == bars[10].bar.bar_end
    assert window10.trades[0].won is False
    assert window10.trades[0].return_pct == Decimal("0.0")
    assert window10.loss_count == window10.trade_count
    assert window10.max_drawdown_pct == Decimal("0.0")
    assert not hasattr(result.value, "actions")
    assert not hasattr(result.value, "reference_trades")


def test_unrealized_open_percentage_participates_in_page_drawdown() -> None:
    module = _api()
    rows = [("110", "90", "100")] * 9
    rows += [("110", "80", "100"), ("109", "85", "90")]
    rows += [("120", "85", "90")]
    rows += [("109", "85", "90")] * 8
    bars = _bars(tuple(rows))

    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, bars),),
        as_of=bars[-1].bar.bar_end,
    )
    window10 = {row.window: row for row in result.value.segments[0].results}[10]

    assert window10.cumulative_return_pct == Decimal("-10.0")
    assert window10.max_drawdown_pct == Decimal("10.0")


def test_twenty_bar_input_keeps_larger_page_windows_as_zero_trade_rows() -> None:
    module = _api()
    bars = _constant_bars(20)

    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, bars),),
        as_of=bars[-1].bar.bar_end,
    )
    rows = {row.window: row for row in result.value.segments[0].results}

    assert rows[20].trade_count == 1
    for window in (24, 30, 52):
        assert rows[window].trade_count == 0
        assert rows[window].win_rate_pct == Decimal("0.0")
        assert rows[window].page_display.win_rate_pct == "0"


def test_source_comparator_ties_preserve_candidate_order_explicitly() -> None:
    module = _api()
    bars = _constant_bars(60)

    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, bars),),
        as_of=bars[-1].bar.bar_end,
    )
    segment = result.value.segments[0]

    assert {row.score for row in segment.results} == {Decimal("0.0")}
    assert segment.ranked_windows == (10, 20, 24, 30, 52)
    tie_gap = next(
        feature
        for feature in result.value.subfeatures
        if feature.name == "browser_tie_golden"
    )
    assert tie_gap.status.status == "evidence_required"
    assert tie_gap.value is None


def test_terminal_valuation_is_synthetic_and_remains_comparator_only() -> None:
    module = _api()
    rows = [("110", "90", "100")] * 19 + [("110", "80", "105")]
    bars = _bars(tuple(rows))

    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, bars),),
        as_of=bars[-1].bar.bar_end,
    )
    window20 = {row.window: row for row in result.value.segments[0].results}[20]

    assert window20.force_closed_at_end is True
    assert window20.trades[-1].synthetic_terminal is True
    assert window20.trades[-1].entry_bar_end == bars[-1].bar.bar_end
    assert window20.trades[-1].exit_bar_end == bars[-1].bar.bar_end
    for forbidden in ("action", "clear", "marker", "reference_trade"):
        assert not hasattr(window20.trades[-1], forbidden)


def test_owner_segments_are_listed_reset_and_default_to_latest() -> None:
    module = _api()
    old = _constant_bars(
        20,
        contract="RB2605",
        segment_id="rb:RB2605:old",
        start=date(2026, 1, 1),
    )
    new = _constant_bars(
        20,
        contract="RB2610",
        segment_id="rb:RB2610:new",
        start=date(2026, 3, 1),
    )

    result = module.compare_page_windows(
        _identity(),
        old + new,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, old), _owner(module, new)),
        as_of=new[-1].bar.bar_end,
    )

    assert [segment.segment_id for segment in result.value.segments] == [
        "rb:RB2605:old",
        "rb:RB2610:new",
    ]
    assert result.value.default_segment_id == "rb:RB2610:new"
    comparable = tuple(
        (
            row.window,
            row.cumulative_return_pct,
            row.max_drawdown_pct,
            row.trade_count,
            row.win_count,
            row.loss_count,
            row.win_rate_pct,
            row.force_closed_at_end,
            row.score,
            row.page_display,
        )
        for row in result.value.segments[0].results
    )
    assert comparable == tuple(
        (
            row.window,
            row.cumulative_return_pct,
            row.max_drawdown_pct,
            row.trade_count,
            row.win_count,
            row.loss_count,
            row.win_rate_pct,
            row.force_closed_at_end,
            row.score,
            row.page_display,
        )
        for row in result.value.segments[1].results
    )
    forbidden = {"cross_segment_ranking", "account_aggregation"}
    assert not forbidden & {field.name for field in fields(result.value)}
    for name in forbidden:
        assert not hasattr(result.value, name)


def test_guiyi_adapter_requires_authoritative_owner_segments() -> None:
    module = _api()
    bars = _constant_bars(20)

    with pytest.raises(TypeError, match="authoritative_segments"):
        module.compare_page_windows(
            _identity(),
            bars,
            module.VerifiedPageComparatorEvidence(),
            as_of=bars[-1].bar.bar_end,
        )


def test_real_product_reader_dataset_identity_flows_into_comparator(
    product_cases,
) -> None:
    module = _api()
    reader, query, fake = product_cases.paged_reader(
        prefix_bars=22,
        frequency="1d",
    )
    read_set = reader.load(replace(query, strategy="oscillation"), fake.as_of)
    bars = tuple(bar for bar in read_set.replay_bars if bar.bar.observation_eligible)
    owner = read_set.owners[0]
    authoritative = module.ComparatorOwnerSegment(
        product=query.product,
        physical_contract=owner.contract,
        segment_id=bars[0].bar.segment_id,
        start_trading_day=owner.start_trading_day,
        end_trading_day=owner.end_trading_day,
    )

    assert isinstance(reader, NewowProductReader)
    assert len(bars) == 20
    assert len({bar.bar.source_identity for bar in bars}) == 1
    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(authoritative,),
        as_of=read_set.as_of,
    )

    assert result.status == "ready"
    assert result.value.segments[0].source_bars.source_identities == (
        bars[0].bar.source_identity,
    )


@pytest.mark.parametrize(
    "conflicting, reason",
    [
        (False, "NEWOW_PAGE_COMPARATOR_DUPLICATE_FACT"),
        (True, "NEWOW_PAGE_COMPARATOR_CONFLICTING_FACT"),
    ],
)
def test_bar_fact_identity_distinguishes_duplicate_from_conflict(
    conflicting: bool,
    reason: str,
) -> None:
    module = _api()
    bars = _constant_bars(20)
    repeated = bars[9]
    if conflicting:
        repeated = replace(
            repeated,
            bar=replace(
                repeated.bar,
                open=Decimal("99"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("99"),
            ),
        )
    duplicated = bars[:10] + (repeated,) + bars[10:]

    with pytest.raises(ValueError, match=reason):
        module.compare_page_windows(
            _identity(),
            duplicated,
            module.VerifiedPageComparatorEvidence(),
            authoritative_segments=(_owner(module, bars),),
            as_of=bars[-1].bar.bar_end,
        )


def test_segment_carries_actual_source_range_separate_from_owner_authority() -> None:
    module = _api()
    bars = _constant_bars(20)
    owner = replace(
        _owner(module, bars),
        end_trading_day=bars[-1].bar.trading_day + timedelta(days=5),
    )
    as_of = bars[-1].bar.bar_end + timedelta(days=5)

    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(owner,),
        as_of=as_of,
    )
    segment = result.value.segments[0]

    assert segment.authoritative_start_trading_day == owner.start_trading_day
    assert segment.authoritative_end_trading_day == owner.end_trading_day
    assert segment.source_bars.count == 20
    assert segment.source_bars.first_trading_day == bars[0].bar.trading_day
    assert segment.source_bars.last_trading_day == bars[-1].bar.trading_day
    assert segment.source_bars.first_bar_end == bars[0].bar.bar_end
    assert segment.source_bars.last_bar_end == bars[-1].bar.bar_end
    assert segment.source_bars.source_identities == tuple(
        bar.bar.source_identity for bar in bars
    )
    assert segment.as_of == as_of
    assert segment.in_sample is True
    assert segment.repainting is False
    assert segment.repaint_status.status == "ready"
    assert segment.repaint_status.evidence_status == "RESEARCH_EVIDENCE_ONLY"
    assert segment.input_snapshot_status.status == "ready"
    assert segment.input_snapshot_status.evidence_status == "ACTIVE_CODE_VERIFIED"
    assert result.source_bars == (segment.source_bars,)


def test_segment_rejects_source_range_outside_owner_and_as_of() -> None:
    module = _api()
    bars = _constant_bars(20)
    owner = _owner(module, bars)
    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(owner,),
        as_of=bars[-1].bar.bar_end,
    )
    segment = result.value.segments[0]
    invalid_source = replace(
        segment.source_bars,
        last_trading_day=owner.end_trading_day + timedelta(days=1),
        last_bar_end=segment.as_of + timedelta(days=1),
    )

    with pytest.raises(
        ValueError, match="NEWOW_PAGE_COMPARATOR_INVALID_SEGMENT_RESULT"
    ):
        replace(segment, source_bars=invalid_source)


def test_public_price_return_and_score_facts_are_decimal() -> None:
    module = _api()
    bars = _constant_bars(20)

    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, bars),),
        as_of=bars[-1].bar.bar_end,
    )

    for row in result.value.segments[0].results:
        for value in (
            row.cumulative_return_pct,
            row.max_drawdown_pct,
            row.win_rate_pct,
            row.score,
        ):
            assert isinstance(value, Decimal)
        for trade in row.trades:
            assert isinstance(trade.entry_price, Decimal)
            assert isinstance(trade.exit_price, Decimal)
            assert isinstance(trade.return_pct, Decimal)


def test_latest_authoritative_segment_without_bars_never_falls_back() -> None:
    module = _api()
    old = _constant_bars(20)
    latest = module.ComparatorOwnerSegment(
        product="rb",
        physical_contract="RB2610",
        segment_id="rb:RB2610:empty",
        start_trading_day=date(2026, 3, 1),
        end_trading_day=date(2026, 3, 31),
    )

    result = module.compare_page_windows(
        _identity(),
        old,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, old), latest),
        as_of=old[-1].bar.bar_end,
    )

    assert result.status == "unavailable"
    assert result.reason_code == "NEWOW_PAGE_COMPARATOR_LATEST_SEGMENT_EMPTY"
    assert result.value.default_segment_id == latest.segment_id
    assert result.value.segments[-1].status.status == "unavailable"
    assert result.value.segments[-1].results == ()
    assert result.value.segments[-1].source_bars.count == 0
    assert result.value.segments[-1].source_bars.first_bar_end is None
    assert result.value.segments[-1].source_bars.last_bar_end is None
    assert result.value.segments[-1].input_snapshot_status.status == "unavailable"


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_strategy",
        "wrong_frequency",
        "ineligible",
        "future",
        "duplicate_time",
        "duplicate_daily_trading_day",
        "owner_relabel",
    ],
)
def test_malformed_identity_owner_and_time_facts_fail_closed(mutation: str) -> None:
    module = _api()
    identity = _identity()
    bars = _constant_bars(20)
    owners = (_owner(module, bars),)
    as_of = bars[-1].bar.bar_end
    if mutation == "wrong_strategy":
        identity = ProductIdentity(
            "rb",
            ProductStrategy.TREND,
            ProductFrequency.DAILY,
            identity.formula_versions,
        )
    elif mutation == "wrong_frequency":
        bars = (replace(bars[0], frequency=ProductFrequency.HOURLY),) + bars[1:]
    elif mutation == "ineligible":
        bars = (
            replace(
                bars[0],
                bar=replace(bars[0].bar, observation_eligible=False),
            ),
        ) + bars[1:]
    elif mutation == "future":
        as_of = bars[-1].bar.bar_end - timedelta(seconds=1)
    elif mutation == "duplicate_time":
        bars = (
            bars[:10]
            + (
                replace(
                    bars[10],
                    bar=replace(bars[10].bar, bar_end=bars[9].bar.bar_end),
                ),
            )
            + bars[11:]
        )
    elif mutation == "duplicate_daily_trading_day":
        bars = (
            bars[:10]
            + (
                replace(
                    bars[10],
                    bar=replace(bars[10].bar, trading_day=bars[9].bar.trading_day),
                ),
            )
            + bars[11:]
        )
    else:
        owners = (replace(owners[0], physical_contract="RB2610"),)

    with pytest.raises(ValueError, match="NEWOW_PAGE_COMPARATOR"):
        module.compare_page_windows(
            identity,
            bars,
            module.VerifiedPageComparatorEvidence(),
            authoritative_segments=owners,
            as_of=as_of,
        )


def test_hourly_owner_allows_multiple_ordered_bars_per_trading_day() -> None:
    module = _api()
    bars = _constant_bars(20, frequency="60m")

    result = module.compare_page_windows(
        _identity("60m"),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, bars),),
        as_of=bars[-1].bar.bar_end,
    )

    assert result.status == "ready"
    assert result.value.segments[0].bar_count == 20


def test_non_product_bar_input_fails_closed_with_comparator_reason() -> None:
    module = _api()

    with pytest.raises(
        ValueError, match="NEWOW_PAGE_COMPARATOR_INPUT_IDENTITY_INVALID"
    ):
        module.compare_page_windows(
            _identity(),
            (object(),),
            module.VerifiedPageComparatorEvidence(),
            authoritative_segments=(),
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
        )


def _frozen_evidence_bars(root: Path) -> tuple[ProductBar, ...]:
    payload = json.loads((root / "sources/page-cases/600519-SH/day.json").read_text())
    table = payload["source_response"]["tables"][0]["table"]
    return tuple(
        ProductBar(
            NewowDailyBar(
                product="rb",
                physical_contract="RB2605",
                segment_id="rb:RB2605:frozen-page-oracle",
                trading_day=date.fromisoformat(trading_day),
                bar_end=datetime.combine(
                    date.fromisoformat(trading_day), datetime.min.time(), UTC
                )
                + timedelta(hours=7),
                open=Decimal(str(table["open"][index])),
                high=Decimal(str(table["high"][index])),
                low=Decimal(str(table["low"][index])),
                close=Decimal(str(table["close"][index])),
                volume=table["volume"][index],
                open_interest=0,
                source_identity=f"frozen-page-oracle:{index}",
                observation_eligible=True,
                completed=True,
            ),
            ProductFrequency.DAILY,
        )
        for index, trading_day in enumerate(table["time"])
    )


def test_frozen_601_bar_source_oracle_matches_all_rows_and_rank() -> None:
    root_value = os.environ.get("GUIYI_NEWOW_TASK13_EVIDENCE_ROOT")
    if root_value is None:
        pytest.skip("set GUIYI_NEWOW_TASK13_EVIDENCE_ROOT for frozen local evidence")
    assert root_value is not None
    module = _api()
    bars = _frozen_evidence_bars(Path(root_value))

    result = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, bars),),
        as_of=bars[-1].bar.bar_end,
    )
    segment = result.value.segments[0]
    expected = {
        10: (
            Decimal("-9.663846482296469"),
            Decimal("23.99066878401761"),
            20,
            Decimal("60.0"),
            False,
            Decimal("0.40184958751414296"),
            ("-9.66", "23.99", "60.0"),
        ),
        20: (
            Decimal("2.114659740773029"),
            Decimal("20.986247212469504"),
            10,
            Decimal("60.0"),
            True,
            Decimal("0.8902002112871927"),
            ("2.11", "20.99", "60.0"),
        ),
        24: (
            Decimal("2.667480521315004"),
            Decimal("17.2293463440191"),
            8,
            Decimal("50.0"),
            True,
            Decimal("1.0873125368652388"),
            ("2.67", "17.23", "50.0"),
        ),
        30: (
            Decimal("-10.395065701222599"),
            Decimal("24.00742566198754"),
            5,
            Decimal("40.0"),
            False,
            Decimal("0.377413892720182"),
            ("-10.40", "24.01", "40.0"),
        ),
        52: (
            Decimal("19.155879410269073"),
            Decimal("22.04303356386306"),
            5,
            Decimal("100.0"),
            False,
            Decimal("1.4086374942737225"),
            ("19.16", "22.04", "100.0"),
        ),
    }

    assert len(bars) == 601
    for row in segment.results:
        cumulative, drawdown, trades, win_rate, forced, score, display = expected[
            row.window
        ]
        assert row.cumulative_return_pct == cumulative
        assert row.max_drawdown_pct == drawdown
        assert row.trade_count == trades
        assert row.win_rate_pct == win_rate
        assert row.force_closed_at_end is forced
        assert row.score == score
        assert (
            row.page_display.cumulative_return_pct,
            row.page_display.max_drawdown_pct,
            row.page_display.win_rate_pct,
        ) == display
    assert segment.ranked_windows == (52, 24, 20, 10, 30)


def test_comparator_terminal_valuation_does_not_close_reference(product_cases) -> None:
    module = _api()
    case = product_cases.open()
    projector = ReferenceTradeProjector()
    before = projector.project(case.replay, case.boundaries, case.as_of)
    bars = _constant_bars(20)

    comparator = module.compare_page_windows(
        _identity(),
        bars,
        module.VerifiedPageComparatorEvidence(),
        authoritative_segments=(_owner(module, bars),),
        as_of=bars[-1].bar.bar_end,
    )
    after = projector.project(case.replay, case.boundaries, case.as_of)

    assert comparator.value.segments[0].results[1].force_closed_at_end is True
    assert after == before
    assert after.trades[0].status == "OPEN"
