"""Engine-independent decisions over one admitted, completed Newow bar."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from ..reference_trading.adapters import (
    AdapterCheckpoint,
    CompletedStrategyInput,
    strategy_input_fingerprint,
)
from .fusion_reference import select_fusion_actions
from .product_adapters import ProductReplayState, build_product_identity, replay_step, seed_replay_state
from .product_contracts import (
    ActionKind,
    FeatureRuntimeStatus,
    MainState,
    ProductBar,
    ProductFrequency,
    ProductStrategy,
    StrategyAction,
    StrategyFrame,
    TradeEligibility,
)
from .product_identity import InputQualityPolicy, input_quality_policy


DECISION_VERSION = "newow_v2_completed_decision_v1"
DECISION_FREQUENCIES = frozenset(ProductFrequency) - {ProductFrequency.MINUTE}


class V2Strategy(StrEnum):
    TREND = "trend"
    OSCILLATION = "oscillation"
    DUAL_FUSION = "dual_fusion"


class MarketSource(StrEnum):
    CANONICAL = "canonical"
    OBSERVATION = "observation"
    RQALPHA_PLUS = "rqalpha_plus_local_bundle"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("V2_DECISION_TIMEZONE_REQUIRED")
    return value.astimezone(UTC)


def _decimal_fact(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True, slots=True)
class CompletedMarketPayload:
    bar: ProductBar
    source: MarketSource
    revision: str
    source_ref: str
    owner_ref: str
    session: tuple[datetime, datetime]
    available_at: datetime
    availability_policy: str
    quality_policy: InputQualityPolicy = InputQualityPolicy.V1
    confirmed_at: datetime | None = None
    observed_at: datetime | None = None
    turnover: Decimal | None = None
    verified_lifecycle: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", MarketSource(self.source))
        object.__setattr__(self, "quality_policy", input_quality_policy(
            self.bar.frequency.value, self.quality_policy,
        ))
        start, end = map(_utc, self.session)
        available = _utc(self.available_at)
        if (
            self.bar.frequency not in DECISION_FREQUENCIES
            or (self.bar.series_kind == "physical_futures") != (self.source is MarketSource.RQALPHA_PLUS)
            or not all((self.revision, self.source_ref, self.owner_ref, self.availability_policy))
            or not start < self.bar.bar.bar_end <= end
            or self.bar.bar.bar_end > available
            or type(self.verified_lifecycle) is not bool
        ):
            raise ValueError("V2_DECISION_COMPLETED_INPUT_INVALID")
        for timestamp in (self.confirmed_at, self.observed_at):
            if timestamp is not None and _utc(timestamp) > available:
                raise ValueError("V2_DECISION_AVAILABILITY_INVALID")
        if self.confirmed_at is not None and self.confirmed_at < self.bar.bar.bar_end:
            raise ValueError("V2_DECISION_AVAILABILITY_INVALID")
        if self.source is MarketSource.OBSERVATION and (
            self.confirmed_at is None or self.observed_at is None
            or self.confirmed_at < self.bar.bar.bar_end
            or self.observed_at > self.confirmed_at
        ):
            raise ValueError("V2_DECISION_OBSERVATION_UNCONFIRMED")

    def market_key(self) -> str:
        raw = self.bar.bar
        return strategy_input_fingerprint({
            "source": self.source, "revision": self.revision,
            "product": raw.product, "contract": raw.physical_contract,
            "frequency": self.bar.frequency, "bar_end": _utc(raw.bar_end),
        })

    def completed_input(self) -> CompletedInput:
        wrapped = self.bar
        bar = wrapped.bar
        digest = strategy_input_fingerprint({
            "product": bar.product,
            "contract": bar.physical_contract,
            "frequency": wrapped.frequency,
            "trading_day": bar.trading_day,
            "bar_end": _utc(bar.bar_end),
            "owner_segment": bar.segment_id,
            "calculation_segment": wrapped.calculation_segment_id,
            "source": self.source,
            "revision": self.revision,
            "source_ref": self.source_ref,
            "bar_source": bar.source_identity,
            "bar_source_hash": wrapped.source_bar_sha256,
            "owner_ref": self.owner_ref,
            "session": tuple(map(_utc, self.session)),
            "available_at": _utc(self.available_at),
            "confirmed_at": _utc(self.confirmed_at) if self.confirmed_at else None,
            "observed_at": _utc(self.observed_at) if self.observed_at else None,
            "availability_policy": self.availability_policy,
            "quality_policy": self.quality_policy,
            "ohlc": tuple(_decimal_fact(value) for value in (bar.open, bar.high, bar.low, bar.close)),
            "volume": bar.volume,
            "open_interest": bar.open_interest,
            "turnover": _decimal_fact(self.turnover),
            "observation_eligible": bar.observation_eligible,
            "verified_lifecycle": self.verified_lifecycle,
        })
        assert wrapped.calculation_segment_id is not None
        return CompletedStrategyInput(
            self, _utc(bar.bar_end), bar.trading_day, bar.physical_contract, bar.segment_id,
            wrapped.calculation_segment_id, digest,
        )


CompletedInput = CompletedStrategyInput[CompletedMarketPayload]


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Position is long quantity on the input contract; None means unverified."""

    scope_id: str
    config_revision: str
    strategies: tuple[V2Strategy, ...]
    execution_strategy: V2Strategy | None = None
    account_as_of: datetime | None = None
    account_ref: str | None = None
    fill_prefix_ref: str | None = None
    position: Decimal | None = None
    position_contract: str | None = None
    unsettled_contracts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        strategies = tuple(V2Strategy(strategy) for strategy in self.strategies)
        if (
            not self.scope_id or not self.config_revision
            or not strategies or len(strategies) != len(set(strategies))
        ):
            raise ValueError("V2_DECISION_CONFIGURATION_INVALID")
        selected = tuple(strategy for strategy in V2Strategy if strategy in strategies)
        object.__setattr__(self, "strategies", selected)
        if self.execution_strategy is not None:
            execution_strategy = V2Strategy(self.execution_strategy)
            if execution_strategy not in selected:
                raise ValueError("V2_DECISION_EXECUTION_STRATEGY_INVALID")
            object.__setattr__(self, "execution_strategy", execution_strategy)
        if self.position is not None and (
            not isinstance(self.position, Decimal) or not self.position.is_finite()
            or self.position < 0 or not self.account_ref or not self.fill_prefix_ref
            or self.account_as_of is None or not self.position_contract
        ):
            raise ValueError("V2_DECISION_ACCOUNT_PREFIX_INVALID")
        if self.account_as_of is not None:
            _utc(self.account_as_of)
        object.__setattr__(self, "unsettled_contracts", tuple(sorted(set(self.unsettled_contracts))))


