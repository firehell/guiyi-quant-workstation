"""Read-only JM 5m causal research from Catalog-resolved Canonical inputs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from collections.abc import Mapping

from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.futures_validation import (
    build_newow_research_bars,
    build_newow_strategy_replay_segments,
)
from guiyi_quant.newow.research_backtest import (
    BacktestCostSnapshot,
    BacktestExecutionConstraint,
    BacktestCosts,
    BacktestOffsetFees,
    NewowResearchBar,
    NewowStrategyReplaySegment,
    ResearchBacktestResult,
    ResearchStrategy,
    build_strategy_intents_from_replay_segments,
    run_causal_long_only_backtest,
    validate_research_bars,
)
from guiyi_quant.newow.research_evidence import CostStressScenario, stress_cost_snapshots
from guiyi_quant.newow.research_walk_forward import (
    WalkForwardFold,
    WalkForwardValidationResult,
    run_fixed_formula_walk_forward,
)


@dataclass(frozen=True, slots=True)
class JMPilotInput:
    bars: tuple[NewowResearchBar, ...]
    replay_segments: tuple[NewowStrategyReplaySegment, ...]
    requested_since: date
    actual_through: date
    input_sha256: str

    def __post_init__(self) -> None:
        if (
            not self.bars
            or not self.replay_segments
            or type(self.requested_since) is not date
            or type(self.actual_through) is not date
            or self.requested_since > self.actual_through
            or len(self.input_sha256) != 64
            or any(bar.product != "jm" or bar.frequency != "5m" for bar in self.bars)
        ):
            raise ValueError("JM_PILOT_INPUT_INVALID")
        validate_research_bars(self.bars)
        eligible = tuple(
            bar for segment in self.replay_segments for bar in segment.bars
            if bar.observation_eligible
        )
        if eligible != self.bars:
            raise ValueError("JM_PILOT_INPUT_INVALID")


@dataclass(frozen=True, slots=True)
class JMPilotResearchResult:
    input_sha256: str
    actual_through: date
    selection_overlap: bool
    retrospective_execution_facts: bool
    full_sample: ResearchBacktestResult
    walk_forward_by_scenario: tuple[
        tuple[CostStressScenario, WalkForwardValidationResult], ...
    ]


def _decimal_fact(value: object, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("EXECUTION_FACTS_MISSING")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("EXECUTION_FACTS_MISSING") from None
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise ValueError("EXECUTION_FACTS_MISSING")
    return result


def _date_fact(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("EXECUTION_FACTS_MISSING")
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise ValueError("EXECUTION_FACTS_MISSING") from None
    if result.isoformat() != value:
        raise ValueError("EXECUTION_FACTS_MISSING")
    return result


def _timestamp_fact(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("EXECUTION_FACTS_MISSING")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("EXECUTION_FACTS_MISSING") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("EXECUTION_FACTS_MISSING")
    return result


def adapt_jm_execution_facts(
    source: JMPilotInput,
    raw: Mapping[str, object],
) -> tuple[
    tuple[BacktestCostSnapshot, ...],
    tuple[BacktestExecutionConstraint, ...],
    str,
]:
    """Validate dated RQData facts; refuse implicit fee/limit/tick defaults."""

    if not isinstance(source, JMPilotInput) or not isinstance(raw, Mapping):
        raise ValueError("EXECUTION_FACTS_MISSING")
    try:
        if (
            raw["schema_version"] != 1
            or raw["source"] != "rqdata"
            or not isinstance(raw["plan_hash"], str)
            or len(raw["plan_hash"]) != 64
        ):
            raise ValueError("EXECUTION_FACTS_MISSING")
        captured_at = _timestamp_fact(raw["captured_at"])
        contracts = raw["contracts"]
        if not isinstance(contracts, dict) or set(contracts) != {
            bar.physical_contract for bar in source.bars
        }:
            raise ValueError("EXECUTION_FACTS_MISSING")
        amendment = raw.get("tick_amendment")
        if amendment is not None:
            if (
                not isinstance(amendment, dict)
                or amendment.get("source") != "rqdata.Instrument.tick_size()"
                or not isinstance(amendment.get("original_sha256"), str)
                or len(amendment["original_sha256"]) != 64
                or not isinstance(amendment.get("ticks"), dict)
                or set(amendment["ticks"]) != set(contracts)
            ):
                raise ValueError("EXECUTION_FACTS_MISSING")
            captured_at = max(captured_at, _timestamp_fact(amendment["captured_at"]))
        fact_hash = sha256(json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        snapshots: list[BacktestCostSnapshot] = []
        constraints: list[BacktestExecutionConstraint] = []
        for contract, body in contracts.items():
            if not isinstance(body, dict) or not isinstance(contract, str):
                raise ValueError("EXECUTION_FACTS_MISSING")
            owned = tuple(bar for bar in source.bars if bar.physical_contract == contract)
            days = {bar.trading_day for bar in owned}
            start = _date_fact(body["start"])
            end = _date_fact(body["end"])
            if not days or start > min(days) or end < max(days):
                raise ValueError("EXECUTION_FACTS_MISSING")
            instrument = body["instrument"]
            if not isinstance(instrument, dict):
                raise ValueError("EXECUTION_FACTS_MISSING")
            multiplier = _decimal_fact(instrument["contract_multiplier"], positive=True)
            tick = _decimal_fact(instrument["tick_size"], positive=True)
            if amendment is not None and tick != _decimal_fact(
                amendment["ticks"][contract], positive=True
            ):
                raise ValueError("EXECUTION_FACTS_MISSING")
            parameters = body["parameters"]
            daily = body["daily"]
            if not isinstance(parameters, list) or not isinstance(daily, list):
                raise ValueError("EXECUTION_FACTS_MISSING")
            parameter_by_day = {_date_fact(row["date"]): row for row in parameters}
            daily_by_day = {_date_fact(row["date"]): row for row in daily}
            if (
                len(parameter_by_day) != len(parameters)
                or len(daily_by_day) != len(daily)
                or set(parameter_by_day) != days
                or set(daily_by_day) != days
            ):
                raise ValueError("EXECUTION_FACTS_MISSING")
            for day in sorted(days):
                parameter = parameter_by_day[day]
                limits = daily_by_day[day]
                if not isinstance(parameter, dict) or not isinstance(limits, dict):
                    raise ValueError("EXECUTION_FACTS_MISSING")
                commission_type = parameter["commission_type"]
                if not isinstance(commission_type, str) or commission_type.lower() not in {
                    "by_money", "by_volume"
                }:
                    raise ValueError("EXECUTION_FACTS_MISSING")
                open_commission = _decimal_fact(parameter["open_commission"])
                close_commission = _decimal_fact(parameter["close_commission"])
                close_today = _decimal_fact(parameter["close_commission_today"])
                _decimal_fact(parameter["long_margin_ratio"], positive=True)
                if not isinstance(parameter["trade_unit"], str) or not parameter["trade_unit"]:
                    raise ValueError("EXECUTION_FACTS_MISSING")
                if not isinstance(parameter["price_unit"], str) or not parameter["price_unit"]:
                    raise ValueError("EXECUTION_FACTS_MISSING")
                money = commission_type.lower() == "by_money"
                fees = BacktestOffsetFees(
                    open_rate=open_commission if money else Decimal(0),
                    open_per_contract=Decimal(0) if money else open_commission,
                    close_today_rate=close_today if money else Decimal(0),
                    close_today_per_contract=Decimal(0) if money else close_today,
                    close_yesterday_rate=close_commission if money else Decimal(0),
                    close_yesterday_per_contract=Decimal(0) if money else close_commission,
                )
                snapshots.append(BacktestCostSnapshot(
                    product="jm", physical_contract=contract,
                    effective_from=day, effective_to=day + timedelta(days=1),
                    captured_at=captured_at,
                    source_identity=f"rqdata:{fact_hash}:{contract}:{day.isoformat()}",
                    costs=BacktestCosts(
                        contract_multiplier=multiplier, price_tick=tick,
                        slippage_ticks=1,
                    ),
                    offset_fees=fees,
                ))
                up = _decimal_fact(limits["limit_up"], positive=True)
                down = _decimal_fact(limits["limit_down"], positive=True)
                _decimal_fact(limits["settlement"], positive=True)
                _decimal_fact(limits["prev_settlement"], positive=True)
                if up <= down:
                    raise ValueError("EXECUTION_FACTS_MISSING")
                for bar in owned:
                    if bar.trading_day == day:
                        constraints.append(BacktestExecutionConstraint(
                            bar_source_identity=bar.source_identity,
                            physical_contract=contract,
                            limit_up=up, limit_down=down,
                            captured_at=captured_at,
                            source_identity=f"rqdata:{fact_hash}:{contract}:{day.isoformat()}:limit",
                        ))
        return tuple(snapshots), tuple(constraints), fact_hash
    except (KeyError, TypeError, AttributeError, InvalidOperation, ValueError):
        raise ValueError("EXECUTION_FACTS_MISSING") from None


def _input_sha256(
    replay_segments: tuple[NewowStrategyReplaySegment, ...],
) -> str:
    payload = [
        [
            [
                bar.source_identity, bar.physical_contract, bar.segment_id,
                bar.trading_day.isoformat(), bar.bar_end.isoformat(),
                *(str(value) for value in (
                    bar.open, bar.high, bar.low, bar.close, bar.volume,
                    bar.open_interest, bar.turnover,
                )),
                bar.observation_eligible,
            ]
            for bar in segment.bars
        ]
        for segment in replay_segments
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def load_jm_pilot_input(
    market_data: MarketDataService,
    *,
    since: date,
    actual_through: date,
) -> JMPilotInput:
    """Use MDS rank1 owners and verified physical prefixes, never a file glob."""

    if type(since) is not date or type(actual_through) is not date or since > actual_through:
        raise ValueError("JM_PILOT_WINDOW_INVALID")
    loaded = ActualDominantResearchSegmentLoader(market_data).load(
        symbol="jm", frequencies=(BarFrequency.M5,),
        since=since, through=actual_through,
    )
    actual = build_newow_research_bars(
        loaded.results[BarFrequency.M5],
        authoritative_segments=loaded.authoritative_segments,
        expected_product="jm", expected_frequency=BarFrequency.M5,
    )
    observed = tuple(
        segment for segment in loaded.authoritative_segments
        if any(segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
               for bar in actual)
    )
    physical = tuple(
        market_data.query_contract_trading_days(ContractTradingDayQuery(
            "jm", segment.contract, BarFrequency.M5,
            segment.start_trading_day - timedelta(days=30),
            max(bar.trading_day for bar in actual if
                segment.start_trading_day <= bar.trading_day <= segment.end_trading_day),
        ))
        for segment in observed
    )
    replay = build_newow_strategy_replay_segments(
        actual,
        authoritative_segments=loaded.authoritative_segments,
        physical_prefix_results=physical,
        expected_product="jm", expected_frequency=BarFrequency.M5,
    )
    # Earlier mapped observations are warm-up for this fixed near-year window.
    scoped = tuple(
        NewowStrategyReplaySegment(tuple(
            bar if bar.trading_day >= since else replace(
                bar, observation_eligible=False, series_kind="contract",
                source_identity=(
                    f"canonical:contract:jm:5m:{bar.physical_contract}:"
                    f"{bar.trading_day.isoformat()}:{bar.bar_end.isoformat()}"
                ),
            )
            for bar in segment.bars
        ))
        for segment in replay
    )
    scored = tuple(bar for bar in actual if bar.trading_day >= since)
    if not scored or scored[-1].trading_day != actual_through:
        raise ValueError("JM_PILOT_COMPLETED_INPUT_MISSING")
    return JMPilotInput(
        bars=scored, replay_segments=scoped, requested_since=since,
        actual_through=actual_through,
        input_sha256=_input_sha256(scoped),
    )


def load_jm_execution_bars(
    market_data: MarketDataService,
    *,
    since: date,
    actual_through: date,
) -> tuple[NewowResearchBar, ...]:
    """MDS-verified rank1 completed 1m Bars for Paper's separate fill clock."""

    if type(since) is not date or type(actual_through) is not date or since > actual_through:
        raise ValueError("JM_PILOT_WINDOW_INVALID")
    loaded = ActualDominantResearchSegmentLoader(market_data).load(
        symbol="jm", frequencies=(BarFrequency.M1,),
        since=since, through=actual_through,
    )
    actual = build_newow_research_bars(
        loaded.results[BarFrequency.M1],
        authoritative_segments=loaded.authoritative_segments,
        expected_product="jm", expected_frequency=BarFrequency.M1,
    )
    scored = tuple(bar for bar in actual if bar.trading_day >= since)
    if not scored or scored[-1].trading_day != actual_through:
        raise ValueError("JM_PILOT_COMPLETED_INPUT_MISSING")
    return scored


