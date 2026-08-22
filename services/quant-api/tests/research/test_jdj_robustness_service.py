from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from app.research.jdj.jdj_events import (
    JdjDirection,
    JdjSetupKind,
    JdjTrendFollowTriggerEvent,
    _canonical_trend_follow_event_id,
)
from app.research.jdj.jdj_research import (
    JDJ_CANDIDATE_SOURCE_EVENT_KINDS,
    JdjBatchResearchResult,
    JdjDetailedCandidateResult,
    JdjEventOutcomeRecord,
    JdjResearchResult,
    JdjSourceUnavailableError,
)
from app.research.robustness.jdj_robustness import (
    JdjActive60RobustnessProtocolError,
    JdjActive60RobustnessRequest,
    JdjRobustnessStatus,
    load_jdj_active60_robustness_protocol,
)
from app.research.robustness.jdj_robustness_service import (
    JdjActive60RobustnessService,
    summarize_jdj_robustness_horizon,
)
from app.market_data.price_outcome import (
    PriceDirectionalOutcome,
    PriceHorizonEvaluation,
)


_CANDIDATES = tuple(JDJ_CANDIDATE_SOURCE_EVENT_KINDS)
_HORIZONS = (3, 5, 8, 20)
_SINCE = date(2023, 1, 1)
_THROUGH = date(2026, 8, 20)


class _RecordingBatchRunner:
    def __init__(
        self,
        results: dict[str, JdjBatchResearchResult | Exception] | None = None,
    ) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, date, date]] = []

    def run_batch(
        self,
        *,
        symbol: str,
        since: date,
        through: date,
    ) -> JdjBatchResearchResult:
        self.calls.append((symbol, since, through))
        result = self.results.get(symbol)
        if isinstance(result, Exception):
            raise result
        return result or _batch(symbol)


def _outcome(
    horizon: int,
    directional_return_bps: str,
    *,
    mfe_bps: str | None = None,
    mae_bps: str | None = None,
) -> PriceDirectionalOutcome:
    value = Decimal(directional_return_bps)
    return PriceDirectionalOutcome(
        horizon=horizon,
        directional_return_bps=value,
        mfe_bps=Decimal(mfe_bps) if mfe_bps is not None else value + 10,
        mae_bps=Decimal(mae_bps) if mae_bps is not None else value - 10,
    )


def _event(
    symbol: str,
    trading_day: date,
    sequence: int,
    *,
    direction: JdjDirection = JdjDirection.LONG,
) -> JdjTrendFollowTriggerEvent:
    observed_at = datetime(
        trading_day.year,
        trading_day.month,
        trading_day.day,
        1,
        sequence + 2,
        tzinfo=UTC,
    )
    reaction_at = observed_at - timedelta(minutes=1)
    trigger_level = Decimal("100") + Decimal(sequence)
    contract = f"{symbol.upper()}2701"
    return JdjTrendFollowTriggerEvent(
        event_id=_canonical_trend_follow_event_id(
            candidate_id=_CANDIDATES[0],
            symbol=symbol,
            contract=contract,
            segment_start_trading_day=_SINCE,
            direction=direction,
            reaction_at=reaction_at,
            observed_at=observed_at,
            trigger_level=trigger_level,
        ),
        source_kind="jdj_1m",
        setup_kind=JdjSetupKind.TREND_FOLLOW,
        candidate_id=_CANDIDATES[0],
        source_event_kind=JDJ_CANDIDATE_SOURCE_EVENT_KINDS[_CANDIDATES[0]],
        direction=direction,
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=_SINCE,
        trading_day=trading_day,
        observed_at=observed_at,
        segment_bar_index=sequence + 2,
        trend_snapshot_observed_at=observed_at - timedelta(minutes=2),
        reaction_at=reaction_at,
        ema20_at_reaction=Decimal("99"),
        trigger_level=trigger_level,
        observation_close=Decimal("101"),
    )


