"""Server-owned P3 input construction from validated product replays."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json

from guiyi_quant.newow.composite_explanation import (
    CompositeStatusFact,
    CompositeStatusState,
    VerifiedCompositeEvidence,
)
from guiyi_quant.newow.context_alignment import ContextSnapshot, align_completed_context
from guiyi_quant.newow.product_contracts import (
    MainState,
    ProductFrequency,
    StrategyFrame,
    StrategyReplay,
)
from guiyi_quant.newow.product_identity import utc_timestamp
from guiyi_quant.newow.target_absorb_display import PageSignalFact, PageSignalState


SOURCE_FACT_ADAPTER_VERSION = "guiyi_newow_server_source_facts_v1"


@dataclass(frozen=True, slots=True)
class SourceFact:
    role: str
    source_category: str
    adapter_version: str
    formula_versions: tuple[str, ...]
    frequency: ProductFrequency | None
    bar_end: datetime | None
    physical_contract: str | None
    segment_id: str | None
    as_of: datetime
    dependency_sha256: str | None
    status: str
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class CompositeInputs:
    context: ContextSnapshot
    evidence: VerifiedCompositeEvidence | None
    sources: tuple[SourceFact, ...]


_PAGE_SIGNAL = {
    MainState.BUILD: PageSignalState.BUY,
    MainState.HOLD: PageSignalState.HOLD,
    MainState.CLEAR: PageSignalState.SELL,
    MainState.FLAT: PageSignalState.WAIT,
}
_COMPOSITE_STATUS = {
    MainState.BUILD: CompositeStatusState.HOLDING,
    MainState.HOLD: CompositeStatusState.HOLDING,
    MainState.CLEAR: CompositeStatusState.CLEARED,
    MainState.FLAT: CompositeStatusState.IDLE,
}


def _last_frame(replay: StrategyReplay, as_of: datetime) -> StrategyFrame | None:
    eligible = tuple(
        frame
        for frame in replay.frames
        if frame.bar.bar.observation_eligible and frame.bar.bar.bar_end <= as_of
    )
    return eligible[-1] if eligible else None


def _dependency(frame: StrategyFrame, replay: StrategyReplay) -> str:
    owner = (frame.bar.bar.physical_contract, frame.bar.bar.segment_id)
    prefix = tuple(
        item
        for item in replay.frames
        if (item.bar.bar.physical_contract, item.bar.bar.segment_id) == owner
        and item.bar.bar.bar_end <= frame.bar.bar.bar_end
    )
    return _frames_dependency(replay, prefix)


def _frames_dependency(
    replay: StrategyReplay, frames: tuple[StrategyFrame, ...]
) -> str:
    payload = {
        "profile_id": replay.identity.profile_id,
        "formula_versions": replay.identity.formula_versions,
        "frames": [
            {
                "source_identity": item.bar.bar.source_identity,
                "physical_contract": item.bar.bar.physical_contract,
                "segment_id": item.bar.bar.segment_id,
                "trading_day": item.bar.bar.trading_day.isoformat(),
                "bar_end": item.bar.bar.bar_end.isoformat(),
                "ohlcv": (
                    str(item.bar.bar.open),
                    str(item.bar.bar.high),
                    str(item.bar.bar.low),
                    str(item.bar.bar.close),
                    item.bar.bar.volume,
                    item.bar.bar.open_interest,
                ),
                "main_state": item.main_state.value,
                "main_values": tuple(
                    (key, None if value is None else str(value))
                    for key, value in item.main_values
                ),
                "actions": tuple(action.signal_id for action in item.actions),
                "hints": tuple(hint.hint_id for hint in item.hints),
            }
            for item in frames
        ],
    }
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _source(
    role: str,
    replay: StrategyReplay,
    frame: StrategyFrame | None,
    as_of: datetime,
) -> SourceFact:
    if frame is None or frame.main_state is MainState.UNAVAILABLE:
        return SourceFact(
            role,
            "strategy_replay",
            SOURCE_FACT_ADAPTER_VERSION,
            replay.identity.formula_versions,
            replay.identity.frequency,
            None,
            None,
            None,
            as_of,
            None,
            "unavailable",
            "NEWOW_SOURCE_FACT_FRAME_UNAVAILABLE",
        )
    bar = frame.bar.bar
    return SourceFact(
        role,
        "strategy_replay",
        SOURCE_FACT_ADAPTER_VERSION,
        replay.identity.formula_versions,
        replay.identity.frequency,
        bar.bar_end,
        bar.physical_contract,
        bar.segment_id,
        as_of,
        _dependency(frame, replay),
        "ready",
    )


def _page_fact(frame: StrategyFrame, frequency: ProductFrequency) -> PageSignalFact:
    value = _PAGE_SIGNAL.get(frame.main_state)
    if value is None:
        raise ValueError("NEWOW_SOURCE_FACT_FRAME_UNAVAILABLE")
    bar = frame.bar.bar
    return PageSignalFact(
        value, frequency, bar.bar_end, bar.physical_contract, bar.segment_id
    )


def _status_fact(
    frame: StrategyFrame, frequency: ProductFrequency
) -> CompositeStatusFact:
    value = _COMPOSITE_STATUS.get(frame.main_state)
    if value is None:
        raise ValueError("NEWOW_SOURCE_FACT_FRAME_UNAVAILABLE")
    bar = frame.bar.bar
    return CompositeStatusFact(
        value, frequency, bar.bar_end, bar.physical_contract, bar.segment_id
    )


def build_composite_inputs(
    trend_replays: Mapping[ProductFrequency, StrategyReplay],
    oscillation_replays: Mapping[ProductFrequency, StrategyReplay],
    as_of: datetime,
) -> CompositeInputs:
    """Build the six current facts; missing facts degrade instead of being guessed."""

    cutoff = utc_timestamp(as_of)
    context_inputs: dict[ProductFrequency | str, StrategyReplay] = {
        frequency: replay for frequency, replay in trend_replays.items()
    }
    context = align_completed_context(context_inputs, cutoff)
    roles = (
        ("trend_weekly", trend_replays[ProductFrequency.WEEKLY]),
        ("trend_daily", trend_replays[ProductFrequency.DAILY]),
        ("trend_hourly", trend_replays[ProductFrequency.HOURLY]),
        ("oscillation_weekly", oscillation_replays[ProductFrequency.WEEKLY]),
        ("oscillation_daily", oscillation_replays[ProductFrequency.DAILY]),
        ("oscillation_hourly", oscillation_replays[ProductFrequency.HOURLY]),
    )
    frames = tuple(_last_frame(replay, cutoff) for _, replay in roles)
    sources = tuple(
        _source(role, replay, frame, cutoff)
        for (role, replay), frame in zip(roles, frames, strict=True)
    )
    if any(
        frame is None or frame.main_state is MainState.UNAVAILABLE for frame in frames
    ):
        return CompositeInputs(context, None, sources)
    weekly, daily, hourly, osc_weekly, osc_daily, osc_hourly = frames
    assert all(frame is not None for frame in frames)
    assert weekly is not None and daily is not None and hourly is not None
    assert osc_weekly is not None and osc_daily is not None and osc_hourly is not None
    daily_owner = daily.bar.bar.segment_id
    daily_prefix = tuple(
        frame
        for frame in trend_replays[ProductFrequency.DAILY].frames
        if frame.bar.bar.segment_id == daily_owner
        and frame.bar.bar.bar_end <= daily.bar.bar.bar_end
    )
    daily_prefix_bars = tuple(frame.bar for frame in daily_prefix)
    evidence = VerifiedCompositeEvidence(
        trend_weekly=_page_fact(weekly, ProductFrequency.WEEKLY),
        trend_daily=_page_fact(daily, ProductFrequency.DAILY),
        trend_hourly=_status_fact(hourly, ProductFrequency.HOURLY),
        oscillation_weekly=_status_fact(osc_weekly, ProductFrequency.WEEKLY),
        oscillation_daily=_status_fact(osc_daily, ProductFrequency.DAILY),
        oscillation_hourly=_status_fact(osc_hourly, ProductFrequency.HOURLY),
        daily_bars=daily_prefix_bars,
    )
    volatility_source = SourceFact(
        "volatility_daily_prefix",
        "canonical_bar_prefix",
        SOURCE_FACT_ADAPTER_VERSION,
        trend_replays[ProductFrequency.DAILY].identity.formula_versions,
        ProductFrequency.DAILY,
        daily.bar.bar.bar_end,
        daily.bar.bar.physical_contract,
        daily.bar.bar.segment_id,
        cutoff,
        _frames_dependency(trend_replays[ProductFrequency.DAILY], daily_prefix),
        "ready",
    )
    return CompositeInputs(context, evidence, (*sources, volatility_source))


def target_absorb_gap_sources(as_of: datetime) -> tuple[SourceFact, ...]:
    """Explicitly report unresolved page input roles; do not synthesize candidates."""

    cutoff = utc_timestamp(as_of)
    roles = (
        "cross_weekly_buy",
        "target_daily",
        "target_weekly",
        "target",
        "high",
        "cost_daily",
        "cost_weekly",
        "cost",
        "previous_close",
    )
    return tuple(
        SourceFact(
            role,
            "evidence_gap",
            SOURCE_FACT_ADAPTER_VERSION,
            (),
            None,
            None,
            None,
            None,
            cutoff,
            None,
            "evidence_required",
            f"NEWOW_{role.upper()}_EVIDENCE_REQUIRED",
        )
        for role in roles
    )


def target_absorb_available_sources(
    context: ContextSnapshot, view_frequency: ProductFrequency
) -> tuple[SourceFact, ...]:
    """Report current page inputs that are tied directly to server facts."""

    slots = {
        ProductFrequency.WEEKLY: context.weekly,
        ProductFrequency.DAILY: context.daily,
        ProductFrequency.HOURLY: context.hourly,
    }
    requested = (
        ("signal_daily", slots[ProductFrequency.DAILY], "strategy_replay"),
        ("signal_weekly", slots[ProductFrequency.WEEKLY], "strategy_replay"),
        (
            "current_price",
            slots[ProductFrequency(view_frequency)],
            "canonical_bar_close",
        ),
    )
    output: list[SourceFact] = []
    for role, slot, category in requested:
        if slot.frame is None or slot.identity is None:
            output.append(
                SourceFact(
                    role,
                    category,
                    SOURCE_FACT_ADAPTER_VERSION,
                    slot.formula_versions,
                    slot.frequency,
                    None,
                    None,
                    None,
                    context.as_of,
                    None,
                    "unavailable",
                    "NEWOW_SOURCE_FACT_FRAME_UNAVAILABLE",
                )
            )
            continue
        frame = slot.frame
        bar = frame.bar.bar
        payload = "|".join(
            (
                role,
                category,
                slot.identity.profile_id,
                *slot.formula_versions,
                bar.source_identity,
                bar.physical_contract,
                bar.segment_id,
                bar.bar_end.isoformat(),
                str(bar.close),
            )
        )
        output.append(
            SourceFact(
                role,
                category,
                SOURCE_FACT_ADAPTER_VERSION,
                slot.formula_versions,
                slot.frequency,
                bar.bar_end,
                bar.physical_contract,
                bar.segment_id,
                context.as_of,
                sha256(payload.encode()).hexdigest(),
                "ready",
            )
        )
    return tuple(output)
