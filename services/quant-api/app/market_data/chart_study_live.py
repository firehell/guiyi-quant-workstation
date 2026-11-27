"""Bounded, transient Web calculation state over Market display snapshots."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from itertools import groupby
from threading import RLock

from guiyi_quant.compute import (
    REGISTRY, BarSeries, FeaturePoint, FeatureRequest, IncrementalState, SeriesIdentity, advance, open_incremental,
)
from guiyi_quant.compute.contracts import hash_parameters

from app.market_data.aggregation import bucket_window_for_bar
from app.market_data.chart_indicators import (
    ANCHOR_POLICY, ChartStudyBlock, OwnedChartBar, WARM_PREFIX, bar_output, block_segment_id, block_series,
    calculation_blocks, chart_scope, point_output, source_revision, study_bar,
)
from app.market_data.domain import (
    BarFrequency, DatasetKey, DatasetKind, INTRADAY_FREQUENCIES, SeriesKind, SeriesPageQuery,
)
from app.market_data.market_data_service import DominantContractSegmentSummary, MarketDataError, MarketDataService
from app.market_data.market_display_preview import MarketActivity
from app.market_data.market_read_service import MarketDisplaySnapshot
from app.schemas.market import (
    MarketChartStudyDisplayOut, MarketChartStudyFeatureOut, MarketChartStudyId, MarketChartStudyPreviewOut,
    MarketChartStudySegmentOut,
)

_MAX_SEEDS = 12
_MAX_LIVE_BARS = 800
_CACHE: OrderedDict[tuple, ChartStudySeed] = OrderedDict()
_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class _StudyState:
    identity: SeriesIdentity
    month: tuple[int, int]
    anchor: datetime
    recent: tuple[OwnedChartBar, ...]
    features: tuple[IncrementalState, ...]


@dataclass(frozen=True, slots=True)
class _ComputedRow:
    row: OwnedChartBar
    segment: str
    anchor: datetime
    points: tuple[FeaturePoint, ...]


@dataclass(slots=True)
class ChartStudySeed:
    block: ChartStudyBlock
    recent: tuple[OwnedChartBar, ...]
    evidence: str
    base: _StudyState | None = None
    live: _StudyState | None = None
    live_rows: tuple[_ComputedRow, ...] = ()


def _cache_key(market: MarketDataService, identity: SeriesPageQuery, canonical_end: datetime,
               revision: str, studies: tuple[MarketChartStudyId, ...]) -> tuple:
    return (market.catalog.canonical_root, market.catalog.session.get_bind().url, identity.symbol,
            identity.series_kind, identity.contract, identity.frequency, canonical_end, revision, studies)


def _evidence(market: MarketDataService, identity: SeriesPageQuery,
              block: ChartStudyBlock, recent: tuple[OwnedChartBar, ...]) -> str:
    """Proof of the applicable active partition and metadata identities, without decoding a prefix."""
    first, last = min(block.rows[0].bar, recent[0].bar, key=lambda bar: bar.bar_end), block.rows[-1]
    key = DatasetKey(DatasetKind.CONTRACT, identity.symbol, last.contract, identity.frequency)
    partitions = market.catalog.partitions(key, first.bar_end - timedelta(microseconds=1), last.bar.bar_end)
    if not partitions:
        raise MarketDataError("MARKET_CHART_STUDY_ANCHOR_UNAVAILABLE")
    metadata = market.historical_metadata_evidence(
        symbol=identity.symbol, since=first.trading_day, through=last.bar.trading_day,
    )
    owner = (
        market.dominant_segment_for_day(identity.symbol, last.bar.trading_day)
        if identity.series_kind is SeriesKind.ACTUAL_DOMINANT else None
    )
    owner_anchor = None if owner is None else (owner.contract, owner.start_trading_day)
    identity_parts = (partitions, metadata, owner_anchor)
    return sha256(repr(identity_parts).encode()).hexdigest()


def retain_chart_study_seed(
    market: MarketDataService, identity: SeriesPageQuery, rows: tuple[OwnedChartBar, ...], revision: str,
    studies: tuple[MarketChartStudyId, ...],
) -> None:
    block = calculation_blocks(rows)[-1]
    last = rows[-1]
    recent = []
    for row in reversed(rows[-WARM_PREFIX:]):
        if row.owner_segment != last.owner_segment or not row.quality_ok:
            break
        recent.append(row)
    prefix = tuple(reversed(recent)) or (last,)
    evidence = _evidence(market, identity, block, prefix)
    key = _cache_key(market, identity, last.bar.bar_end, revision, studies)
    with _LOCK:
        existing = _CACHE.get(key)
        if existing is None or existing.evidence != evidence:
            _CACHE[key] = ChartStudySeed(block, prefix, evidence)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_SEEDS:
            _CACHE.popitem(last=False)


def read_chart_study_seed(
    market: MarketDataService, identity: SeriesPageQuery, canonical_end: datetime, revision: str,
    studies: tuple[MarketChartStudyId, ...],
) -> ChartStudySeed:
    key = _cache_key(market, identity, canonical_end, revision, studies)
    with _LOCK:
        seed = _CACHE.get(key)
        if seed is not None:
            _CACHE.move_to_end(key)
    if seed is None:
        raise MarketDataError("MARKET_CHART_STUDY_BASE_EXPIRED")
    if seed.evidence != _evidence(market, identity, seed.block, seed.recent):
        with _LOCK:
            _CACHE.pop(key, None)
        raise MarketDataError("MARKET_CHART_STUDY_WINDOW_MISMATCH")
    return seed


def _month(row: OwnedChartBar) -> tuple[int, int]:
    return row.bar.trading_day.year, row.bar.trading_day.month


def _open(
    series: BarSeries, requests: tuple[FeatureRequest, ...], *, as_of: datetime,
) -> tuple[IncrementalState, ...]:
    return tuple(open_incremental(series, request, as_of=as_of, mode="incremental", use="web")
                 for request in requests)


def _step(
    scope: SeriesPageQuery, current: _StudyState, row: OwnedChartBar, requests: tuple[FeatureRequest, ...],
) -> tuple[_StudyState, _ComputedRow]:
    previous = current.recent[-1]
    if (row.owner_segment != previous.owner_segment or _month(row) != current.month
            or not previous.quality_ok or not row.quality_ok):
        warm = (
            current.recent
            if row.owner_segment == previous.owner_segment and previous.quality_ok and row.quality_ok
            else ()
        )
        first = warm[0] if warm else row
        segment = block_segment_id(first, row.bar.trading_day)
        identity = SeriesIdentity(
            scope.symbol, row.contract, segment, scope.frequency.value, source_revision(warm),
        )
        prefix = BarSeries(identity, tuple(study_bar(item, segment) for item in warm))
        current = _StudyState(identity, _month(row), first.bar.bar_end, warm,
                              _open(prefix, requests, as_of=row.bar.bar_end))
    updates = tuple(advance(state, current.identity, study_bar(row, current.identity.segment_id))
                    for state in current.features)
    states, points = zip(*updates, strict=True)
    return (
        _StudyState(
            current.identity, current.month, current.anchor,
            (*current.recent, row)[-WARM_PREFIX:], states,
        ),
        _ComputedRow(row, current.identity.segment_id, current.anchor, points),
    )


def _segments(
    rows: tuple[_ComputedRow, ...], studies: tuple[MarketChartStudyId, ...], *, active: bool = False,
) -> list[MarketChartStudySegmentOut]:
    result = []
    for segment, pool in groupby(rows, key=lambda item: item.segment):
        group = tuple(pool)
        first = group[0]
        features = []
        for index, study in enumerate(studies):
            definition = REGISTRY.definition(study)
            features.append(MarketChartStudyFeatureOut(
                study=study, formula_version=definition.formula_version, backend_version=definition.backend_version,
                parameters_hash=hash_parameters(definition.resolve(FeatureRequest(study))),
                points=[point_output(item.points[index]) for item in group],
            ))
        result.append(MarketChartStudySegmentOut(
            physical_contract=first.row.contract, segment_id=segment, calculation_anchor=first.anchor,
            bars=[bar_output(item.row.bar, "active_preview" if active else "completed_live") for item in group],
            features=features,
        ))
    return result


def _owner_segment(scope: SeriesPageQuery, rank: DominantContractSegmentSummary) -> str:
    return f"contract:{rank.contract}" if scope.contract else f"{rank.contract}:{rank.start_trading_day}"


def verify_tail_reconciliation(
    market: MarketDataService, scope: SeriesPageQuery, display: MarketDisplaySnapshot,
    response: MarketChartStudyDisplayOut,
) -> None:
    latest = market.query_page(scope, mapping_cache={})
    if not latest.bars or latest.bars[-1].bar_end != response.as_of:
        raise MarketDataError("MARKET_CHART_STUDY_WINDOW_MISMATCH")
    segments = [*response.segments, *([response.preview.segment] if response.preview else [])]
    if not segments:
        return
    day = display.state.trading_day
    assert day is not None
    rank = market.dominant_segment_for_day(scope.symbol, day)
    prefix = f"{ANCHOR_POLICY}:{_owner_segment(scope, rank)}:"
    if any(segment.physical_contract != rank.contract or not segment.segment_id.startswith(prefix)
           for segment in segments):
        raise MarketDataError("MARKET_CHART_STUDY_WINDOW_MISMATCH")


def _intraday_preview_proved(
    market: MarketDataService, scope: SeriesPageQuery, display: MarketDisplaySnapshot, activity: MarketActivity,
) -> bool:
    if display.state.phase != "TRADING" or not display.state.live_available:
        return False
    end = activity.bar.bar_end
    windows = market.session_windows(symbol=scope.symbol, trading_day=activity.bar.trading_day)
    matches = [window for window in windows if window.start < end <= window.end]
    if len(matches) != 1:
        return False
    (window,) = matches
    if scope.frequency is BarFrequency.M1:
        start = end - timedelta(minutes=1)
    else:
        bucket = bucket_window_for_bar(window, scope.frequency, end)
        if bucket.end != end:
            return False
        start = bucket.start
    return window.start <= start <= activity.observed_at < end


def _verified_tail(
    market: MarketDataService, scope: SeriesPageQuery, display: MarketDisplaySnapshot, seed: ChartStudySeed,
    through: datetime | None, include_preview: bool, now: datetime,
):
    last = seed.block.rows[-1]
    state = display.state
    if state.canonical_end != last.bar.bar_end:
        raise MarketDataError("MARKET_CHART_STUDY_WINDOW_MISMATCH")
    if state.phase == "CLOSED":
        return (), None

    activity = display.preview.activity if include_preview and display.preview is not None else None
    if activity is not None and activity.bar.bar_end <= last.bar.bar_end:
        activity = None
    if through is None and activity is None:
        return (), None
    day = state.trading_day
    if day is None or state.phase == "UNKNOWN":
        raise MarketDataError("MARKET_CHART_STUDY_LIVE_IDENTITY_UNAVAILABLE")
    if through is not None and (display.source == "none" or display.trading_day != day or display.contract is None):
        raise MarketDataError("MARKET_CHART_STUDY_LIVE_IDENTITY_UNAVAILABLE")

    rank = market.dominant_segment_for_day(scope.symbol, day)
    contract = rank.contract
    if (
        scope.contract is not None and scope.contract != contract
        or display.contract is not None and display.contract != contract
        or activity is not None and (activity.contract != contract or activity.bar.trading_day != day)
    ):
        raise MarketDataError("MARKET_CHART_STUDY_LIVE_IDENTITY_UNAVAILABLE")
    owner = _owner_segment(scope, rank)
    rolled = owner != last.owner_segment
    since = rank.start_trading_day if rolled else last.bar.trading_day
    # A retained price-only tail cannot be used to bridge an unproven day.
    if day < since or day - since > timedelta(days=32):
        raise MarketDataError("MARKET_CHART_STUDY_LIVE_IDENTITY_UNAVAILABLE")

    bars = tuple(bar for bar in display.bars if through is not None and bar.bar_end <= through)
    if through is not None and (not bars or bars[-1].bar_end != through or display.contract != contract):
        raise MarketDataError("MARKET_CHART_STUDY_LIVE_GAP")
    if len(bars) > _MAX_LIVE_BARS:
        raise MarketDataError("MARKET_CHART_STUDY_LIVE_GAP")
    if activity is not None and bars and activity.bar.bar_end <= bars[-1].bar_end:
        activity = None
    if activity is not None and scope.frequency in INTRADAY_FREQUENCIES:
        # The preview must follow the newest completed Market Bar, including
        # completions the browser may not have processed yet.
        if (activity.bar.bar_end <= now or len(bars) != len(display.bars)
                or not _intraday_preview_proved(market, scope, display, activity)):
            activity = None
    cutoff = activity.bar.bar_end if activity is not None else through
    if cutoff is None:
        return (), None
    upper = cutoff
    if activity is not None and scope.frequency is BarFrequency.W1:
        # The Market's weekly display activity can be dated at the current
        # daily close, before its official weekly endpoint exists.
        upper = min(now, cutoff - timedelta(microseconds=1))
    expected = market.expected_contract_replay_endpoints(
        symbol=scope.symbol, contract=contract, frequency=scope.frequency, trading_day=day,
        cutoff=upper, after=last.bar.bar_end, since=since,
    )
    actual = tuple((bar.bar_end, bar.trading_day) for bar in bars)
    if activity is not None and scope.frequency is not BarFrequency.W1:
        actual += ((activity.bar.bar_end, activity.bar.trading_day),)
    if expected != actual:
        # A stale or incomplete preview must not suppress a verified completed prefix.
        if activity is None or expected[:len(bars)] != actual[:len(bars)]:
            raise MarketDataError("MARKET_CHART_STUDY_LIVE_GAP")
        activity = None
    return tuple(OwnedChartBar(bar, contract, owner) for bar in bars), (
        (activity, OwnedChartBar(activity.bar, contract, owner)) if activity is not None else None
    )


def project_chart_study_tail(
    market: MarketDataService, scope: SeriesPageQuery, display: MarketDisplaySnapshot, seed: ChartStudySeed,
    *, canonical_end: datetime, revision: str, studies: tuple[MarketChartStudyId, ...],
    through: datetime | None, include_preview: bool, now: datetime, check_cancelled,
) -> MarketChartStudyDisplayOut:
    response = dict(**chart_scope(scope, canonical_end), source_revision=revision, unavailable_reason=None)
    try:
        rows, activity = _verified_tail(market, scope, display, seed, through, include_preview, now)
    except MarketDataError as exc:
        if exc.code == "MARKET_CHART_STUDY_WINDOW_MISMATCH":
            raise
        reason = exc.code if exc.code.startswith("MARKET_CHART_STUDY_") else "MARKET_CHART_STUDY_LIVE_IDENTITY_UNAVAILABLE"
        return MarketChartStudyDisplayOut(**response, segments=[],
                                          tail_unavailable_reason=reason)
    if not rows and activity is None:
        return MarketChartStudyDisplayOut(
            **response, segments=[],
            tail_unavailable_reason="MARKET_CHART_STUDY_PREVIEW_UNAVAILABLE" if include_preview else None,
        )

    requests = tuple(FeatureRequest(study) for study in studies)
    with _LOCK:
        if seed.base is None:
            series = block_series(scope, seed.block)
            seed.base = _StudyState(
                series.identity, _month(seed.block.rows[-1]), seed.block.anchor, seed.recent,
                _open(series, requests, as_of=canonical_end),
            )
        observed = tuple(item.row for item in seed.live_rows)
        common = min(len(rows), len(observed))
        if rows[:common] != observed[:common]:
            raise MarketDataError("MARKET_CHART_STUDY_LIVE_REVISION_CONFLICT")
        current = seed.base
        if len(rows) >= len(observed) and seed.live is not None:
            current = seed.live
            computed = list(seed.live_rows)
        else:
            computed = []
        for row in rows[len(computed):]:
            check_cancelled()
            current, result = _step(scope, current, row, requests)
            computed.append(result)
        finished = tuple(computed)
        if len(finished) > len(seed.live_rows):
            seed.live, seed.live_rows = current, finished

        preview = None
        if activity is not None:
            fact, row = activity
            check_cancelled()
            # Core has one pure step input type. Only this fork uses the
            # hypothetical endpoint, and the returned state is never retained.
            _, value = _step(scope, current, row, requests)
            (segment,) = _segments((value,), studies, active=True)
            preview = MarketChartStudyPreviewOut(
                segment=segment, generation=fact.generation,
                observed_at=fact.observed_at, received_at=fact.received_at,
            )
    return MarketChartStudyDisplayOut(
        **response, segments=_segments(finished, studies), preview=preview,
        tail_unavailable_reason="MARKET_CHART_STUDY_PREVIEW_UNAVAILABLE" if include_preview and preview is None else None,
    )
