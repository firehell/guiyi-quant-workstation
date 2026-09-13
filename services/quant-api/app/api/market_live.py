"""Market Web 的状态与实时 WebSocket 路由。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

import anyio
from datetime import UTC, datetime
import json
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import (
    build_market_read_service,
    open_market_home_live_service,
    open_market_read_service,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ContractError,
    SeriesKind,
    SeriesPageQuery,
    parse_rfc3339_instant,
)
from app.market_data.live_market import LIVE_STATE_CHANNEL, live_bar_channel
from app.market_data.market_home_live import MarketHomeLiveItem, MarketHomeLiveSnapshot
from app.market_data.market_read_service import MarketReadService, MarketReadState
from app.market_data.operational_universe import load_operational_products
from app.redis_connections import get_async_redis_connection
from app.schemas.market import MarketReadStateResponse
from app.schemas.market_home_live import (
    MarketHomeLiveItemResponse,
    MarketHomeLiveQuoteFrame,
    MarketHomeLiveResetFrame,
    MarketHomeLiveSnapshotFrame,
    MarketHomeLiveUnavailableFrame,
)


router = APIRouter(prefix="/api/v1/market", tags=["market"])
# Admission precedes submit: no unbounded executor queue, including cancellation.
_READ_SLOTS = BoundedSemaphore(4)
_READ_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="market-ws-read")
_HOME_LIVE_STATUS_REFRESH_SECONDS = 5.0
_HOME_LIVE_AUTHORITY_REFRESH_SECONDS = 60.0


@router.get("/state", response_model=MarketReadStateResponse)
def market_state(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    contract: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MarketReadStateResponse:
    """读取图表状态；Live Redis 不可用时由 read service 降级为 historical-only。"""
    try:
        identity = _identity(series_kind, symbol, frequency, contract)
        state = build_market_read_service(session).state(identity, datetime.now(UTC))
    except ContractError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "facts": dict(exc.facts)}) from exc
    return _state_response(state)


@router.websocket("/ws")
async def market_websocket(websocket: WebSocket) -> None:
    """先订阅 Pub/Sub、再读快照，杜绝 REST 到 WebSocket 的 Live bar 空窗。"""
    try:
        identity = _identity(
            websocket.query_params.get("series_kind", ""),
            websocket.query_params.get("symbol", ""),
            websocket.query_params.get("frequency", ""),
            websocket.query_params.get("contract"),
        )
        after = _after(websocket.query_params.get("after"))
    except ContractError:
        await websocket.close(code=1008, reason="MARKET_DATA_CONTRACT_INVALID")
        return

    redis = get_async_redis_connection()
    pubsub = redis.pubsub()
    channels = (live_bar_channel(identity.symbol, identity.frequency), LIVE_STATE_CHANNEL)
    try:
        await pubsub.subscribe(*channels)
        display = await _read_in_worker(
            lambda service: service.display_snapshot(identity, after, datetime.now(UTC)),
        )
        initial_state = display.state
        await websocket.accept()
        await _send_state(websocket, initial_state)

        cutoff = _later(after, initial_state.canonical_end)
        snapshot = _newer_bars(
            display.bars,
            canonical_end=initial_state.canonical_end,
            after=cutoff,
        )
        await websocket.send_json(
            {
                "type": "snapshot",
                "source": display.source,
                "trading_day": (
                    None
                    if display.trading_day is None
                    else display.trading_day.isoformat()
                ),
                "contract": display.contract,
                "bars": [_bar_response(bar) for bar in snapshot],
            }
        )
        last_sent = snapshot[-1].bar_end if snapshot else cutoff
        current_state = initial_state

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                if await _client_disconnected(websocket):
                    break
                await asyncio.sleep(0.01)
                continue
            channel = _text(message.get("channel"))
            if channel == LIVE_STATE_CHANNEL:
                next_state = await _read_in_worker(
                    lambda service: service.state(identity, datetime.now(UTC)),
                )
                if (
                    next_state.trading_day != current_state.trading_day
                    or next_state.live_contract != current_state.live_contract
                ):
                    await websocket.send_json(
                        {
                            "type": "reset",
                            "trading_day": (
                                None
                                if next_state.trading_day is None
                                else next_state.trading_day.isoformat()
                            ),
                            "contract": next_state.live_contract,
                        }
                    )
                    last_sent = next_state.canonical_end
                current_state = next_state
                await _send_state(websocket, next_state)
                continue
            if channel != channels[0]:
                continue
            bar = _bar_from_message(message.get("data"))
            if not current_state.live_eligible or not current_state.live_available:
                continue
            if bar is None or (current_state.canonical_end is not None and bar.bar_end <= current_state.canonical_end):
                continue
            if last_sent is not None and bar.bar_end <= last_sent:
                continue
            await websocket.send_json({"type": "bar", "bar": _bar_response(bar)})
            last_sent = bar.bar_end
    except Exception:  # noqa: BLE001 - Redis/WebSocket transport failures have no historical fallback here
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close(code=1013, reason="LIVE_UNAVAILABLE")
    finally:
        with anyio.CancelScope(shield=True):
            try:
                await pubsub.unsubscribe(*channels)
            finally:
                try:
                    await pubsub.aclose()
                finally:
                    await redis.aclose()


@router.websocket("/research/home-live/ws")
async def market_home_live_websocket(websocket: WebSocket) -> None:
    """Stream all operational completed-minute quotes through one fixed subscription."""

    redis = None
    pubsub = None
    channels: tuple[str, ...] = ()
    accepted = False
    try:
        if websocket.query_params:
            await websocket.close(code=1008, reason="MARKET_HOME_LIVE_SCOPE_FIXED")
            return
        products = load_operational_products()
        channels = tuple(live_bar_channel(symbol, BarFrequency.M1) for symbol in products) + (
            LIVE_STATE_CHANNEL,
        )
        redis = get_async_redis_connection()
        pubsub = redis.pubsub()
        await pubsub.subscribe(*channels)
        snapshot = await _read_home_live_snapshot()
        current = {item.symbol: item for item in snapshot.items}
        await websocket.accept()
        accepted = True
        await websocket.send_json(
            MarketHomeLiveSnapshotFrame(
                observed_at=_instant(snapshot.observed_at),
                items=[_home_item_response(item) for item in snapshot.items],
            ).model_dump(mode="json")
        )
        status_signature = await _home_live_status_signature(redis)
        loop = asyncio.get_running_loop()
        last_status_check = loop.time()
        last_authority_check = loop.time()

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0,
            )
            now_tick = loop.time()
            if now_tick - last_status_check >= _HOME_LIVE_STATUS_REFRESH_SECONDS:
                next_signature = await _home_live_status_signature(redis)
                if next_signature != status_signature:
                    snapshot, current = await _refresh_home_live(
                        websocket,
                        snapshot,
                        current,
                    )
                status_signature = next_signature
                last_status_check = now_tick
            if now_tick - last_authority_check >= _HOME_LIVE_AUTHORITY_REFRESH_SECONDS:
                snapshot, current = await _refresh_home_live(
                    websocket,
                    snapshot,
                    current,
                )
                last_authority_check = now_tick
            if message is None:
                if await _client_disconnected(websocket):
                    break
                await asyncio.sleep(0.01)
                continue

            channel = _text(message.get("channel"))
            if channel == LIVE_STATE_CHANNEL:
                snapshot, current = await _refresh_home_live(
                    websocket,
                    snapshot,
                    current,
                    force=True,
                )
                status_signature = await _home_live_status_signature(redis)
                last_status_check = now_tick
                last_authority_check = now_tick
                continue
            if not channel.startswith("live:bar:") or not channel.endswith(":1m"):
                continue
            symbol = channel.removeprefix("live:bar:").removesuffix(":1m")
            old_item = current.get(symbol)
            if old_item is None:
                continue
            item = await _read_home_live_item(symbol, old_item)
            if item == old_item:
                continue
            current[symbol] = item
            if _home_item_authority(item) != _home_item_authority(old_item):
                snapshot = MarketHomeLiveSnapshot(_home_live_now(), tuple(current.values()))
                await websocket.send_json(
                    MarketHomeLiveResetFrame(
                        observed_at=_instant(snapshot.observed_at),
                        items=[_home_item_response(value) for value in current.values()],
                    ).model_dump(mode="json")
                )
            elif item.bar_end is not None and (
                old_item.bar_end is None or item.bar_end > old_item.bar_end
            ):
                await websocket.send_json(
                    MarketHomeLiveQuoteFrame(
                        observed_at=_instant(_home_live_now()),
                        item=_home_item_response(item),
                    ).model_dump(mode="json")
                )
    except Exception:  # noqa: BLE001 - transport/read failures have one typed WS boundary
        try:
            if not accepted:
                await websocket.accept()
                accepted = True
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.send_json(
                    MarketHomeLiveUnavailableFrame(
                        observed_at=_instant(_home_live_now())
                    ).model_dump(mode="json")
                )
                await websocket.close(code=1013, reason="MARKET_HOME_LIVE_UNAVAILABLE")
        except Exception:  # noqa: BLE001 - peer may already be gone
            pass
    finally:
        with anyio.CancelScope(shield=True):
            try:
                if pubsub is not None:
                    try:
                        if channels:
                            await pubsub.unsubscribe(*channels)
                    finally:
                        await pubsub.aclose()
            finally:
                if redis is not None:
                    await redis.aclose()


async def _read_in_worker[T](operation: Callable[[MarketReadService], T]) -> T:
    """Keep admission until the actual worker exits, even if its caller cancels."""
    if not _READ_SLOTS.acquire(blocking=False):
        raise RuntimeError("MARKET_READ_BUSY")

    def read() -> T:
        with open_market_read_service() as service:
            return operation(service)

    try:
        future = _READ_EXECUTOR.submit(read)
    except BaseException:
        _READ_SLOTS.release()
        raise
    future.add_done_callback(lambda _: _READ_SLOTS.release())
    return await asyncio.wrap_future(future)


async def _read_home_live_snapshot(
    previous: MarketHomeLiveSnapshot | None = None,
) -> MarketHomeLiveSnapshot:
    if not _READ_SLOTS.acquire(blocking=False):
        raise RuntimeError("MARKET_READ_BUSY")

    def read() -> MarketHomeLiveSnapshot:
        with open_market_home_live_service() as service:
            return service.snapshot(_home_live_now(), previous=previous)

    try:
        future = _READ_EXECUTOR.submit(read)
    except BaseException:
        _READ_SLOTS.release()
        raise
    future.add_done_callback(lambda _: _READ_SLOTS.release())
    return await asyncio.wrap_future(future)


async def _read_home_live_item(
    symbol: str,
    previous: MarketHomeLiveItem,
) -> MarketHomeLiveItem:
    if not _READ_SLOTS.acquire(blocking=False):
        raise RuntimeError("MARKET_READ_BUSY")

    def read() -> MarketHomeLiveItem:
        with open_market_home_live_service() as service:
            return service.refresh_item(
                symbol,
                _home_live_now(),
                previous=previous,
            )

    try:
        future = _READ_EXECUTOR.submit(read)
    except BaseException:
        _READ_SLOTS.release()
        raise
    future.add_done_callback(lambda _: _READ_SLOTS.release())
    return await asyncio.wrap_future(future)


async def _refresh_home_live(
    websocket: WebSocket,
    previous: MarketHomeLiveSnapshot,
    current: dict[str, MarketHomeLiveItem],
    *,
    force: bool = False,
) -> tuple[MarketHomeLiveSnapshot, dict[str, MarketHomeLiveItem]]:
    refreshed = await _read_home_live_snapshot(None if force else previous)
    refreshed_items = {item.symbol: item for item in refreshed.items}
    if tuple(
        _home_item_response(item).model_dump(mode="json")
        for item in refreshed_items.values()
    ) != tuple(
        _home_item_response(item).model_dump(mode="json")
        for item in current.values()
    ):
        await websocket.send_json(
            MarketHomeLiveResetFrame(
                observed_at=_instant(refreshed.observed_at),
                items=[_home_item_response(item) for item in refreshed.items],
            ).model_dump(mode="json")
        )
    return refreshed, refreshed_items


async def _home_live_status_signature(redis: object) -> tuple[object, ...]:
    try:
        raw = await redis.get("live:heartbeat")  # type: ignore[attr-defined]
        payload = json.loads(_text(raw))
        if not isinstance(payload, dict):
            raise ValueError("heartbeat")
        phase_counts = payload.get("phase_counts")
        return (
            payload.get("available"),
            payload.get("operational_count"),
            payload.get("subscribed_count"),
            tuple(sorted(phase_counts.items())) if isinstance(phase_counts, dict) else None,
        )
    except Exception:  # noqa: BLE001 - invalid/absent status triggers bounded refresh
        return ("unavailable",)


def _home_item_authority(item: MarketHomeLiveItem) -> tuple[object, ...]:
    return (
        item.physical_contract,
        item.trading_day,
        item.source,
        item.availability,
        item.phase,
        item.previous_close,
        item.reason,
    )


def _home_item_response(item: MarketHomeLiveItem) -> MarketHomeLiveItemResponse:
    return MarketHomeLiveItemResponse(
        symbol=item.symbol,
        physical_contract=item.physical_contract,
        trading_day=None if item.trading_day is None else item.trading_day.isoformat(),
        bar_end=None if item.bar_end is None else _instant(item.bar_end),
        price=None if item.price is None else str(item.price),
        previous_close=(
            None if item.previous_close is None else str(item.previous_close)
        ),
        price_change=None if item.price_change is None else str(item.price_change),
        source=item.source,
        availability=item.availability,
        phase=item.phase,
        reason=item.reason,
    )


def _home_live_now() -> datetime:
    return datetime.now(UTC)


def _instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _identity(
    series_kind: str,
    symbol: str,
    frequency: str,
    contract: str | None,
) -> SeriesPageQuery:
    return SeriesPageQuery(
        series_kind=cast(SeriesKind, series_kind),
        symbol=symbol,
        contract=contract,
        frequency=cast(BarFrequency, frequency),
        limit=1,
    )


def _state_response(state: MarketReadState) -> MarketReadStateResponse:
    return MarketReadStateResponse(
        symbol=state.symbol,
        series_kind=state.series_kind,
        frequency=state.frequency,
        operational=state.operational,
        phase=state.phase,
        trading_day=state.trading_day,
        live_eligible=state.live_eligible,
        live_available=state.live_available,
        live_contract=state.live_contract,
        canonical_end=state.canonical_end,
        after_market=dict(state.after_market),
    )


async def _send_state(websocket: WebSocket, state: MarketReadState) -> None:
    await websocket.send_json({"type": "state", "state": _state_response(state).model_dump(mode="json")})


async def _client_disconnected(websocket: WebSocket) -> bool:
    """在 Pub/Sub 空轮询时探测客户端断连，避免遗留每连接的 Redis subscription。"""
    try:
        message = await asyncio.wait_for(websocket.receive(), timeout=0.01)
    except TimeoutError:
        return False
    return message.get("type") == "websocket.disconnect"


def _bar_response(bar: CanonicalBar) -> dict[str, object]:
    return {
        "bar_end": bar.bar_end.isoformat().replace("+00:00", "Z"),
        "trading_day": bar.trading_day.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "turnover": None if bar.turnover is None else str(bar.turnover),
        "open_interest": None if bar.open_interest is None else str(bar.open_interest),
    }


def _after(value: str | None) -> datetime | None:
    if value is None:
        return None
    return parse_rfc3339_instant(value, field="after")


def _later(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _newer_bars(
    bars: tuple[CanonicalBar, ...],
    *,
    canonical_end: datetime | None,
    after: datetime | None,
) -> tuple[CanonicalBar, ...]:
    deduped = {
        bar.bar_end: bar
        for bar in bars
        if (canonical_end is None or bar.bar_end > canonical_end)
        and (after is None or bar.bar_end > after)
    }
    return tuple(deduped[key] for key in sorted(deduped))


def _bar_from_message(value: object) -> CanonicalBar | None:
    try:
        payload = json.loads(_text(value))
        if not isinstance(payload, dict):
            return None
        return CanonicalBar(
            bar_end=datetime.fromisoformat(str(payload["bar_end"])),
            trading_day=datetime.fromisoformat(str(payload["trading_day"])).date(),
            open=payload["open"],
            high=payload["high"],
            low=payload["low"],
            close=payload["close"],
            volume=payload["volume"],
            turnover=payload.get("turnover"),
            open_interest=payload.get("open_interest"),
        )
    except (ContractError, KeyError, TypeError, ValueError):
        return None


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return value if isinstance(value, str) else ""
