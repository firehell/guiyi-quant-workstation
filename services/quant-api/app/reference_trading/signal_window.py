"""Bounded historical chart signals, separate from performance windows."""
from dataclasses import asdict, dataclass
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import os
from zoneinfo import ZoneInfo

from app.market_data.domain import BarFrequency, CanonicalBar, SeriesPageQuery
from app.market_data.subing_reference import SubingReferenceError
from app.reference_trading.htdy_history import HtdyReplaySegment, history_identity, _cached_replay
from guiyi_quant.reference_trading import BoundaryReason
from guiyi_quant.subing_reference import FORMULA_VERSIONS, REFERENCE_MODEL_VERSION, REFERENCE_MODEL_VERSION_V2, project_reference

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class SignalWindowQuery:
    symbol: str
    strategy: str
    frequency: str
    since: date
    through: date
    from_time: datetime
    to_time: datetime
    as_of: datetime | None = None
    cursor: str | None = None
    limit: int = 200


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _days(service, symbol, since, through, as_of):
    return service.market_data.completed_trading_days(
        symbol=symbol, start=datetime.combine(since - timedelta(days=1), time.min, SHANGHAI),
        as_of=as_of, latest=through, calendar_since=since)


def historical_window_navigation(service, *, symbol, since, through, frequency, as_of):
    start = service.historical_storage_start(symbol)
    days = tuple(day for day in _days(service, symbol, start, through, as_of) if day < since)
    width = 120 if frequency == "1d" else 20
    prior = None if not days else dict(since=days[max(0, len(days)-width)].isoformat(), through=days[-1].isoformat())
    return dict(history_start=start.isoformat(), previous_window=prior,
                window_identity_scope="PER_WINDOW_SOURCE_IDENTITY")


def _canonical_bars(raw):
    return tuple(CanonicalBar(
        bar_end=datetime.fromisoformat(bar["bar_end"]) if isinstance(bar["bar_end"], str) else bar["bar_end"],
        trading_day=date.fromisoformat(bar["trading_day"]) if isinstance(bar["trading_day"], str) else bar["trading_day"],
        **{key: None if bar[key] is None else Decimal(str(bar[key])) for key in
           ("open", "high", "low", "close", "volume", "turnover", "open_interest")}) for bar in raw)



def _preflight_signal_window(service, query, *, since, through, cutoff, as_of):
    # The shared estimate counts two durable events per physical endpoint, plus
    # owner overhead; this reader budgets Bars, never its 4096-byte event estimate.
    event_bound, _ = service.historical_input_bound(symbol=query.symbol,
        frequency=query.frequency, since=since, through=through, as_of=as_of)
    if (event_bound + 1) // 2 > 100000:
        raise SubingReferenceError("SIGNAL_WINDOW_PREFIX_BUDGET_EXCEEDED")
    page = service.market_data.query_page(SeriesPageQuery(
        series_kind="actual_dominant", symbol=query.symbol, frequency=query.frequency,
        before=min(query.to_time, cutoff) + timedelta(microseconds=1), limit=2000))
    bars = tuple(sorted(page.bars, key=lambda bar: bar.bar_end))
    selected = tuple(bar for bar in bars if query.from_time <= bar.bar_end <= query.to_time
                     and query.since <= bar.trading_day <= through)
    if len(selected) == 2000:
        extra = service.market_data.query_page(SeriesPageQuery(
            series_kind="actual_dominant", symbol=query.symbol, frequency=query.frequency,
            before=selected[0].bar_end, limit=1))
        if any(query.from_time <= bar.bar_end <= query.to_time
               and query.since <= bar.trading_day <= through for bar in extra.bars):
            raise SubingReferenceError("SIGNAL_WINDOW_TOO_LARGE")
    # COMPLETE requires actual exact endpoint facts, not a later Session cutoff.
    if not selected or selected[0].bar_end != query.from_time:
        raise SubingReferenceError("SIGNAL_WINDOW_ENDPOINT_UNAVAILABLE")
    if query.to_time <= cutoff and selected[-1].bar_end != query.to_time:
        raise SubingReferenceError("SIGNAL_WINDOW_ENDPOINT_UNAVAILABLE")
    return frozenset((bar.bar_end, bar.trading_day) for bar in selected)

