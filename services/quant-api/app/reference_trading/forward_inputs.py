"""Typed completed Live observation capture through MarketReadService."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from hashlib import sha256
import json

from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery
from app.market_data.market_read_service import MarketReadService
from app.reference_trading.capture import ForwardCapture
from guiyi_quant.reference_trading import StreamIdentity
from guiyi_quant.reference_trading.htdy import CONTEXT_BARS
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import InputQualityPolicy


class ForwardInputUnavailable(RuntimeError):
    def __init__(
        self, code: str, *, trading_day: date | None = None,
        endpoints: tuple[datetime, ...] = (),
    ):
        super().__init__(code)
        self.trading_day = trading_day
        self.endpoints = endpoints


def _bar_wire(bar) -> dict[str, object]:
    return {
        "bar_end": bar.bar_end.isoformat(), "trading_day": bar.trading_day.isoformat(),
        "open": str(bar.open), "high": str(bar.high), "low": str(bar.low),
        "close": str(bar.close), "volume": str(bar.volume),
        "turnover": None if bar.turnover is None else str(bar.turnover),
        "open_interest": None if bar.open_interest is None else str(bar.open_interest),
    }


def capture_htdy_live(
    market_read: MarketReadService, identity: StreamIdentity, *,
    revision_id: str, generation: int, after: datetime | None,
    now: datetime, wake_kind: str, event_bar_end: datetime | None = None,
    owner_segments: Callable[[str, datetime], tuple[str, str]],
) -> ForwardCapture | None:
    """Capture one genuine live wake; scanning a missed Bar never invents first_seen."""
    if identity.strategy_code != "htdy" or wake_kind not in {"live_event", "scan"}:
        raise ValueError("FORWARD_INPUT_IDENTITY_INVALID")
    query = SeriesPageQuery(
        SeriesKind.ACTUAL_DOMINANT, identity.product.upper(),
        BarFrequency(identity.frequency), limit=CONTEXT_BARS,
    )
    snapshot = market_read.observation_snapshot(query, after, now)
    if snapshot.source == "unavailable":
        raise ForwardInputUnavailable("LIVE_SOURCE_UNAVAILABLE")
    if snapshot.source == "none" or not snapshot.bars:
        return None
    if snapshot.source != "realtime":
        raise ForwardInputUnavailable("LIVE_SOURCE_UNAVAILABLE")
    if wake_kind != "live_event" or len(snapshot.bars) != 1:
        raise ForwardInputUnavailable(
            "FIRST_SEEN_NOT_PROVEN", trading_day=snapshot.trading_day,
            endpoints=tuple(bar.bar_end for bar in snapshot.bars),
        )
    latest = snapshot.bars[0]
    if wake_kind == "live_event" and latest.bar_end != event_bar_end:
        raise ForwardInputUnavailable(
            "LIVE_EVENT_IDENTITY_CONFLICT", trading_day=latest.trading_day,
        )
    window = market_read.bars_until(
        query, trading_day=latest.trading_day, end=latest.bar_end,
        limit=CONTEXT_BARS,
    )
    if (
        len(window.bars) != CONTEXT_BARS
        or not window.notification_eligible
        or window.contract != snapshot.contract
        or window.cutoff != latest.bar_end
        or window.bars[-1] != latest
    ):
        raise ForwardInputUnavailable("HTDY_WINDOW_UNAVAILABLE")
    market_read.validate_alert_window(window, context_bars=CONTEXT_BARS)
    owner_id, calculation_id = owner_segments(window.contract, latest.bar_end)
    if not owner_id or not calculation_id:
        raise ForwardInputUnavailable("OWNER_UNAVAILABLE")
    bars = [_bar_wire(bar) for bar in window.bars]
    window_hash = sha256(json.dumps(bars, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ForwardCapture(
        stream_id=identity.stream_id, revision_id=revision_id, generation=generation,
        source_key=f"{window.contract}:{latest.bar_end.isoformat()}",
        bar_end=latest.bar_end, observed_at=now, source_kind="completed_live",
        input_payload={"bars": bars, "bar_contracts": list(window.bar_contracts),
                       "contract": window.contract,
                       "trading_day": latest.trading_day.isoformat()},
        source_proof={"window_sha256": window_hash, "owner_segment_id": owner_id,
                      "calculation_segment_id": calculation_id,
                      "source": snapshot.source, "frequency": identity.frequency,
                      "event_bar_end": latest.bar_end.isoformat()},
        eligibility="first_seen",
    )


def capture_subing_live(
    market_read: MarketReadService, identity: StreamIdentity, *,
    revision_id: str, generation: int, after: datetime | None,
    now: datetime, wake_kind: str, event_bar_end: datetime | None = None,
    owner_segments: Callable[[str, datetime], tuple[str, str]],
    expected_endpoints: Callable[[str, datetime | None, datetime], tuple[datetime, ...]],
) -> ForwardCapture | None:
    """Capture one completed SuBing Bar only when Session continuity is proven."""
    if identity.strategy_code.replace("-", "_") != "subing_reference" or identity.frequency not in {"15m", "30m", "60m"}:
        raise ValueError("FORWARD_INPUT_IDENTITY_INVALID")
    if wake_kind not in {"live_event", "scan"}:
        raise ValueError("FORWARD_INPUT_WAKE_INVALID")
    query = SeriesPageQuery(
        SeriesKind.ACTUAL_DOMINANT, identity.product.upper(),
        BarFrequency(identity.frequency), limit=2,
    )
    snapshot = market_read.observation_snapshot(query, after, now)
    if snapshot.source == "unavailable":
        raise ForwardInputUnavailable("LIVE_SOURCE_UNAVAILABLE")
    if snapshot.source == "none" or not snapshot.bars:
        return None
    if snapshot.source != "realtime" or not snapshot.contract:
        raise ForwardInputUnavailable("LIVE_SOURCE_UNAVAILABLE")
    if len(snapshot.bars) != 1:
        raise ForwardInputUnavailable(
            "OBSERVATION_GAP", trading_day=snapshot.trading_day,
            endpoints=tuple(item.bar_end for item in snapshot.bars),
        )
    bar = snapshot.bars[0]
    if wake_kind == "live_event" and bar.bar_end != event_bar_end:
        raise ForwardInputUnavailable("LIVE_EVENT_IDENTITY_CONFLICT")
    endpoints = expected_endpoints(snapshot.contract, after, bar.bar_end)
    if endpoints != (bar.bar_end,):
        raise ForwardInputUnavailable(
            "OBSERVATION_GAP", trading_day=bar.trading_day,
            endpoints=endpoints,
        )
    owner_id, calculation_id = owner_segments(snapshot.contract, bar.bar_end)
    if not owner_id or not calculation_id:
        raise ForwardInputUnavailable("OWNER_UNAVAILABLE")
    wire = _bar_wire(bar)
    source_hash = sha256(json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ForwardCapture(
        stream_id=identity.stream_id, revision_id=revision_id, generation=generation,
        source_key=f"{snapshot.contract}:{bar.bar_end.isoformat()}",
        bar_end=bar.bar_end, observed_at=now, source_kind="completed_live",
        input_payload={"bar": wire, "contract": snapshot.contract},
        source_proof={
            "source_sha256": source_hash, "owner_segment_id": owner_id,
            "calculation_segment_id": calculation_id,
            "previous_watermark": None if after is None else after.isoformat(),
            "expected_endpoints": [item.isoformat() for item in endpoints],
            "frequency": identity.frequency, "source": snapshot.source,
        },
        eligibility="completed_live",
    )


def _newow_strategy(identity: StreamIdentity) -> ProductStrategy:
    code = identity.strategy_code.replace("-", "_")
    if not code.startswith("newow_"):
        raise ValueError("FORWARD_INPUT_IDENTITY_INVALID")
    return ProductStrategy(code.removeprefix("newow_"))


def _newow_capture(
    identity: StreamIdentity, *, revision_id: str, generation: int,
    now: datetime, after: datetime | None, bar: dict[str, object],
    contract: str, owner_id: str, calculation_id: str,
    source_kind: str, source_identity: str, source_bar_sha256: str,
    input_quality_policy: InputQualityPolicy,
) -> ForwardCapture:
    end = datetime.fromisoformat(str(bar["bar_end"]))
    if (
        end.tzinfo is None or now.tzinfo is None or end > now
        or after is not None and end <= after
        or not contract or not owner_id or not calculation_id
        or not source_identity or len(source_bar_sha256) != 64
    ):
        raise ForwardInputUnavailable("NEWOW_SOURCE_IDENTITY_INVALID")
    source_hash = sha256(json.dumps(bar, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ForwardCapture(
        stream_id=identity.stream_id, revision_id=revision_id, generation=generation,
        source_key=f"{contract}:{end.isoformat()}", bar_end=end,
        observed_at=now, source_kind=source_kind,
        input_payload={
            "bar": bar, "contract": contract, "product": identity.product,
            "source_identity": source_identity,
            "source_bar_sha256": source_bar_sha256,
            "input_quality_policy": input_quality_policy.value,
        },
        source_proof={
            "source_sha256": source_hash, "owner_segment_id": owner_id,
            "calculation_segment_id": calculation_id,
            "previous_watermark": None if after is None else after.isoformat(),
            "expected_endpoints": [end.isoformat()],
            "frequency": identity.frequency, "source": source_kind,
        }, eligibility="completed_observation",
    )


def capture_newow_live(
    market_read: MarketReadService, identity: StreamIdentity, *,
    revision_id: str, generation: int, after: datetime | None,
    now: datetime, wake_kind: str, event_bar_end: datetime | None = None,
    owner_segments: Callable[[str, datetime], tuple[str, str]],
    expected_endpoints: Callable[[str, datetime | None, datetime], tuple[datetime, ...]],
    capability_ready: Callable[[StreamIdentity], bool],
) -> ForwardCapture | None:
    """Capture one 60m completed Live Bar without opening the product capability."""
    _newow_strategy(identity)
    if identity.frequency != ProductFrequency.HOURLY.value or wake_kind not in {"live_event", "scan"}:
        raise ValueError("FORWARD_INPUT_IDENTITY_INVALID")
    if not capability_ready(identity):
        raise ForwardInputUnavailable("NEWOW_CAPABILITY_CLOSED")
    query = SeriesPageQuery(
        SeriesKind.ACTUAL_DOMINANT, identity.product.upper(), BarFrequency.H1,
        limit=2,
    )
    snapshot = market_read.observation_snapshot(query, after, now)
    if snapshot.source == "unavailable":
        raise ForwardInputUnavailable("LIVE_SOURCE_UNAVAILABLE")
    if snapshot.source == "none" or not snapshot.bars:
        return None
    if snapshot.source != "realtime" or not snapshot.contract:
        raise ForwardInputUnavailable("LIVE_SOURCE_UNAVAILABLE")
    if len(snapshot.bars) != 1:
        raise ForwardInputUnavailable(
            "OBSERVATION_GAP", trading_day=snapshot.trading_day,
            endpoints=tuple(item.bar_end for item in snapshot.bars),
        )
    bar = snapshot.bars[0]
    if wake_kind == "live_event" and bar.bar_end != event_bar_end:
        raise ForwardInputUnavailable("LIVE_EVENT_IDENTITY_CONFLICT")
    endpoints = expected_endpoints(snapshot.contract, after, bar.bar_end)
    if endpoints != (bar.bar_end,):
        raise ForwardInputUnavailable(
            "OBSERVATION_GAP", trading_day=bar.trading_day,
            endpoints=endpoints or (bar.bar_end,),
        )
    owner_id, calculation_id = owner_segments(snapshot.contract, bar.bar_end)
    wire = _bar_wire(bar)
    source_bar_sha = sha256(json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return _newow_capture(
        identity, revision_id=revision_id, generation=generation, now=now,
        after=after, bar=wire, contract=snapshot.contract, owner_id=owner_id,
        calculation_id=calculation_id, source_kind="completed_live",
        source_identity="market_read_service:completed_live:v1",
        source_bar_sha256=source_bar_sha,
        input_quality_policy=InputQualityPolicy.V1,
    )


def capture_newow_canonical(
    reader, identity: StreamIdentity, *,
    revision_id: str, generation: int, after: datetime | None,
    recording_start: datetime, now: datetime,
    capability_ready: Callable[[StreamIdentity], bool],
) -> ForwardCapture | None:
    """Capture only a newly available authoritative completed D1/W1 input."""
    from app.market_data.newow.product_query import NewowProductQuery

    strategy = _newow_strategy(identity)
    if identity.frequency not in {ProductFrequency.DAILY.value, ProductFrequency.WEEKLY.value}:
        raise ValueError("FORWARD_INPUT_IDENTITY_INVALID")
    if not capability_ready(identity):
        raise ForwardInputUnavailable("NEWOW_CAPABILITY_CLOSED")
    if recording_start.tzinfo is None or now.tzinfo is None or recording_start > now:
        raise ValueError("FORWARD_INPUT_TIME_INVALID")
    frequency = ProductFrequency(identity.frequency)
    start_day = recording_start.date()
    query = NewowProductQuery(
        identity.product, strategy, frequency, start_day, now.date(),
        performance_since=start_day, performance_through=now.date(), as_of=now,
    )
    read = reader.load(query, now)
    if read.frequency is not frequency or read.as_of != now:
        raise ForwardInputUnavailable("NEWOW_SOURCE_IDENTITY_INVALID")
    boundary = after if after is not None else recording_start
    if any(
        gap.effective_at >= boundary
        for gap in read.data_interruptions_by_frequency.get(frequency, ())
    ):
        raise ForwardInputUnavailable("DATA_INTERRUPTED")
    unseen = tuple(item for item in read.replay_bars if (
        item.bar.bar_end > after if after is not None
        else item.bar.bar_end >= recording_start
    ) and item.bar.observation_eligible)
    if not unseen:
        return None
    if len(unseen) != 1:
        raise ForwardInputUnavailable(
            "OBSERVATION_GAP", trading_day=unseen[-1].bar.trading_day,
            endpoints=tuple(item.bar.bar_end for item in unseen),
        )
    item = unseen[0]
    source = read.sources.get(frequency)
    if (
        source is None or not item.bar.source_identity.startswith(source.source_identity + ":")
        or item.frequency is not frequency or not item.source_bar_sha256
        or item.bar.bar_end > now or not item.bar.completed
    ):
        raise ForwardInputUnavailable("NEWOW_SOURCE_IDENTITY_INVALID")
    wire = {
        "bar_end": item.bar.bar_end.isoformat(),
        "trading_day": item.bar.trading_day.isoformat(),
        "open": str(item.bar.open), "high": str(item.bar.high),
        "low": str(item.bar.low), "close": str(item.bar.close),
        "volume": str(item.bar.volume),
        "open_interest": None if item.bar.open_interest is None else str(item.bar.open_interest),
    }
    return _newow_capture(
        identity, revision_id=revision_id, generation=generation, now=now,
        after=after, bar=wire, contract=item.bar.physical_contract,
        owner_id=item.bar.segment_id,
        calculation_id=item.calculation_segment_id,
        source_kind="canonical_completed", source_identity=item.bar.source_identity,
        source_bar_sha256=item.source_bar_sha256,
        input_quality_policy=read.input_quality_policy,
    )