@dataclass(frozen=True, slots=True)
class Decision:
    decision_id: str
    scope_id: str
    config_revision: str
    strategy: V2Strategy
    product: str
    frequency: ProductFrequency
    physical_contract: str
    trading_day: date
    owner_segment_id: str
    calculation_segment_id: str
    bar_end: datetime
    decision_at: datetime
    input_key: str
    input_ref: str
    previous_state_ref: str
    state_ref: str
    execution_context_ref: str
    unsettled_contracts: tuple[str, ...]
    formula_versions: tuple[str, ...]
    profiles: tuple[str, ...]
    state: MainState
    main_action: ActionKind | None
    reason: str
    execution_candidate: bool
    source_actions: tuple[StrategyAction, ...]
    hint_refs: tuple[str, ...]
    version: str = DECISION_VERSION


@dataclass(frozen=True, slots=True)
class _DecisionState:
    binding: tuple[object, ...] = ()
    reference: str = "initial"
    trend: ProductReplayState = field(default_factory=seed_replay_state)
    oscillation: ProductReplayState = field(default_factory=seed_replay_state)
    fusion_long: bool = False
    eligible_started: bool = False
    source: tuple[MarketSource, str] | None = None
    available_through: datetime | None = None


DecisionState = AdapterCheckpoint[_DecisionState]


def seed_decision_state() -> DecisionState:
    return AdapterCheckpoint(_DecisionState())