def _detail(
    candidate_id: str,
    symbol: str,
    records: tuple[JdjEventOutcomeRecord, ...] = (),
    directions: tuple[JdjDirection, ...] | None = None,
) -> JdjDetailedCandidateResult:
    event_directions = directions or tuple(
        JdjDirection.LONG for _ in records
    )
    events = tuple(
        _event(symbol, record.trading_day, index, direction=direction)
        for index, (record, direction) in enumerate(
            zip(records, event_directions, strict=True)
        )
    )
    zero = PriceHorizonEvaluation(0, None, None, None)
    deliberately_unused = PriceHorizonEvaluation(
        len(records),
        Decimal("999"),
        Decimal("999"),
        Decimal("-999"),
    )
    return JdjDetailedCandidateResult(
        result=JdjResearchResult(
            candidate_id=candidate_id,
            source_event_kind=JDJ_CANDIDATE_SOURCE_EVENT_KINDS[candidate_id],
            products=(symbol,),
            segment_count=1,
            evaluable_bar_count=2000,
            trigger_count_long=sum(
                event.direction is JdjDirection.LONG for event in events
            ),
            trigger_count_short=sum(
                event.direction is JdjDirection.SHORT for event in events
            ),
            horizon_summary={
                horizon: deliberately_unused if records else zero
                for horizon in _HORIZONS
            },
            events=events,
        ),
        event_outcomes=records,
    )


def _record(
    symbol: str,
    trading_day: date,
    sequence: int,
    returns: dict[int, str | None],
    *,
    direction: JdjDirection = JdjDirection.LONG,
) -> JdjEventOutcomeRecord:
    event = _event(symbol, trading_day, sequence, direction=direction)
    return JdjEventOutcomeRecord(
        event_id=event.event_id,
        trading_day=trading_day,
        outcomes={
            horizon: (
                None
                if (value := returns[horizon]) is None
                else _outcome(horizon, value)
            )
            for horizon in _HORIZONS
        },
    )


def _batch(
    symbol: str,
    first_candidate_records: tuple[JdjEventOutcomeRecord, ...] = (),
    *,
    observed_since: date = _SINCE,
    first_candidate_directions: tuple[JdjDirection, ...] | None = None,
) -> JdjBatchResearchResult:
    return JdjBatchResearchResult(
        symbol=symbol,
        observed_since=observed_since,
        observed_through=_THROUGH,
        candidates=tuple(
            _detail(
                candidate_id,
                symbol,
                first_candidate_records if index == 0 else (),
                first_candidate_directions if index == 0 else None,
            )
            for index, candidate_id in enumerate(_CANDIDATES)
        ),
    )


def _service(
    runner: _RecordingBatchRunner,
) -> tuple[JdjActive60RobustnessService, object]:
    protocol = load_jdj_active60_robustness_protocol()
    return (
        JdjActive60RobustnessService(protocol, jdj_research=runner),
        protocol,
    )


def test_run_uses_exact_window_once_per_symbol_and_returns_180_candidate_major_rows() -> None:
    runner = _RecordingBatchRunner()
    service, protocol = _service(runner)

    report = service.run(
        JdjActive60RobustnessRequest("jdj_active60_robustness_v1")
    )

    products = protocol.cross_symbol_products  # type: ignore[attr-defined]
    assert runner.calls == [
        (symbol, date(2023, 1, 1), date(2026, 8, 20))
        for symbol in products
    ]
    assert len(report.cross_symbol_results) == 180
    assert tuple(
        (row.candidate_id, row.symbol) for row in report.cross_symbol_results
    ) == tuple(
        (candidate_id, symbol)
        for candidate_id in _CANDIDATES
        for symbol in products
    )
    assert all(
        row.status is JdjRobustnessStatus.AVAILABLE
        and row.event_count == 0
        and row.reason_code is None
        for row in report.cross_symbol_results
    )