def query_signal_window(service, query, *, persisted_query=None):
    now = service.now()
    as_of = query.as_of or now
    if (query.strategy not in {"htdy", "subing"} or query.frequency not in FORMULA_VERSIONS
            or query.symbol not in service.active_products or query.since > query.through
            or query.since < service.historical_storage_start(query.symbol)
            or any(value.tzinfo is None or value.utcoffset() is None for value in
                   (as_of, query.from_time, query.to_time))
            or as_of > now or query.from_time > query.to_time or query.to_time > as_of
            or not 1 <= query.limit <= 200):
        raise SubingReferenceError("SIGNAL_WINDOW_INVALID_QUERY")
    mode = os.getenv("REFERENCE_TRADING_READER_MODE", "legacy")
    if mode not in {"legacy", "persisted"}:
        raise SubingReferenceError("REFERENCE_READER_MODE_INVALID")
    service.check_cancelled()
    days = tuple(_days(service, query.symbol, query.since, query.through, as_of))
    days = tuple(day for day in days if query.since <= day <= query.through)
    if not days:
        raise SubingReferenceError("SIGNAL_WINDOW_DATA_UNAVAILABLE")
    through = days[-1]
    cutoff = max(window.end for window in service.market_data.session_windows(symbol=query.symbol, trading_day=through))
    before = service.historical_metadata_evidence(symbol=query.symbol, since=days[0], through=through)
    expected_window = _preflight_signal_window(service, query, since=days[0],
        through=through, cutoff=cutoff, as_of=as_of)
    service.check_cancelled()
    segments, raw, quality, loaded_cutoff = service.load_historical_inputs(
        symbol=query.symbol, frequency=BarFrequency(query.frequency), since=days[0], through=through, as_of=as_of)
    if loaded_cutoff != cutoff:
        raise SubingReferenceError("SIGNAL_WINDOW_SOURCE_CONFLICT")
    selected_bars = {(segment.physical_contract, bar.bar_end): bar for segment in segments
        for bar in segment.bars if segment.owner_since <= bar.trading_day <= segment.owner_through
        and query.since <= bar.trading_day <= through
        and query.from_time <= bar.bar_end <= query.to_time}
    if frozenset((bar.bar_end, bar.trading_day) for bar in selected_bars.values()) != expected_window:
        raise SubingReferenceError("SIGNAL_WINDOW_SOURCE_CONFLICT")
    if len(selected_bars) > 2000:
        raise SubingReferenceError("SIGNAL_WINDOW_TOO_LARGE")
    if sum(len(segment.bars) for segment in segments) > 100000:
        raise SubingReferenceError("SIGNAL_WINDOW_PREFIX_BUDGET_EXCEEDED")
    identity = {}
    if mode == "persisted":
        if persisted_query is None:
            raise SubingReferenceError("SIGNAL_WINDOW_NOT_BUILT")
        matches = persisted_query.streams(strategy="htdy" if query.strategy == "htdy" else "subing_reference",
            product=query.symbol.upper(), frequency=query.frequency, mode="historical_replay")
        if len(matches) != 1:
            raise SubingReferenceError("SIGNAL_WINDOW_NOT_BUILT" if not matches else "SIGNAL_WINDOW_IDENTITY_CONFLICT")
        stream = matches[0]
        items, cursor, snapshot = [], None, None
        while True:
            service.check_cancelled()
            page = persisted_query.signals(stream["stream_id"], since=days[0], through=through,
                cutoff=cutoff, limit=200, cursor=cursor, snapshot_token=snapshot, point_kind="signal")
            snapshot = page["snapshot"]
            items.extend(point["value"] for point in page["items"])
            if len(items) > 4000:
                raise SubingReferenceError("SIGNAL_WINDOW_TOO_LARGE")
            cursor = page["next_cursor"]
            if cursor is None:
                break
        identity = dict(stream_id=stream["stream_id"], snapshot=snapshot,
            formula_versions=stream["formula_versions"],
            reference_model_version=stream["reference_model_version"])
    elif query.strategy == "subing":
        projection = project_reference(query.symbol, segments,
            since=min(segment.owner_since for segment in segments), through=through,
            as_of=cutoff, frequency=query.frequency, quality_segmented=query.frequency == "1d")
        items = [asdict(item) for item in projection.signals]
        identity = dict(formula_versions=[FORMULA_VERSIONS[query.frequency]],
            reference_model_version=REFERENCE_MODEL_VERSION_V2 if query.frequency == "1d" else REFERENCE_MODEL_VERSION)
    else:
        canonical = {}
        if query.frequency == "1d":
            for segment in segments:
                if segment.physical_contract not in canonical:
                    bars, _ = service.market_data.query_contract_replay_quality_union(
                        symbol=query.symbol, contract=segment.physical_contract, through=through, cutoff=cutoff)
                    canonical[segment.physical_contract] = {bar.bar_end: bar for bar in bars}
        else:
            canonical = {item["contract"]: {bar.bar_end: bar for bar in _canonical_bars(item["bars"])} for item in raw}
        loaded = tuple(HtdyReplaySegment(segment.physical_contract, segment.segment_id,
            segment.calculation_segment_id or segment.segment_id, segment.owner_since, segment.owner_through,
            tuple(canonical[segment.physical_contract][bar.bar_end] for bar in segment.bars),
            segment.quality_interrupted_at or segment.interrupted_at, segment.quality_interruption_trading_day,
            BoundaryReason.DATA_INTERRUPTED if segment.quality_interrupted_at else BoundaryReason.ROLLOVER)
            for segment in segments)
        stream = history_identity(query.symbol, query.frequency)
        token = _hash(dict(stream=asdict(stream), segments=[asdict(item) for item in loaded], source=before, cutoff=cutoff))
        _, signals, _ = _cached_replay(token, stream, loaded, service.check_cancelled)
        items = [dict(signal, direction=signal["observation_types"][0]) for signal in signals]
        identity = dict(replay_input_hash=token, stream_id=stream.stream_id, formula_versions=stream.formula_versions,
                        reference_model_version=stream.reference_model_version)
    service.check_cancelled()
    after = service.historical_metadata_evidence(symbol=query.symbol, since=days[0], through=through)
    if before != after:
        raise SubingReferenceError("SIGNAL_WINDOW_SOURCE_CONFLICT")
    source = _hash(dict(identity=identity, source=after, raw=raw, cutoff=cutoff,
                        strategy=query.strategy, frequency=query.frequency))
    normalized = []
    for item in items:
        instant = item["bar_end"]
        instant = datetime.fromisoformat(instant) if isinstance(instant, str) else instant
        if query.from_time <= instant <= query.to_time:
            contract = item["physical_contract"]
            if (contract, instant) not in selected_bars:
                raise SubingReferenceError("SIGNAL_WINDOW_SOURCE_CONFLICT")
            normalized.append(dict(item, bar_end=instant))
    normalized.sort(key=lambda item: (item["bar_end"], item["physical_contract"]))
    key = _hash(dict(source=source, since=query.since, through=query.through,
                     from_time=query.from_time, to_time=query.to_time, mode=mode))
    offset = 0
    if query.cursor:
        parts = query.cursor.split(":")
        if len(parts) != 2 or parts[0] != key or not parts[1].isdigit():
            raise SubingReferenceError("SIGNAL_WINDOW_CURSOR_CONFLICT")
        offset = int(parts[1])
    times = sorted(bar.bar_end for bar in selected_bars.values())
    return dict(schema_version="historical_signal_window_v1", strategy=query.strategy,
        symbol=query.symbol, frequency=query.frequency, recording_mode="historical_replay",
        **{"from": query.from_time, "to": query.to_time}, history_start=service.historical_storage_start(query.symbol),
        identity=dict(identity, input_snapshot_hash=source),
        coverage=dict(status="COMPLETE" if cutoff >= query.to_time else "PARTIAL_CANONICAL",
            first_bar_end=times[0] if times else None, last_bar_end=times[-1] if times else None,
            bar_count=len(selected_bars), completed_through=cutoff),
        items=normalized[offset:offset+query.limit],
        next_cursor=f"{key}:{offset+query.limit}" if offset+query.limit < len(normalized) else None,
        executable=False, auto_order=False)
