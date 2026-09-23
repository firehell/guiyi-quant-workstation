"""Read-only SuBing historical reference, using the existing MarketDataService authority."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from guiyi_quant.subing_reference import (
    FORMULA_VERSIONS,
    REFERENCE_MODEL_VERSION,
    REFERENCE_MODEL_VERSION_V2,
    ReferenceBar,
    ReferenceSegment,
    ReferenceProjectionError,
    project_reference,
)
from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.diagnostics import DATA_REASONS, data_reason, safe_context
from app.market_data.domain import (
    BarFrequency,
    ContractTradingDayQuery,
    MarketSeriesResult,
)
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.source_quality import SourceQualityFact

SHANGHAI = ZoneInfo("Asia/Shanghai")
D1_QUALITY_POLICY_VERSION = "subing-d1-quality-segment-v1"


class SubingReferenceError(ValueError):
    def __init__(
        self, code: str, *, diagnostic: Mapping[str, object] | None = None
    ):
        self.code = code
        self.diagnostic = _diagnostic(diagnostic)
        super().__init__(code)


class Coverage(Protocol):
    def product_start(self, symbol: str) -> date: ...


@dataclass(frozen=True)
class SubingReferenceQuery:
    symbol: str
    since: date | None = None
    through: date | None = None
    as_of: datetime | None = None
    before: str | None = None
    limit: int = 50
    frequency: str = "15m"


class SubingReferenceService:
    def __init__(
        self,
        market_data: MarketDataService,
        *,
        coverage: Coverage,
        active_products: Collection[str],
        now: Callable[[], datetime] | None = None,
        check_cancelled: Callable[[], None] | None = None,
    ):
        self.market_data = market_data
        self.coverage = coverage
        self.active_products = frozenset(active_products)
        self.now = now or (lambda: datetime.now(UTC))
        self.check_cancelled = check_cancelled or (lambda: None)

    def load_historical_inputs(
        self,
        *,
        symbol: str,
        frequency: BarFrequency,
        since: date,
        through: date,
        as_of: datetime,
    ):
        """Return the typed MDS-backed replay inputs without projecting trades."""
        if as_of.tzinfo is None or as_of.utcoffset() is None or since > through:
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
        sessions = self._session_windows(symbol, through)
        cutoff = max(window.end for window in sessions)
        if cutoff > as_of:
            raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")
        segments, inputs, quality = self._inputs(
            symbol, since, through, cutoff, frequency,
        )
        return segments, inputs, quality, cutoff

    def historical_metadata_evidence(
        self, *, symbol: str, since: date, through: date,
    ) -> dict[str, object]:
        """Expose the exact MDS metadata proof required by offline P4 replay."""
        return self.market_data.historical_metadata_evidence(
            symbol=symbol, since=since, through=through,
        )

    def historical_storage_start(self, symbol: str) -> date:
        return self.coverage.product_start(symbol)

    def historical_input_bound(
        self, *, symbol: str, frequency: str, since: date, through: date,
        as_of: datetime,
    ) -> tuple[int, int]:
        """Bound physical-prefix warm-up across every authoritative owner."""
        if as_of.tzinfo is None or as_of.utcoffset() is None or since > through:
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
        bar_frequency = BarFrequency(frequency)
        owners = ActualDominantResearchSegmentLoader(
            self.market_data
        ).owner_segments(symbol=symbol, since=since, through=through)
        endpoint_count = 0
        for owner in owners:
            own_last = min(owner.end_trading_day, through)
            cutoff = max(
                window.end for window in self._session_windows(symbol, own_last)
            )
            if cutoff > as_of:
                raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")
            endpoints = self.market_data.expected_contract_replay_endpoints(
                symbol=symbol,
                contract=owner.contract,
                frequency=bar_frequency,
                trading_day=own_last,
                cutoff=cutoff,
                after=None,
            )
            if not endpoints:
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            endpoint_count += len(endpoints)
        # One interruption per physical endpoint plus one owner boundary is a
        # conservative ceiling for the typed replay event stream.
        max_events = endpoint_count * 2 + len(owners)
        return max_events, max_events * 4096

    def read_daily_quality_presentation(
        self, *, symbol: str, since: date, through: date, cutoff: datetime,
    ) -> dict[str, Any]:
        """Read bounded D1 chart and quality facts without projecting a trade.

        The same MDS quality segmentation used by the legacy reference reader
        supplies chart bars; no strategy kernel or provider is invoked.
        """
        if (
            symbol not in self.active_products
            or type(since) is not date or type(through) is not date
            or since > through or (through - since).days > 366
            or cutoff.tzinfo is None or cutoff.utcoffset() is None
        ):
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
        _segments, _inputs, quality = self._daily_quality_inputs(
            symbol, since, through, cutoff,
        )
        if len(quality["quality_chart_bars"]) > 500:
            raise SubingReferenceError("SUBING_REFERENCE_BUDGET_EXCEEDED")
        return _wire(quality)

    def resolve_read_window(
        self, query: SubingReferenceQuery,
    ) -> tuple[date, date, datetime, datetime]:
        """Resolve calendar/session cutoff without running the strategy kernel."""
        now = self.now()
        as_of = query.as_of or now
        self._validate_query(query, as_of, now)
        since, through, cutoff = self._window(query, as_of)
        return since, through, cutoff, as_of

    def query(self, query: SubingReferenceQuery) -> dict[str, Any]:
        self.check_cancelled()
        now = self.now()
        as_of = query.as_of or now
        self._validate_query(query, as_of, now)
        since, through, cutoff = self._window(query, as_of)
        frequency = BarFrequency(query.frequency)
        self.check_cancelled()
        segments, inputs, quality = self._inputs(
            query.symbol, since, through, cutoff, frequency,
        )
        self.check_cancelled()
        try:
            projection = project_reference(
                query.symbol, segments, since=since, through=through, as_of=cutoff,
                frequency=query.frequency,
                quality_segmented=frequency is BarFrequency.D1,
            )
        except ReferenceProjectionError as exc:
            raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT") from exc
        self.check_cancelled()
        fingerprint = _hash(
            {
                "symbol": query.symbol,
                "frequency": query.frequency,
                "formula_version": FORMULA_VERSIONS[query.frequency],
                "reference_model_version": (
                    REFERENCE_MODEL_VERSION_V2
                    if frequency is BarFrequency.D1 else REFERENCE_MODEL_VERSION
                ),
                "since": since,
                "through": through,
                "cutoff": cutoff,
                "inputs": inputs,
            }
        )
        trades = sorted(
            projection.trades,
            key=lambda item: (item.entry_bar_end, item.reference_trade_id),
            reverse=True,
        )
        offset = 0
        if query.before is not None:
            match = re.fullmatch(r"([0-9a-f]{64}):([0-9a-f]{64})", query.before)
            if match is None:
                raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
            if match[1] != fingerprint:
                raise SubingReferenceError("SUBING_REFERENCE_SNAPSHOT_CHANGED")
            matches = [
                index
                for index, item in enumerate(trades)
                if _hash(item.reference_trade_id) == match[2]
            ]
            if len(matches) != 1:
                raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
            offset = matches[0] + 1
        items = trades[offset : offset + query.limit]
        next_before = (
            f"{fingerprint}:{_hash(items[-1].reference_trade_id)}"
            if items and offset + len(items) < len(trades)
            else None
        )
        summary = asdict(projection.summary)
        signals = [asdict(item) for item in projection.signals]
        indicators = [asdict(item) for item in projection.indicators]
        wire_items = [asdict(item) for item in items]
        if frequency is not BarFrequency.D1:
            summary.pop("rollover_interrupted_count")
            summary.pop("data_interrupted_count")
            for item in (*signals, *indicators, *wire_items):
                item.pop("calculation_segment_id")
            for item in wire_items:
                item.pop("interruption_reason")
                item.pop("interruption_trading_day")
        return _wire(
            {
                "symbol": query.symbol,
                "frequency": query.frequency,
                "series_kind": "actual_dominant",
                "formula_version": FORMULA_VERSIONS[query.frequency],
                "reference_model_version": (
                    REFERENCE_MODEL_VERSION_V2
                    if frequency is BarFrequency.D1 else REFERENCE_MODEL_VERSION
                ),
                "as_of": as_of,
                "performance_since": since,
                "performance_through": through,
                "reference_cutoff": cutoff,
                "input_snapshot_hash": fingerprint,
                "executable": False,
                "auto_order": False,
                "source": "historical_replay",
                "research_status": projection.readiness,
                "summary": summary,
                "signals": signals,
                "indicators": indicators,
                "items": wire_items,
                "next_before": next_before,
                **quality,
            }
        )

    def _validate_query(
        self, query: SubingReferenceQuery, as_of: datetime, now: datetime
    ) -> None:
        if (
            query.frequency not in FORMULA_VERSIONS
            or
            query.symbol not in self.active_products
            or not re.fullmatch(r"[a-z]{1,3}", query.symbol)
            or type(query.limit) is not int
            or not 1 <= query.limit <= 200
            or not isinstance(as_of, datetime)
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or as_of > now
            or any(
                value is not None and type(value) is not date
                for value in (query.since, query.through)
            )
            or (
                query.since is not None
                and query.through is not None
                and query.since > query.through
            )
            or (
                query.before is not None
                and (not isinstance(query.before, str) or len(query.before) > 2048)
            )
        ):
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")

    def _window(
        self, query: SubingReferenceQuery, as_of: datetime
    ) -> tuple[date, date, datetime]:
        latest = as_of.astimezone(SHANGHAI).date()
        if query.through is not None and query.through > latest:
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
        start = max(
            self.coverage.product_start(query.symbol),
            (query.through or latest) - timedelta(days=365),
        )
        if query.since is not None and query.since < start:
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
        calendar_as_of = as_of
        if query.through is not None:
            calendar_as_of = min(
                as_of,
                max(
                    window.end
                    for window in self._session_windows(query.symbol, query.through)
                ),
            )
        try:
            days = self.market_data.completed_trading_days(
                symbol=query.symbol,
                start=datetime.combine(start - timedelta(days=1), time.min, SHANGHAI),
                as_of=calendar_as_of,
                latest=query.through or latest,
                calendar_since=start,
            )
        except MarketDataError as exc:
            reason = getattr(exc, "reason", None) or data_reason(exc.code)
            stage = "session" if reason in {
                "TRADING_SESSION_MISSING", "HISTORICAL_SESSION_FACT_MISSING"
            } else "calendar"
            self._raise_data_unavailable(exc, stage, query.symbol)
        days = tuple(day for day in days if day >= start)
        if not days or tuple(sorted(set(days))) != days:
            raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
        # Calendar/session facts select the window, never whichever dataset exists.
        through = query.through or days[-1]
        if through != days[-1]:
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
        default_days = 120 if query.frequency == "1d" else 20
        since = query.since or days[max(0, len(days) - default_days)]
        if since > through:
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
        sessions = self._session_windows(query.symbol, through)
        cutoff = max(window.end for window in sessions)
        if cutoff > as_of:
            raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")
        return since, through, cutoff

    def _inputs(
        self, symbol: str, since: date, through: date, cutoff: datetime,
        frequency: BarFrequency,
    ) -> tuple[
        tuple[ReferenceSegment, ...], list[dict[str, Any]], dict[str, Any]
    ]:
        if frequency is BarFrequency.D1:
            return self._daily_quality_inputs(symbol, since, through, cutoff)
        try:
            loaded = ActualDominantResearchSegmentLoader(self.market_data).load(
                symbol=symbol,
                frequencies=(frequency,),
                since=since,
                through=through,
            )
        except MarketDataError as exc:
            self._raise_data_unavailable(exc, "actual_dominant_replay", symbol, frequency)
        actual = loaded.results[frequency]
        _identity(actual, symbol, "actual_dominant", None, frequency)
        _order(actual)
        owners = loaded.authoritative_segments
        if actual.requested_trading_day_window != (
            owners[0].start_trading_day,
            through,
        ):
            raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")
        result: list[ReferenceSegment] = []
        inputs: list[dict[str, Any]] = []
        for index, owner in enumerate(owners):
            self.check_cancelled()
            own_bars = tuple(
                bar
                for bar in actual.bars
                if owner.start_trading_day
                <= bar.trading_day
                <= min(owner.end_trading_day, through)
            )
            if not own_bars:
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            own_last_day = own_bars[-1].trading_day
            if own_last_day != min(owner.end_trading_day, through):
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            end = max(
                window.end
                for window in self._session_windows(symbol, own_last_day)
            )
            if end > cutoff or own_bars[-1].bar_end != end:
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            expected = self.market_data.expected_contract_replay_endpoints(
                symbol=symbol,
                contract=owner.contract,
                frequency=frequency,
                trading_day=own_last_day,
                cutoff=end,
                after=None,
            )
            if not expected or expected[-1] != (end, own_last_day):
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            self.check_cancelled()
            try:
                physical = self.market_data.query_contract_trading_days(
                    ContractTradingDayQuery(
                        symbol,
                        owner.contract,
                        frequency,
                        expected[0][1],
                        own_last_day,
                    )
                )
            except MarketDataError as exc:
                reason = getattr(exc, "reason", None) or data_reason(exc.code)
                if reason not in DATA_REASONS:
                    raise
                context = {
                    "symbol": symbol,
                    "contract": owner.contract,
                    "frequency": frequency.value,
                    "expected_count": len(expected),
                    **getattr(exc, "context", {}),
                }
                raise SubingReferenceError(
                    "SUBING_REFERENCE_DATA_UNAVAILABLE",
                    diagnostic={
                        "stage": "physical_contract_replay",
                        "reason": reason,
                        "context": context,
                    },
                ) from exc
            _identity(physical, symbol, "contract", owner.contract, frequency)
            _order(physical)
            if (
                physical.requested_trading_day_window != (expected[0][1], own_last_day)
                or tuple((bar.bar_end, bar.trading_day) for bar in physical.bars)
                != expected
            ):
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            physical_owned = tuple(
                bar
                for bar in physical.bars
                if owner.start_trading_day <= bar.trading_day <= owner.end_trading_day
            )
            if own_bars != physical_owned:
                raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")
            interruption = None
            if index + 1 < len(owners):
                next_owner = owners[index + 1]
                interruption = min(
                    window.start
                    for window in self._session_windows(
                        symbol, next_owner.start_trading_day
                    )
                )
                if not end <= interruption <= cutoff:
                    raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")
            segment_id = _hash([symbol, owner.contract, owner.start_trading_day])
            result.append(
                ReferenceSegment(
                    physical_contract=owner.contract,
                    segment_id=segment_id,
                    bars=tuple(
                        ReferenceBar(bar.bar_end, bar.trading_day, bar.close)
                        for bar in physical.bars
                    ),
                    owner_since=owner.start_trading_day,
                    owner_through=min(owner.end_trading_day, through),
                    interrupted_at=interruption,
                )
            )
            inputs.append(
                {
                    "contract": owner.contract,
                    "segment_id": segment_id,
                    "owner_since": owner.start_trading_day,
                    "owner_through": min(owner.end_trading_day, through),
                    "interrupted_at": interruption,
                    "bars": [bar.as_record() for bar in physical.bars],
                }
            )
        if actual.bars[-1].trading_day != through or actual.bars[-1].bar_end != cutoff:
            raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
        return tuple(result), inputs, {}

    def _daily_quality_inputs(
        self, symbol: str, since: date, through: date, cutoff: datetime,
    ) -> tuple[
        tuple[ReferenceSegment, ...], list[dict[str, Any]], dict[str, Any]
    ]:
        try:
            owners = self.market_data.actual_dominant_segments(symbol, since, through)
        except MarketDataError as exc:
            self._raise_data_unavailable(exc, "actual_dominant_replay", symbol, BarFrequency.D1)
        if not owners or owners[0].start_trading_day > since or owners[-1].end_trading_day < through:
            raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
        result: list[ReferenceSegment] = []
        inputs: list[dict[str, Any]] = []
        interruptions: list[dict[str, Any]] = []
        coverage_events: list[dict[str, Any]] = []
        chart_bars: list[dict[str, Any]] = []
        for owner_index, owner in enumerate(owners):
            self.check_cancelled()
            own_through = min(owner.end_trading_day, through)
            if own_through < since:
                continue
            end = max(
                window.end for window in self._session_windows(symbol, own_through)
            )
            if end > cutoff:
                raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")
            try:
                bars, facts = self.market_data.query_contract_replay_quality_union(
                    symbol=symbol, contract=owner.contract,
                    through=own_through, cutoff=end,
                )
            except MarketDataError as exc:
                self._raise_data_unavailable(
                    exc, "physical_contract_replay", symbol, BarFrequency.D1,
                )
            ordered: list[tuple[datetime, ReferenceBar | SourceQualityFact]] = [
                (bar.bar_end, ReferenceBar(bar.bar_end, bar.trading_day, bar.close))
                for bar in bars
            ] + [(fact.bar_end, fact) for fact in facts]
            ordered.sort(key=lambda item: item[0])
            if not ordered or len({item[0] for item in ordered}) != len(ordered):
                raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")
            owned = [
                item for _, item in ordered
                if owner.start_trading_day <= item.trading_day <= own_through
            ]
            if not owned or owned[-1].trading_day != own_through:
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            owner_segment_id = _hash([
                "subing-owner-segment-v1", symbol, owner.contract,
                owner.start_trading_day,
            ])
            first_end, first_item = ordered[0]
            boundary: list[object] = [
                "LIFECYCLE_START", first_end, first_item.trading_day,
            ]
            current: list[ReferenceBar] = []
            owner_segments: list[ReferenceSegment] = []

            def append_segment(
                quality_fact: SourceQualityFact | None = None,
            ) -> None:
                nonlocal current
                if not current or not any(
                    owner.start_trading_day <= bar.trading_day <= own_through
                    for bar in current
                ):
                    current = []
                    return
                calculation_id = _hash([
                    "subing-d1-calculation-segment-v1",
                    D1_QUALITY_POLICY_VERSION,
                    symbol,
                    BarFrequency.D1.value,
                    owner.contract,
                    owner.start_trading_day,
                    boundary,
                    current[0].bar_end,
                ])
                owner_segments.append(ReferenceSegment(
                    physical_contract=owner.contract,
                    segment_id=owner_segment_id,
                    bars=tuple(current),
                    owner_since=owner.start_trading_day,
                    owner_through=own_through,
                    calculation_segment_id=calculation_id,
                    quality_interrupted_at=(
                        quality_fact.bar_end if quality_fact is not None else None
                    ),
                    quality_interruption_trading_day=(
                        quality_fact.trading_day if quality_fact is not None else None
                    ),
                    quality_classification=(
                        quality_fact.classification if quality_fact is not None else None
                    ),
                ))
                current = []

            for _, item in ordered:
                if isinstance(item, ReferenceBar):
                    current.append(item)
                    continue
                append_segment(item)
                interruptions.append({
                    "bar_end": item.bar_end,
                    "trading_day": item.trading_day,
                    "physical_contract": owner.contract,
                    "segment_id": owner_segment_id,
                    "classification": item.classification,
                    "classification_version": item.classification_version,
                    "request_sha256": item.request_sha256,
                    "response_sha256": item.response_sha256,
                })
                boundary = [
                    item.classification,
                    item.classification_version,
                    item.bar_end,
                    item.response_sha256,
                ]
                if since <= item.trading_day <= through and (
                    owner.start_trading_day <= item.trading_day <= own_through
                ):
                    coverage_events.append({
                        "since": item.trading_day,
                        "through": item.trading_day,
                        "status": item.classification,
                        "physical_contract": owner.contract,
                        "segment_id": owner_segment_id,
                        "calculation_segment_id": None,
                    })
            append_segment()
            if not owner_segments:
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            if owner_index + 1 < len(owners):
                next_owner = owners[owner_index + 1]
                rollover_at = min(
                    window.start for window in self._session_windows(
                        symbol, next_owner.start_trading_day,
                    )
                )
                owner_segments[-1] = replace(
                    owner_segments[-1], interrupted_at=rollover_at,
                )
            for segment in owner_segments:
                ordinal = 0
                canonical_by_end = {bar.bar_end: bar for bar in bars}
                for bar in segment.bars:
                    ordinal += 1
                    if not (
                        owner.start_trading_day <= bar.trading_day <= own_through
                        and since <= bar.trading_day <= through
                    ):
                        continue
                    status = (
                        "WARMING" if ordinal < 34
                        else "INDICATOR_READY_CROSS_UNEVALUABLE" if ordinal == 34
                        else "CROSS_EVALUATED"
                    )
                    coverage_events.append({
                        "since": bar.trading_day,
                        "through": bar.trading_day,
                        "status": status,
                        "physical_contract": owner.contract,
                        "segment_id": owner_segment_id,
                        "calculation_segment_id": segment.calculation_segment_id,
                    })
                    canonical = canonical_by_end[bar.bar_end]
                    chart_bars.append({
                        **canonical.as_record(),
                        "physical_contract": owner.contract,
                        "segment_id": owner_segment_id,
                        "calculation_segment_id": segment.calculation_segment_id,
                    })
            result.extend(owner_segments)
            inputs.append({
                "contract": owner.contract,
                "segment_id": owner_segment_id,
                "owner_since": owner.start_trading_day,
                "owner_through": own_through,
                "calculation_segments": [
                    {
                        "calculation_segment_id": item.calculation_segment_id,
                        "quality_interrupted_at": item.quality_interrupted_at,
                        "quality_classification": item.quality_classification,
                        "bars": [asdict(bar) for bar in item.bars],
                    }
                    for item in owner_segments
                ],
                "quality_facts": [
                    item.to_record() for item in facts
                ],
            })
        coverage_events.sort(key=lambda item: (item["since"], item["status"]))
        intervals: list[dict[str, Any]] = []
        for event in coverage_events:
            identity = (
                event["status"], event["physical_contract"], event["segment_id"],
                event["calculation_segment_id"],
            )
            if intervals and (
                intervals[-1]["status"],
                intervals[-1]["physical_contract"],
                intervals[-1]["segment_id"],
                intervals[-1]["calculation_segment_id"],
            ) == identity:
                intervals[-1]["through"] = event["through"]
            else:
                intervals.append(dict(event))
        return tuple(result), inputs, {
            "quality_policy_version": D1_QUALITY_POLICY_VERSION,
            "coverage_intervals": intervals,
            "quality_interruptions": interruptions,
            "quality_chart_bars": sorted(chart_bars, key=lambda item: item["bar_end"]),
        }

    def _session_windows(self, symbol: str, trading_day: date):
        try:
            return self.market_data.session_windows(
                symbol=symbol, trading_day=trading_day
            )
        except MarketDataError as exc:
            self._raise_data_unavailable(exc, "session", symbol)

    @staticmethod
    def _raise_data_unavailable(
        exc: MarketDataError, stage: str, symbol: str,
        frequency: BarFrequency = BarFrequency.M15,
    ) -> None:
        reason = getattr(exc, "reason", None) or data_reason(exc.code)
        if reason not in DATA_REASONS:
            raise exc
        raise SubingReferenceError(
            "SUBING_REFERENCE_DATA_UNAVAILABLE",
            diagnostic={
                "stage": stage,
                "reason": reason,
                "context": {
                    "symbol": symbol,
                    "frequency": frequency.value,
                    **getattr(exc, "context", {}),
                },
            },
        ) from exc


def _identity(
    result: MarketSeriesResult, symbol: str, kind: str, contract: str | None,
    frequency: BarFrequency,
) -> None:
    expected = {
        "symbol": symbol,
        "series_kind": kind,
        "contract": contract,
        "frequency": frequency.value,
    }
    if any(
        result.request_identity.get(key) != value for key, value in expected.items()
    ):
        raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")


def _order(result: MarketSeriesResult) -> None:
    if (
        not result.bars
        or any(
            right.bar_end <= left.bar_end
            for left, right in zip(result.bars, result.bars[1:])
        )
        or result.coverage != (result.bars[0].bar_end, result.bars[-1].bar_end)
    ):
        raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")


def _wire(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


def _hash(value: Any) -> str:
    return sha256(
        json.dumps(
            _wire(value), sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


_DIAGNOSTIC_STAGES = frozenset(
    {"calendar", "session", "actual_dominant_replay", "physical_contract_replay"}
)


def _diagnostic(value: Mapping[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None
    stage = value.get("stage")
    reason = value.get("reason")
    if stage not in _DIAGNOSTIC_STAGES or reason not in DATA_REASONS:
        return None
    context = value.get("context")
    return {
        "stage": stage,
        "reason": reason,
        "context": safe_context(context if isinstance(context, Mapping) else None),
    }