def test_horizon_summary_uses_decimal_positive_rate_and_medians() -> None:
    outcomes = (
        _outcome(3, "-2", mfe_bps="5", mae_bps="-8"),
        _outcome(3, "0", mfe_bps="6", mae_bps="-7"),
        _outcome(3, "3", mfe_bps="9", mae_bps="-4"),
        _outcome(3, "4", mfe_bps="12", mae_bps="-1"),
    )

    summary = summarize_jdj_robustness_horizon(outcomes)

    assert summary.sample_count == 4
    assert summary.historical_positive_outcome_rate == Decimal("0.5")
    assert summary.median_directional_return_bps == Decimal("1.5")
    assert summary.median_mfe_bps == Decimal("7.5")
    assert summary.median_mae_bps == Decimal("-5.5")
    assert summarize_jdj_robustness_horizon(()) == replace(
        summary,
        sample_count=0,
        historical_positive_outcome_rate=None,
        median_directional_return_bps=None,
        median_mfe_bps=None,
        median_mae_bps=None,
    )


def test_typed_source_unavailable_emits_three_cells_and_continues() -> None:
    protocol = load_jdj_active60_robustness_protocol()
    unavailable_symbol = protocol.cross_symbol_products[7]
    runner = _RecordingBatchRunner(
        {unavailable_symbol: JdjSourceUnavailableError()}
    )
    service = JdjActive60RobustnessService(protocol, jdj_research=runner)

    report = service.run(
        JdjActive60RobustnessRequest("jdj_active60_robustness_v1")
    )

    unavailable = tuple(
        row
        for row in report.cross_symbol_results
        if row.symbol == unavailable_symbol
    )
    assert len(runner.calls) == 60
    assert len(unavailable) == 3
    assert all(
        row.status is JdjRobustnessStatus.UNAVAILABLE
        and row.reason_code == "JDJ_SOURCE_UNAVAILABLE"
        and row.event_count is None
        and row.horizon_summary is None
        and row.yearly is None
        for row in unavailable
    )
    assert report.quality_flags[0] == "SOURCE_UNAVAILABLE_PRESENT"


def test_yearly_summaries_use_existing_event_records_without_reload() -> None:
    symbol = "a"
    records = (
        _record(
            symbol,
            date(2023, 6, 1),
            0,
            {3: "-2", 5: "1", 8: None, 20: None},
        ),
        _record(
            symbol,
            date(2023, 8, 1),
            1,
            {3: "4", 5: "3", 8: "2", 20: None},
            direction=JdjDirection.SHORT,
        ),
        _record(
            symbol,
            date(2026, 8, 20),
            2,
            {3: "6", 5: None, 8: None, 20: None},
        ),
    )
    runner = _RecordingBatchRunner(
        {
            symbol: _batch(
                symbol,
                records,
                first_candidate_directions=(
                    JdjDirection.LONG,
                    JdjDirection.SHORT,
                    JdjDirection.LONG,
                ),
            )
        }
    )
    service, _ = _service(runner)

    report = service.run(
        JdjActive60RobustnessRequest("jdj_active60_robustness_v1")
    )

    row = report.cross_symbol_results[0]
    assert len(runner.calls) == 60
    assert row.event_count == 3
    assert row.long_event_count == 2
    assert row.short_event_count == 1
    assert row.event_rate_per_1000_evaluable == Decimal("1.5")
    assert row.horizon_summary is not None
    assert row.horizon_summary[3].sample_count == 3
    assert row.horizon_summary[3].historical_positive_outcome_rate == (
        Decimal(2) / Decimal(3)
    )
    assert row.horizon_summary[3].median_directional_return_bps == Decimal("4")
    assert row.yearly is not None
    assert tuple(row.yearly) == (2023, 2024, 2025, 2026)
    assert row.yearly[2023].event_count == 2
    assert row.yearly[2023].horizon_sample_count == {
        3: 2,
        5: 2,
        8: 1,
        20: 0,
    }
    assert row.yearly[2023].horizon_positive_outcome_rate[3] == Decimal("0.5")
    assert row.yearly[2023].horizon_median_directional_return_bps[3] == Decimal(
        "1"
    )
    assert row.yearly[2024].event_count == 0
    assert row.yearly[2024].horizon_positive_outcome_rate[3] is None
    assert row.yearly[2026].event_count == 1