def _fixed_folds(bars: tuple[NewowResearchBar, ...]) -> tuple[WalkForwardFold, ...]:
    first, last = bars[0].trading_day, bars[-1].trading_day
    if first > date(2026, 3, 31) or last < date(2026, 10, 1):
        raise ValueError("JM_PILOT_WALK_FORWARD_WINDOW_INSUFFICIENT")
    return (
        WalkForwardFold("2026Q2", first, date(2026, 3, 31),
                        date(2026, 4, 1), date(2026, 6, 30)),
        WalkForwardFold("2026Q3", first, date(2026, 6, 30),
                        date(2026, 7, 1), date(2026, 9, 30)),
        WalkForwardFold("2026Oct", first, date(2026, 9, 30),
                        date(2026, 10, 1), last),
    )


def run_jm_pilot_research(
    source: JMPilotInput,
    *,
    cost_snapshots: tuple[BacktestCostSnapshot, ...],
    execution_constraints: tuple[BacktestExecutionConstraint, ...],
) -> JMPilotResearchResult:
    """Run sourced retrospective execution checks; selection year overlaps folds."""

    if (
        not isinstance(source, JMPilotInput)
        or not cost_snapshots
        or not execution_constraints
        or any(snapshot.offset_fees is None for snapshot in cost_snapshots)
        or {item.bar_source_identity for item in execution_constraints}
        != {bar.source_identity for bar in source.bars}
    ):
        raise ValueError("EXECUTION_FACTS_MISSING")
    intents, versions = build_strategy_intents_from_replay_segments(
        source.replay_segments, ResearchStrategy.DUAL_FUSION,
    )
    ends = {bar.bar_end for bar in source.bars}
    full = run_causal_long_only_backtest(
        source.bars,
        tuple(intent for intent in intents if intent.signal_bar_end in ends),
        cost_snapshots=cost_snapshots,
        execution_constraints=execution_constraints,
        require_execution_facts=True,
        require_offset_fees=True,
        strategy=ResearchStrategy.DUAL_FUSION,
        signal_formula_versions=versions,
    )
    folds = _fixed_folds(source.bars)
    scenarios = tuple(
        (
            scenario,
            run_fixed_formula_walk_forward(
                source.bars, folds, strategy=ResearchStrategy.DUAL_FUSION,
                strategy_replay_segments=source.replay_segments,
                cost_snapshots=stress_cost_snapshots(cost_snapshots, scenario),
                execution_constraints=execution_constraints,
                require_offset_fees=True,
            ),
        )
        for scenario in CostStressScenario
    )
    return JMPilotResearchResult(
        source.input_sha256, source.actual_through,
        selection_overlap=True,
        retrospective_execution_facts=True,
        full_sample=full,
        walk_forward_by_scenario=scenarios,
    )