def _standalone(frame: StrategyFrame) -> tuple[MainState, ActionKind | None, str, tuple[StrategyAction, ...]]:
    if not frame.bar.bar.observation_eligible:
        return frame.main_state, None, "WARMUP_ONLY", ()
    if frame.availability.status is not FeatureRuntimeStatus.READY:
        return frame.main_state, None, frame.availability.reason_code or "FORMULA_UNAVAILABLE", ()
    if frame.actions:
        last = frame.actions[-1]
        reason = last.kind.value if last.trade_eligibility is TradeEligibility.ELIGIBLE else last.trade_eligibility.value
        return frame.main_state, last.kind, reason, frame.actions
    return frame.main_state, None, frame.main_state.value, ()


def _execution_reason(
    action: ActionKind | None,
    reason: str,
    context: ExecutionContext,
    contract: str,
    strategy: V2Strategy,
) -> tuple[bool, str]:
    if action is None or reason != action.value:
        return False, reason
    if context.execution_strategy is not strategy:
        return False, "OBSERVATION_ONLY"
    if context.position is None:
        return False, "ACCOUNT_PREFIX_UNVERIFIED"
    if context.position_contract != contract:
        return False, "ACCOUNT_CONTRACT_MISMATCH"
    if action is ActionKind.CLEAR:
        return (True, reason) if context.position > 0 else (False, "NO_CONFIRMED_POSITION")
    if any(other != contract for other in context.unsettled_contracts):
        return False, "ROLLOVER_INTERRUPTED"
    if contract in context.unsettled_contracts:
        return False, "UNSETTLED_EXECUTION"
    return (True, reason) if context.position == 0 else (False, "POSITION_ALREADY_LONG")


def _fusion(
    trend: StrategyFrame,
    oscillation: StrategyFrame,
    holding: bool,
    *,
    verified_lifecycle: bool,
) -> tuple[bool, MainState, ActionKind | None, str, tuple[StrategyAction, ...]]:
    if not trend.bar.bar.observation_eligible:
        return holding, MainState.FLAT, None, "WARMUP_ONLY", ()
    candidates = tuple(
        action for frame in (oscillation, trend)
        if frame.availability.status is FeatureRuntimeStatus.READY
        for action in frame.actions
        if action.trade_eligibility is not TradeEligibility.WARMUP_ONLY
        and (verified_lifecycle or action.trade_eligibility is not TradeEligibility.INITIAL_CLEAR_NO_ENTRY)
    )
    selected = select_fusion_actions(candidates, holding=holding)
    after = selected[-1].kind is ActionKind.BUILD if selected else holding
    if holding == after:
        state = MainState.HOLD if after else MainState.FLAT
        return after, state, None, state.value, selected
    action = ActionKind.BUILD if after else ActionKind.CLEAR
    return after, MainState(action.value), action, action.value, selected