def test_sector_summary_gives_each_symbol_one_median_vote() -> None:
    a_single = _record(
        "a",
        date(2025, 1, 2),
        0,
        {3: "10", 5: None, 8: None, 20: None},
    )
    a_duplicate = _record(
        "a",
        date(2025, 1, 3),
        1,
        {3: "10", 5: None, 8: None, 20: None},
    )
    ap = _record(
        "ap",
        date(2025, 1, 2),
        0,
        {3: "-2", 5: None, 8: None, 20: None},
    )

    one_runner = _RecordingBatchRunner(
        {"a": _batch("a", (a_single,)), "ap": _batch("ap", (ap,))}
    )
    duplicated_runner = _RecordingBatchRunner(
        {
            "a": _batch("a", (a_single, a_duplicate)),
            "ap": _batch("ap", (ap,)),
        }
    )
    one_report = _service(one_runner)[0].run(
        JdjActive60RobustnessRequest("jdj_active60_robustness_v1")
    )
    duplicated_report = _service(duplicated_runner)[0].run(
        JdjActive60RobustnessRequest("jdj_active60_robustness_v1")
    )

    one_sector = one_report.sector_summaries[0].horizon_summary[3]
    duplicated_sector = duplicated_report.sector_summaries[0].horizon_summary[3]
    assert len(one_runner.calls) == len(duplicated_runner.calls) == 60
    assert one_sector == duplicated_sector
    assert one_sector.symbols_with_samples == 2
    assert one_sector.positive_median_symbol_count == 1
    assert one_sector.negative_median_symbol_count == 1
    assert one_sector.median_of_symbol_median_return_bps == Decimal("4")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("common_since", date(2023, 1, 2)),
        ("common_through", date(2026, 8, 21)),
        ("candidate_ids", tuple(reversed(_CANDIDATES))),
        ("cross_symbol_products", ("jm",)),
        ("sector_groups", MappingProxyType({"black": ("jm",)})),
        ("prospective_consumed", True),
    ),
)
def test_global_or_oos_protocol_drift_fails_before_first_batch_call(
    field: str,
    value: object,
) -> None:
    protocol = load_jdj_active60_robustness_protocol()
    object.__setattr__(protocol, field, value)
    runner = _RecordingBatchRunner()
    service = JdjActive60RobustnessService(protocol, jdj_research=runner)

    with pytest.raises(
        JdjActive60RobustnessProtocolError,
        match="JDJ_ACTIVE60_ROBUSTNESS_PROTOCOL_INVALID",
    ):
        service.run(
            JdjActive60RobustnessRequest("jdj_active60_robustness_v1")
        )

    assert runner.calls == []


def test_report_has_only_fixed_order_quality_flags() -> None:
    protocol = load_jdj_active60_robustness_protocol()
    short_symbol = protocol.cross_symbol_products[-1]
    runner = _RecordingBatchRunner(
        {short_symbol: _batch(short_symbol, observed_since=date(2024, 1, 1))}
    )
    service = JdjActive60RobustnessService(protocol, jdj_research=runner)

    report = service.run(
        JdjActive60RobustnessRequest("jdj_active60_robustness_v1")
    )

    assert report.quality_flags == (
        "SYMBOL_WITHOUT_EVENT",
        "HORIZON_WITHOUT_SAMPLE",
        "SHORT_HISTORY_PRESENT",
    )


def test_unexpected_batch_failure_is_not_downgraded_to_unavailable() -> None:
    runner = _RecordingBatchRunner({"a": RuntimeError("unexpected")})
    service, _ = _service(runner)

    with pytest.raises(RuntimeError, match="unexpected"):
        service.run(
            JdjActive60RobustnessRequest("jdj_active60_robustness_v1")
        )

    assert runner.calls == [("a", _SINCE, _THROUGH)]
