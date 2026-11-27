"""Map verified Market facts to the V2 completed-input contract."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from itertools import groupby
from typing import TYPE_CHECKING

from guiyi_quant.newow.decision_adapter import (
    DECISION_FREQUENCIES,
    CompletedInput,
    CompletedMarketPayload,
    Decision,
    DecisionState,
    ExecutionContext,
    MarketSource,
    step_completed,
)
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import DataInterruption, ProductBar, ProductFrequency
from guiyi_quant.newow.product_identity import (
    InputQualityPolicy,
    build_calculation_segment_id,
    build_segment_id,
)

from app.market_data.aggregation import (
    SessionWindow,
    aggregate_from_1m,
    bucket_window_for_bar,
    expected_intraday_ends,
)
from app.market_data.domain import (
    INTRADAY_DERIVED_FREQUENCIES,
    BarFrequency,
    CanonicalBar,
    normalize_contract_for_symbol,
)
from app.market_data.live_market import LiveBarObservation, _bar_observation_from_payload, live_bar_channel
from app.market_data.observation_stream import ObservationEnvelope

if TYPE_CHECKING:
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.newow.product_reader import NewowProductReader, ProductReadSet


def _require_aware(*values: datetime) -> None:
    if any(value.tzinfo is None or value.utcoffset() is None for value in values):
        raise ValueError("V2_MARKET_TIMEZONE_REQUIRED")


@dataclass(frozen=True, slots=True)
class MarketWindow:
    """Session proof for one physical contract and trading day; reusable across bars."""

    product: str
    contract: str
    owner_segment_id: str
    owner_ref: str
    trading_day: date
    frequency: BarFrequency
    sessions: tuple[SessionWindow, ...]
    completed_week: tuple[date, datetime] | None = None
    warmup_only: bool = False
    endpoints: tuple[datetime, ...] = field(init=False)

    def __post_init__(self) -> None:
        frequency = BarFrequency(self.frequency)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "sessions", tuple(self.sessions))
        if frequency.value not in DECISION_FREQUENCIES:
            raise ValueError("V2_MARKET_FREQUENCY_INVALID")
        if normalize_contract_for_symbol(self.product, self.contract) != self.contract:
            raise ValueError("V2_MARKET_OWNER_CONFLICT")
        if not self.owner_segment_id or not self.owner_ref:
            raise ValueError("V2_MARKET_OWNER_PROOF_REQUIRED")
        if frequency in INTRADAY_DERIVED_FREQUENCIES:
            endpoints = expected_intraday_ends(self.sessions, frequency)
        else:
            if not self.sessions or any(a.end > b.start for a, b in zip(self.sessions, self.sessions[1:])):
                raise ValueError("V2_MARKET_SESSION_INVALID")
            end = self.sessions[-1].end
            endpoints = (end,) if frequency is BarFrequency.D1 else ()
            if frequency is BarFrequency.W1 and self.completed_week is not None:
                day, cutoff = self.completed_week
                _require_aware(cutoff)
                if day == self.trading_day and cutoff > end:
                    endpoints = (end,)
        object.__setattr__(self, "endpoints", endpoints)

    @classmethod
    def from_mds(
        cls, mds: MarketDataService, *, product: str, contract: str,
        owner_segment_id: str, owner_ref: str, trading_day: date, frequency: BarFrequency,
        as_of: datetime, warmup: bool = False,
    ) -> MarketWindow:
        """Bind externally captured owner evidence to current MDS authority."""
        _require_aware(as_of)
        if not warmup:
            owner = mds.dominant_segment_for_day(product, trading_day)
            if owner.contract != contract:
                raise ValueError("V2_MARKET_OWNER_CONFLICT")
            owner_start = mds.session_windows(symbol=product, trading_day=owner.start_trading_day)[0].start
            if owner_segment_id != build_segment_id(product, contract, owner_start):
                raise ValueError("V2_MARKET_OWNER_CONFLICT")
        sessions = mds.session_windows(symbol=product, trading_day=trading_day)
        completed_week = None
        if frequency == BarFrequency.W1:
            completed_week = mds.completed_calendar_week(
                symbol=product, week_monday=trading_day - timedelta(days=trading_day.weekday()),
                as_of=as_of,
            )
        return cls(
            product, contract, owner_segment_id, owner_ref, trading_day, frequency,
            sessions, completed_week, warmup_only=warmup,
        )

    def next_after(self, through: datetime) -> datetime | None:
        """Return the next authoritative endpoint covered by this window."""
        _require_aware(through)
        return next((end for end in self.endpoints if end > through), None)

    def session_for(self, end: datetime) -> SessionWindow:
        _require_aware(end)
        if end not in self.endpoints:
            raise ValueError("V2_MARKET_ENDPOINT_INVALID")
        return next(session for session in self.sessions if session.start < end <= session.end)


@dataclass(frozen=True, slots=True)
class HistoricalAvailability:
    available_at: datetime
    policy: str
    confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.available_at)
        if not self.policy:
            raise ValueError("V2_MARKET_AVAILABILITY_POLICY_REQUIRED")
        if self.confirmed_at is not None:
            _require_aware(self.confirmed_at)


def _check_availability(
    window: MarketWindow, end: datetime, available_at: datetime, as_of: datetime,
) -> SessionWindow:
    _require_aware(end, available_at, as_of)
    session = window.session_for(end)
    completion = end
    if window.frequency is BarFrequency.W1:
        assert window.completed_week is not None
        completion = window.completed_week[1]
    if not completion <= available_at <= as_of:
        raise ValueError("V2_MARKET_INPUT_NOT_AVAILABLE")
    return session


def completed_bucket(
    minutes: tuple[LiveBarObservation, ...], window: MarketWindow, *, through: datetime,
) -> CanonicalBar:
    """Derive only the requested bucket of already-confirmed physical 1m facts."""
    session = window.session_for(through)
    bucket = bucket_window_for_bar(session, window.frequency, through)
    if any(item.contract != window.contract for item in minutes):
        raise ValueError("V2_MARKET_OWNER_CONFLICT")
    bars = tuple(item.bar for item in minutes)
    if any(bar.trading_day != window.trading_day for bar in bars):
        raise ValueError("V2_MARKET_TRADING_DAY_CONFLICT")
    return aggregate_from_1m(bars, target_frequency=window.frequency, sessions=(bucket,))[0]


def _product_bar(
    bar: CanonicalBar, window: MarketWindow, *, source_ref: str, eligible: bool,
    quality_policy: InputQualityPolicy, last_gap_at: datetime | None,
) -> ProductBar:
    if bar.trading_day != window.trading_day:
        raise ValueError("V2_MARKET_TRADING_DAY_CONFLICT")
    if bar.is_strict_no_trade:
        raise ValueError("V2_MARKET_NO_TRADE")
    if bar.volume != int(bar.volume) or (
        bar.open_interest is not None and bar.open_interest != int(bar.open_interest)
    ):
        raise ValueError("V2_MARKET_VOLUME_OR_OI_INVALID")
    product_bar = NewowDailyBar(
        window.product, window.contract, window.owner_segment_id,
        bar.trading_day, bar.bar_end, bar.open, bar.high, bar.low, bar.close,
        int(bar.volume), None if bar.open_interest is None else int(bar.open_interest),
        source_ref, eligible, True,
    )
    return ProductBar(
        product_bar, window.frequency.value,
        calculation_segment_id=build_calculation_segment_id(
            window.owner_segment_id, last_gap_at, quality_policy,
        ),
    )


def from_historical_bar(
    bar: CanonicalBar, window: MarketWindow, *, revision: str, source_ref: str,
    availability: HistoricalAvailability, as_of: datetime, warmup: bool = False,
    quality_policy: InputQualityPolicy = InputQualityPolicy.V1,
    last_gap_at: datetime | None = None, verified_lifecycle: bool = False,
) -> CompletedInput:
    session = _check_availability(window, bar.bar_end, availability.available_at, as_of)
    return CompletedMarketPayload(
        _product_bar(bar, window, source_ref=source_ref, eligible=not (warmup or window.warmup_only),
                     quality_policy=quality_policy, last_gap_at=last_gap_at),
        MarketSource.CANONICAL, revision, source_ref, window.owner_ref,
        (session.start, session.end), availability.available_at, availability.policy,
        quality_policy, confirmed_at=availability.confirmed_at, turnover=bar.turnover,
        verified_lifecycle=verified_lifecycle,
    ).completed_input()


def from_observation(
    envelope: ObservationEnvelope, window: MarketWindow, *, generation: str, as_of: datetime,
    verified_lifecycle: bool = False,
) -> CompletedInput:
    """Consume the completed journal original for the configured live generation."""
    if (
        window.warmup_only or not envelope.stream_id or envelope.confirmed_at is None
        or envelope.trading_day != window.trading_day
        or envelope.channel != live_bar_channel(window.product, window.frequency)
        or window.frequency not in INTRADAY_DERIVED_FREQUENCIES
    ):
        raise ValueError("V2_MARKET_OBSERVATION_INVALID")
    observed = envelope.raw_received_at or envelope.source_observed_at
    if envelope.source_observed_at > envelope.confirmed_at or observed > envelope.confirmed_at:
        raise ValueError("V2_MARKET_OBSERVATION_INVALID")
    item = _bar_observation_from_payload(
        json.dumps(envelope.data), symbol=window.product, expected_contract=window.contract,
    )
    bar = item.bar
    identity = f"{bar.trading_day}:{item.contract}:{window.frequency.value}:{bar.bar_end.isoformat()}"
    if envelope.observation_id != identity:
        raise ValueError("V2_MARKET_OBSERVATION_INVALID")
    session = _check_availability(window, bar.bar_end, envelope.confirmed_at, as_of)
    return CompletedMarketPayload(
        _product_bar(bar, window, source_ref=identity, eligible=envelope.notification_eligible,
                     quality_policy=InputQualityPolicy.V1, last_gap_at=None),
        MarketSource.OBSERVATION, generation, identity, window.owner_ref,
        (session.start, session.end), envelope.confirmed_at, "completed-journal-v1",
        confirmed_at=envelope.confirmed_at, observed_at=observed, turnover=bar.turnover,
        verified_lifecycle=verified_lifecycle,
    ).completed_input()


@dataclass(frozen=True, slots=True)
class PublishedObservation:
    reference: str
    bar_sha256: str
    first_observed_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.first_observed_at)
        if not self.reference or len(self.bar_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.bar_sha256
        ):
            raise ValueError("V2_MARKET_PUBLICATION_INVALID")


def read_next_published_input(
    reader: NewowProductReader, window: MarketWindow, *, after: datetime, as_of: datetime,
    generation: str, publication: PublishedObservation, prior_owner_segment_id: str,
    prior_calculation_segment_id: str, verified_lifecycle: bool = False,
) -> CompletedInput | None:
    """Bind a D1/W1 observation to the first publication receipt and bar digest."""
    _require_aware(after, as_of)
    observed = publication.first_observed_at
    if window.warmup_only or window.frequency not in (BarFrequency.D1, BarFrequency.W1):
        raise ValueError("V2_MARKET_PUBLICATION_INVALID")
    if not after < observed <= as_of:
        raise ValueError("V2_MARKET_PUBLICATION_INVALID")
    result = reader.forward_incremental_bar(
        product=window.product, frequency=ProductFrequency(window.frequency.value),
        after=after, as_of=observed, prior_owner_segment_id=prior_owner_segment_id,
        prior_calculation_segment_id=prior_calculation_segment_id,
    )
    if result is None:
        return None
    bar, quality_policy = result
    _validate_window(bar, window)
    raw = bar.bar
    if not raw.observation_eligible or raw.bar_end <= after:
        raise ValueError("V2_MARKET_PUBLICATION_INVALID")
    if bar.source_bar_sha256 != publication.bar_sha256:
        raise ValueError("V2_MARKET_PUBLICATION_CONFLICT")
    session = _check_availability(window, raw.bar_end, observed, as_of)
    return CompletedMarketPayload(
        bar, MarketSource.OBSERVATION, generation, publication.reference, window.owner_ref,
        (session.start, session.end), observed, "canonical-publication-observed-v1", quality_policy,
        confirmed_at=observed, observed_at=observed, verified_lifecycle=verified_lifecycle,
    ).completed_input()


@dataclass(frozen=True, slots=True)
class CompletedStream:
    scope: tuple[MarketSource, str, str, str] | None = None
    through: datetime | None = None
    fingerprint: str | None = None
    contract: str | None = None
    blocked: bool = False
    available_through: datetime | None = None


class Admission(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    UNVERIFIED_REPLAY = "UNVERIFIED_REPLAY"
    GAP = "GAP"
    LATE = "LATE"
    BLOCKED = "BLOCKED"


def admit(
    state: CompletedStream, item: CompletedInput, *, expected: datetime, fresh: bool | None = None,
    previous_fingerprint: str | None = None,
) -> tuple[CompletedStream, Admission]:
    """Return the proposed watermark. Commit it with the decision in the caller.

    The previous fingerprint is an optional lookup from the existing journal
    for older physical input identities. Rewarm separately with a new, proved
    contiguous prefix before resuming a blocked stream.
    """
    _require_aware(expected)
    if fresh is not None and type(fresh) is not bool:
        raise ValueError("V2_MARKET_FRESHNESS_INVALID")
    if item != item.payload.completed_input():
        raise ValueError("V2_MARKET_INPUT_INVALID")
    if state.blocked:
        return state, Admission.BLOCKED
    payload = item.payload
    scope = (payload.source, payload.revision, payload.bar.bar.product, payload.bar.frequency.value)
    if state.scope is not None and state.scope != scope:
        return replace(state, blocked=True), Admission.SOURCE_CONFLICT
    if state.through is not None and item.bar_end <= state.through:
        known = previous_fingerprint
        if item.bar_end == state.through:
            if item.physical_contract != state.contract:
                return replace(state, blocked=True), Admission.CONFLICT
            known = state.fingerprint
        if known is not None:
            if item.fingerprint == known:
                return state, Admission.DUPLICATE
            return replace(state, blocked=True), Admission.CONFLICT
        return replace(state, blocked=True), Admission.UNVERIFIED_REPLAY
    if item.bar_end > expected:
        return replace(state, blocked=True), Admission.GAP
    if item.bar_end < expected:
        return state, Admission.LATE
    if payload.source is MarketSource.OBSERVATION and fresh is None:
        raise ValueError("V2_MARKET_FRESHNESS_REQUIRED")
    if fresh is False or (
        state.available_through is not None and payload.available_at < state.available_through
    ):
        return replace(state, blocked=True), Admission.LATE
    if payload.source is MarketSource.OBSERVATION and not payload.bar.bar.observation_eligible:
        return replace(state, blocked=True), Admission.LATE
    return CompletedStream(
        scope, item.bar_end, item.fingerprint, item.physical_contract,
        available_through=payload.available_at,
    ), Admission.ACCEPTED


def consume_completed(
    market_state: CompletedStream, strategy_state: DecisionState, item: CompletedInput,
    context: ExecutionContext, *, expected: datetime, fresh: bool | None = None,
    previous_fingerprint: str | None = None,
) -> tuple[CompletedStream, DecisionState, Admission, tuple[Decision, ...]]:
    """Propose a paired watermark and decision; the caller commits both together.

    At forward activation, begin a new observation watermark and retain the
    same-owner Core checkpoint from the canonical warm-up.
    """
    prior = strategy_state.strategy_state
    warmup_handoff = (
        market_state.through is None and strategy_state.computed_through is not None
        and prior.source is not None and prior.source[0] is MarketSource.CANONICAL
        and not prior.eligible_started and item.payload.source is MarketSource.OBSERVATION
    )
    if not warmup_handoff and (
        market_state.through != strategy_state.computed_through
        or market_state.fingerprint != strategy_state.last_fingerprint
        or market_state.contract != strategy_state.physical_contract
        or market_state.available_through != prior.available_through
    ):
        raise ValueError("V2_MARKET_DECISION_CHECKPOINT_CONFLICT")
    proposed, outcome = admit(
        market_state, item, expected=expected, fresh=fresh, previous_fingerprint=previous_fingerprint,
    )
    if outcome is not Admission.ACCEPTED:
        return proposed, strategy_state, outcome, ()
    next_state, decisions = step_completed(strategy_state, item, context)
    expected_last = (item.bar_end, item.fingerprint, item.physical_contract)
    if (next_state.computed_through, next_state.last_fingerprint, next_state.physical_contract) != expected_last:
        raise ValueError("V2_MARKET_DECISION_CHECKPOINT_CONFLICT")
    return proposed, next_state, outcome, decisions


def _validate_window(bar: ProductBar, window: MarketWindow) -> None:
    raw = bar.bar
    if (window.warmup_only and raw.observation_eligible) or (
        window.product, window.contract, window.owner_segment_id, window.trading_day, window.frequency.value
    ) != (raw.product, raw.physical_contract, raw.segment_id, raw.trading_day, bar.frequency.value):
        raise ValueError("V2_MARKET_OWNER_CONFLICT")


def iter_historical_inputs(
    read: ProductReadSet, *, revision: str, as_of: datetime,
    window_for: Callable[[ProductBar], MarketWindow],
    availability_for: Callable[[ProductBar], HistoricalAvailability],
    verified_prefix_for: Callable[[ProductBar], bool] | None = None,
) -> Iterator[CompletedInput | DataInterruption]:
    """Stream the already verified MDS-backed Newow read set and its quality breaks.

    The caller keeps the read set open and supplies frozen session and
    availability evidence. A quality break is a boundary, never a price.
    Lifecycle proof must cover only the state known at the input, rather than
    depend on a later gap or proof on the complete read set.
    """
    _require_aware(as_of)
    if read.as_of > as_of:
        raise ValueError("V2_MARKET_READ_CUTOFF_CONFLICT")
    quality_policy = read.input_quality_policies_by_frequency.get(read.frequency, read.input_quality_policy)
    by_owner: dict[tuple[str, str], list[DataInterruption]] = {}
    for gap in read.data_interruptions:
        by_owner.setdefault((gap.physical_contract, gap.segment_id), []).append(gap)
    remaining = {owner: iter(gaps) for owner, gaps in by_owner.items()}
    pending = {owner: next(gaps, None) for owner, gaps in remaining.items()}
    last_owner = None
    last_gap_at = None
    last_window_key = None
    for bar in read.replay_bars:
        raw = bar.bar
        owner = (raw.physical_contract, raw.segment_id)
        if owner != last_owner:
            if last_owner is not None:
                gap = pending.pop(last_owner, None)
                if gap is not None:
                    yield gap
                    yield from remaining[last_owner]
            last_owner = owner
            last_gap_at = None
        window_key = (owner, raw.trading_day, bar.frequency)
        if window_key != last_window_key:
            window = window_for(bar)
            _validate_window(bar, window)
            last_window_key = window_key
        gap = pending.get(owner)
        while gap is not None and gap.effective_at <= raw.bar_end:
            yield gap
            last_gap_at = gap.effective_at
            gap = next(remaining[owner], None)
        if owner in pending:
            pending[owner] = gap
        availability = availability_for(bar)
        session = _check_availability(window, raw.bar_end, availability.available_at, as_of)
        source_ref = bar.source_bar_sha256 or raw.source_identity
        bar = replace(bar, calculation_segment_id=build_calculation_segment_id(
            raw.segment_id, last_gap_at, quality_policy,
        ))
        yield CompletedMarketPayload(
            bar, MarketSource.CANONICAL, revision, source_ref, window.owner_ref,
            (session.start, session.end), availability.available_at, availability.policy,
            quality_policy, confirmed_at=availability.confirmed_at,
            verified_lifecycle=verified_prefix_for(bar) if verified_prefix_for else False,
        ).completed_input()

    for owner, gap in pending.items():
        if gap is not None:
            yield gap
            yield from remaining[owner]


def iter_historical_segments(
    inputs: Iterable[CompletedInput | DataInterruption],
) -> Iterator[tuple[tuple[str, str], Iterator[CompletedInput | DataInterruption]]]:
    """Consume one physical-owner stream before the next, using a fresh Core seed.

    MDS may supply new-owner prewarm that starts before the previous owner
    ended. Historical hosts preserve their old-account obligations separately.
    """
    def owner(item: CompletedInput | DataInterruption) -> tuple[str, str]:
        if isinstance(item, DataInterruption):
            return item.physical_contract, item.segment_id
        return item.physical_contract, item.owner_segment_id

    yield from groupby(inputs, key=owner)


def next_executable_minute(
    available_at: datetime, legal_minute_opens: Iterable[datetime],
) -> datetime | None:
    """Earliest supplied legal opening instant strictly after signal availability."""
    _require_aware(available_at)
    candidate = None
    for opening in legal_minute_opens:
        _require_aware(opening)
        if opening > available_at and (candidate is None or opening < candidate):
            candidate = opening
    return candidate
