"""Read-only completed-prefix HTDY replay; never creates observed events."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from threading import Lock

from app.alerts.evaluators import HtdyOriginalEvaluator
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.market_read_service import MarketReadWindow
from guiyi_quant.reference_trading import (
    BoundaryReason, RecordingMode, ReferenceBoundary, ReferenceState, StreamIdentity,
    reduce_reference,
)
from guiyi_quant.reference_trading.htdy import (
    CONTEXT_BARS, HISTORICAL_MODEL_VERSION, project_historical_observation,
)


# Pure derived results only. Every caller still loads and verifies MDS content;
# elapsed time/TTL never proves source validity. Nothing here is authoritative.
_REPLAY_CACHE = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_KEYS = 4
_CACHE_POINTS = 40000


def _cached_replay(source, stream, loaded, check_cancelled):
    with _CACHE_LOCK:
        cached = _REPLAY_CACHE.get(source)
        if cached is not None:
            _REPLAY_CACHE.move_to_end(source)
            return deepcopy(cached)
    result = replay_htdy(stream, loaded, check_cancelled=check_cancelled)
    weight = len(result[0]) + len(result[1])
    if weight <= _CACHE_POINTS:
        with _CACHE_LOCK:
            _REPLAY_CACHE[source] = deepcopy(result)
            _REPLAY_CACHE.move_to_end(source)
            while (len(_REPLAY_CACHE) > _CACHE_KEYS or sum(
                len(value[0]) + len(value[1]) for value in _REPLAY_CACHE.values()
            ) > _CACHE_POINTS):
                _REPLAY_CACHE.popitem(last=False)
    return result


@dataclass(frozen=True)
class HtdyReplaySegment:
    contract: str
    owner_id: str
    calculation_id: str
    owner_since: date
    owner_through: date
    bars: tuple[CanonicalBar, ...]
    interrupted_at: datetime | None = None
    interruption_day: date | None = None
    interruption_reason: BoundaryReason = BoundaryReason.ROLLOVER


def replay_htdy(stream, segments, *, check_cancelled=lambda: None):
    """Replay each fixed-size prefix, independent of presentation date/window."""
    if (stream.recording_mode is not RecordingMode.HISTORICAL_REPLAY
            or stream.reference_model_version != HISTORICAL_MODEL_VERSION
            or stream.strategy_code != "htdy"):
        raise ValueError("HTDY_HISTORICAL_IDENTITY_INVALID")
    state = ReferenceState.flat(stream)
    trades, signals = {}, []
    evaluator = HtdyOriginalEvaluator()
    for segment in segments:
        for index, bar in enumerate(segment.bars):
            check_cancelled()
            if not segment.owner_since <= bar.trading_day <= segment.owner_through:
                continue
            window = segment.bars[max(0, index + 1 - CONTEXT_BARS):index + 1]
            if len(window) < CONTEXT_BARS:
                continue
            observed = evaluator.evaluate(MarketReadWindow(
                symbol=stream.product, series_kind="actual_dominant", frequency=stream.frequency,
                trading_day=bar.trading_day, contract=segment.contract, cutoff=bar.bar_end,
                bars=window, bar_contracts=(segment.contract,) * len(window),
            )).observation_types
            actions, transition = project_historical_observation(
                state, observations=observed, physical_contract=segment.contract,
                owner_segment_id=segment.owner_id, calculation_segment_id=segment.calculation_id,
                bar_end=bar.bar_end, trading_day=bar.trading_day, close=bar.close,
            )
            state = transition.state
            trades.update((trade.reference_trade_id, trade) for trade in transition.changed_trades)
            if observed:
                signals.append(dict(bar_end=bar.bar_end, trading_day=bar.trading_day,
                    physical_contract=segment.contract, segment_id=segment.owner_id,
                    calculation_segment_id=segment.calculation_id, observation_types=observed,
                    reference_price=bar.close, action_ids=[action.source_action_id for action in actions],
                    actions=[dict(action_id=action.source_action_id, kind=action.kind.value,
                                  entry_action_id=action.entry_action_id) for action in actions]))
        if segment.interrupted_at is not None:
            transition = reduce_reference(state, boundaries=(ReferenceBoundary(
                stream, segment.interruption_reason, segment.contract, segment.owner_id,
                segment.calculation_id, segment.interrupted_at,
                segment.interruption_day or segment.owner_through,
            ),))
            state = transition.state
            trades.update((trade.reference_trade_id, trade) for trade in transition.changed_trades)
    if state.open_trade is not None:
        trades[state.open_trade.reference_trade_id] = state.open_trade
    return tuple(trades.values()), tuple(signals), state


def history_identity(product, frequency):
    from guiyi_quant.indicators import get_indicator
    definition = get_indicator("huotian_dayou_original_v0")
    return StreamIdentity(
        strategy_code="htdy", formula_versions=(definition.indicator_version,),
        profile_id="htdy_historical_window32_v1", reference_model_version=HISTORICAL_MODEL_VERSION,
        futures_adaptation_version="htdy_physical_quality_prefix_v1", product=product.upper(),
        frequency=frequency, series_kind="actual_dominant",
        recording_mode=RecordingMode.HISTORICAL_REPLAY, observation_policy_version=None,
    )


def query_htdy_history(service, query):
    """MDS owns physical prefixes and quality boundaries; no DB mutation."""
    since, through, cutoff, as_of = service.resolve_read_window(query)
    storage_start = service.historical_storage_start(query.symbol)
    event_bound, _reference_event_bytes = service.historical_input_bound(
        symbol=query.symbol, frequency=query.frequency, since=storage_start,
        through=through, as_of=as_of)
    # The shared preflight estimates two durable reference events per endpoint,
    # at 4096 bytes each. This reader retains neither durable events nor per-Bar
    # checkpoints: it retains OHLCV prefixes and only signal/trade results.
    # ceil(events / 2) remains a conservative Bar bound (owner overhead included).
    bar_bound = (event_bound + 1) // 2
    if bar_bound > 100000 or bar_bound * 1024 > 128 * 1024 * 1024:
        from app.market_data.subing_reference import SubingReferenceError
        raise SubingReferenceError("HTDY_REFERENCE_BUDGET_EXCEEDED")
    before_source = service.historical_metadata_evidence(
        symbol=query.symbol, since=storage_start, through=through)
    segments, raw, quality, loaded_cutoff = service.load_historical_inputs(
        symbol=query.symbol, frequency=BarFrequency(query.frequency),
        since=storage_start, through=through, as_of=as_of)
    if loaded_cutoff != cutoff:
        raise ValueError("HTDY_SOURCE_CHANGED")
    canonical = {}
    if query.frequency == "1d":
        for segment in segments:
            if segment.physical_contract in canonical:
                continue
            bars, _ = service.market_data.query_contract_replay_quality_union(
                symbol=query.symbol, contract=segment.physical_contract,
                through=through, cutoff=cutoff)
            canonical[segment.physical_contract] = {bar.bar_end: bar for bar in bars}
    else:
        for item in raw:
            canonical[item["contract"]] = {
                datetime.fromisoformat(bar["bar_end"]) if isinstance(bar["bar_end"], str) else bar["bar_end"]:
                CanonicalBar(
                    bar_end=datetime.fromisoformat(bar["bar_end"]) if isinstance(bar["bar_end"], str) else bar["bar_end"],
                    trading_day=date.fromisoformat(bar["trading_day"]) if isinstance(bar["trading_day"], str) else bar["trading_day"],
                    **{key: None if bar[key] is None else Decimal(str(bar[key])) for key in ("open", "high", "low", "close", "volume", "turnover", "open_interest")})
                for bar in item["bars"]}
    loaded = []
    for segment in segments:
        bars = tuple(canonical[segment.physical_contract][bar.bar_end] for bar in segment.bars)
        loaded.append(HtdyReplaySegment(
            segment.physical_contract, segment.segment_id,
            segment.calculation_segment_id or segment.segment_id,
            segment.owner_since, segment.owner_through, bars,
            segment.quality_interrupted_at or segment.interrupted_at,
            segment.quality_interruption_trading_day,
            BoundaryReason.DATA_INTERRUPTED if segment.quality_interrupted_at else BoundaryReason.ROLLOVER))
    stream = history_identity(query.symbol, query.frequency)
    after_source = service.historical_metadata_evidence(
        symbol=query.symbol, since=storage_start, through=through)
    if before_source != after_source:
        raise ValueError("HTDY_SOURCE_CHANGED")
    source = sha256(json.dumps(dict(identity=asdict(stream), metadata=after_source,
        inputs=raw, segments=[asdict(item) for item in loaded], cutoff=cutoff), sort_keys=True, default=str).encode()).hexdigest()
    trades, signals, _ = _cached_replay(source, stream, loaded, service.check_cancelled)
    # Recheck after a cold calculation too; never publish a stale build as current.
    if after_source != service.historical_metadata_evidence(
            symbol=query.symbol, since=storage_start, through=through):
        raise ValueError("HTDY_SOURCE_CHANGED")
    service.check_cancelled()
    cursor_identity = sha256(f"{source}:{since}:{through}".encode()).hexdigest()
    selected = sorted((trade for trade in trades if since <= trade.entry_trading_day <= through),
                      key=lambda trade: (trade.entry_bar_end, trade.reference_trade_id), reverse=True)
    offset = 0
    if query.before:
        parts = query.before.split(":")
        if len(parts) != 2 or parts[0] != cursor_identity or not parts[1].isdigit():
            raise ValueError("HTDY_CURSOR_CONFLICT")
        offset = int(parts[1])
    page = selected[offset:offset + query.limit]
    closed = [trade for trade in selected if trade.status.value == "CLOSED"]
    return dict(schema_version="htdy_historical_reference_v1", product=query.symbol,
        frequency=query.frequency, recording_mode="historical_replay", source="canonical",
        reference_model_version=HISTORICAL_MODEL_VERSION, stream_id=stream.stream_id,
        formula_versions=stream.formula_versions, source_token=source,
        since=since, through=through, computed_through=cutoff,
        page_parity=True, executable=False, auto_order=False,
        trades=[asdict(trade) for trade in page],
        signals=[signal for signal in signals if since <= signal["trading_day"] <= through],
        summary=dict(total=len(selected), closed=len(closed),
                     open=sum(trade.status.value == "OPEN" for trade in selected)),
        next_cursor=f"{cursor_identity}:{offset + query.limit}" if offset + query.limit < len(selected) else None,
        quality=quality)