def step_completed(
    state: DecisionState, input: CompletedInput, execution_context: ExecutionContext,
) -> tuple[DecisionState, tuple[Decision, ...]]:
    """Advance once, sharing the two underlying formula steps with fusion."""

    payload = input.payload
    if input != payload.completed_input():
        raise ValueError("V2_DECISION_INPUT_INVALID")
    context = execution_context
    if context.account_as_of is not None and context.account_as_of > payload.available_at:
        raise ValueError("V2_DECISION_ACCOUNT_PREFIX_IN_FUTURE")
    bar = payload.bar
    binding = (
        context.scope_id, context.config_revision, context.strategies,
        context.execution_strategy, bar.bar.product, bar.frequency, payload.quality_policy,
    )
    prior = state.strategy_state
    if prior.binding and prior.binding != binding:
        raise ValueError("V2_DECISION_CONFIGURATION_CONFLICT")
    if state.computed_through is not None:
        if input.bar_end < state.computed_through:
            raise ValueError("V2_DECISION_OUT_OF_ORDER")
        if input.bar_end == state.computed_through:
            if input.fingerprint == state.last_fingerprint:
                return state, ()
            raise ValueError("V2_DECISION_INPUT_CONFLICT")
    if prior.available_through is not None and payload.available_at < prior.available_through:
        raise ValueError("V2_DECISION_AVAILABILITY_OUT_OF_ORDER")
    rolled = state.physical_contract is not None and (
        state.physical_contract, state.owner_segment_id, state.calculation_segment_id
    ) != (input.physical_contract, input.owner_segment_id, input.calculation_segment_id)
    source = (payload.source, payload.revision)
    warmup_handoff = (
        prior.source is not None and prior.source[0] is MarketSource.CANONICAL
        and payload.source is MarketSource.OBSERVATION and not prior.eligible_started and not rolled
    )
    if prior.source is not None and source != prior.source and not warmup_handoff:
        raise ValueError("V2_DECISION_SOURCE_CONFLICT")
    working = _DecisionState() if rolled else prior
    if working.eligible_started and not bar.bar.observation_eligible:
        raise ValueError("V2_DECISION_WARMUP_AFTER_ACTIVATION")

    frames = {}
    substates = {}
    identities = {}
    for strategy, kernel_state in (
        (V2Strategy.TREND, working.trend), (V2Strategy.OSCILLATION, working.oscillation),
    ):
        if strategy not in context.strategies and V2Strategy.DUAL_FUSION not in context.strategies:
            continue
        identity = build_product_identity(
            bar.bar.product, ProductStrategy(strategy.value), bar.frequency,
            input_quality_policy=payload.quality_policy,
            series_kind=bar.series_kind,
        )
        next_kernel, frame, _ = replay_step(
            identity, kernel_state, bar, verified_lifecycle=payload.verified_lifecycle,
        )
        if frame is None:
            raise ValueError("V2_DECISION_CHECKPOINT_MISMATCH")
        identities[strategy], frames[strategy], substates[strategy] = identity, frame, next_kernel

    results = {strategy: _standalone(frame) for strategy, frame in frames.items()}
    fusion_long = working.fusion_long
    if V2Strategy.DUAL_FUSION in context.strategies:
        fusion_long, status, action, reason, actions = _fusion(
            frames[V2Strategy.TREND], frames[V2Strategy.OSCILLATION], fusion_long,
            verified_lifecycle=payload.verified_lifecycle,
        )
        results[V2Strategy.DUAL_FUSION] = (status, action, reason, actions)

    context_ref = strategy_input_fingerprint({
        "account": context.account_ref, "fills": context.fill_prefix_ref,
        "account_as_of": _utc(context.account_as_of) if context.account_as_of else None,
        "position": _decimal_fact(context.position), "position_contract": context.position_contract,
        "unsettled": context.unsettled_contracts,
    })
    state_ref = strategy_input_fingerprint({
        "version": DECISION_VERSION, "prior": prior.reference, "binding": binding,
        "input": input.fingerprint,
        "profiles": tuple(identity.profile_id for identity in identities.values()),
    })
    decisions = []
    input_key = payload.market_key()
    for strategy in context.strategies:
        status, action, reason, actions = results[strategy]
        eligible, reason = _execution_reason(action, reason, context, input.physical_contract, strategy)
        source_strategies = tuple(identities) if strategy is V2Strategy.DUAL_FUSION else (strategy,)
        sources = tuple(identities[source] for source in source_strategies)
        hints = tuple(hint.hint_id for source in source_strategies for hint in frames[source].hints)
        profiles = tuple(identity.profile_id for identity in sources)
        formulas = tuple(dict.fromkeys(v for identity in sources for v in identity.formula_versions))
        decision_id = strategy_input_fingerprint({
            "version": DECISION_VERSION, "scope": context.scope_id, "config": context.config_revision,
            "strategy": strategy, "input": input_key, "sequence": 0,
        })
        decisions.append(Decision(
            decision_id, context.scope_id, context.config_revision, strategy,
            bar.bar.product, bar.frequency, input.physical_contract, input.trading_day,
            input.owner_segment_id, input.calculation_segment_id, input.bar_end,
            _utc(payload.available_at), input_key, input.fingerprint, prior.reference, state_ref,
            context_ref, context.unsettled_contracts, formulas, profiles,
            status, action, reason, eligible, actions, hints,
        ))
    next_strategy = _DecisionState(
        binding, state_ref, substates.get(V2Strategy.TREND, working.trend),
        substates.get(V2Strategy.OSCILLATION, working.oscillation), fusion_long,
        working.eligible_started or bar.bar.observation_eligible, source, _utc(payload.available_at),
    )
    return AdapterCheckpoint(
        next_strategy, input.bar_end, input.fingerprint, input.physical_contract,
        input.owner_segment_id, input.calculation_segment_id,
    ), tuple(decisions)
