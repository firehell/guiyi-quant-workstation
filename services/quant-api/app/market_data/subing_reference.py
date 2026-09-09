"""Read-only SuBing historical reference, using the existing MarketDataService authority."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from guiyi_quant.subing_reference import (
    FORMULA_VERSION,
    REFERENCE_MODEL_VERSION,
    ReferenceBar,
    ReferenceSegment,
    ReferenceProjectionError,
    project_reference,
)
from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import (
    BarFrequency,
    ContractTradingDayQuery,
    MarketSeriesResult,
)
from app.market_data.market_data_service import MarketDataService

SHANGHAI = ZoneInfo("Asia/Shanghai")


class SubingReferenceError(ValueError):
    def __init__(self, code: str):
        self.code = code
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

    def query(self, query: SubingReferenceQuery) -> dict[str, Any]:
        self.check_cancelled()
        now = self.now()
        as_of = query.as_of or now
        self._validate_query(query, as_of, now)
        since, through, cutoff = self._window(query, as_of)
        self.check_cancelled()
        segments, inputs = self._inputs(query.symbol, since, through, cutoff)
        self.check_cancelled()
        try:
            projection = project_reference(
                query.symbol, segments, since=since, through=through, as_of=cutoff
            )
        except ReferenceProjectionError as exc:
            raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT") from exc
        self.check_cancelled()
        fingerprint = _hash(
            {
                "symbol": query.symbol,
                "frequency": "15m",
                "formula_version": FORMULA_VERSION,
                "reference_model_version": REFERENCE_MODEL_VERSION,
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
        return _wire(
            {
                "symbol": query.symbol,
                "frequency": "15m",
                "series_kind": "actual_dominant",
                "formula_version": FORMULA_VERSION,
                "reference_model_version": REFERENCE_MODEL_VERSION,
                "as_of": as_of,
                "performance_since": since,
                "performance_through": through,
                "reference_cutoff": cutoff,
                "input_snapshot_hash": fingerprint,
                "executable": False,
                "auto_order": False,
                "source": "historical_replay",
                "summary": asdict(projection.summary),
                "signals": [asdict(item) for item in projection.signals],
                "items": [asdict(item) for item in items],
                "next_before": next_before,
            }
        )

    def _validate_query(
        self, query: SubingReferenceQuery, as_of: datetime, now: datetime
    ) -> None:
        if (
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
                and (not isinstance(query.before, str) or len(query.before) > 129)
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
                    for window in self.market_data.session_windows(
                        symbol=query.symbol, trading_day=query.through
                    )
                ),
            )
        days = self.market_data.completed_trading_days(
            symbol=query.symbol,
            start=datetime.combine(start - timedelta(days=1), time.min, SHANGHAI),
            as_of=calendar_as_of,
            latest=query.through or latest,
            calendar_since=start,
        )
        days = tuple(day for day in days if day >= start)
        if not days or tuple(sorted(set(days))) != days:
            raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
        # Calendar/session facts select the window, never whichever dataset exists.
        through = query.through or days[-1]
        if through != days[-1]:
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
        since = query.since or days[max(0, len(days) - 20)]
        if since > through:
            raise SubingReferenceError("SUBING_REFERENCE_INVALID_QUERY")
        sessions = self.market_data.session_windows(
            symbol=query.symbol, trading_day=through
        )
        cutoff = max(window.end for window in sessions)
        if cutoff > as_of:
            raise SubingReferenceError("SUBING_REFERENCE_DATA_CONFLICT")
        return since, through, cutoff

    def _inputs(
        self, symbol: str, since: date, through: date, cutoff: datetime
    ) -> tuple[tuple[ReferenceSegment, ...], list[dict[str, Any]]]:
        loaded = ActualDominantResearchSegmentLoader(self.market_data).load(
            symbol=symbol,
            frequencies=(BarFrequency.M15,),
            since=since,
            through=through,
        )
        actual = loaded.results[BarFrequency.M15]
        _identity(actual, symbol, "actual_dominant", None)
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
                for window in self.market_data.session_windows(
                    symbol=symbol, trading_day=own_last_day
                )
            )
            if end > cutoff or own_bars[-1].bar_end != end:
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            expected = self.market_data.expected_contract_replay_endpoints(
                symbol=symbol,
                contract=owner.contract,
                frequency=BarFrequency.M15,
                trading_day=own_last_day,
                cutoff=end,
                after=None,
            )
            if not expected or expected[-1] != (end, own_last_day):
                raise SubingReferenceError("SUBING_REFERENCE_DATA_UNAVAILABLE")
            self.check_cancelled()
            physical = self.market_data.query_contract_trading_days(
                ContractTradingDayQuery(
                    symbol,
                    owner.contract,
                    BarFrequency.M15,
                    expected[0][1],
                    own_last_day,
                )
            )
            _identity(physical, symbol, "contract", owner.contract)
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
                    for window in self.market_data.session_windows(
                        symbol=symbol, trading_day=next_owner.start_trading_day
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
        return tuple(result), inputs


def _identity(
    result: MarketSeriesResult, symbol: str, kind: str, contract: str | None
) -> None:
    expected = {
        "symbol": symbol,
        "series_kind": kind,
        "contract": contract,
        "frequency": "15m",
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
