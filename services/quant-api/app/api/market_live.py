"""Market Web 的状态与实时 WebSocket 路由。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import build_market_read_service
from app.market_data.domain import BarFrequency, CanonicalBar, ContractError, SeriesKind, SeriesPageQuery
from app.market_data.live_market import LIVE_STATE_CHANNEL, live_bar_channel
from app.market_data.market_read import MarketReadState
from app.queue import get_async_redis_connection
from app.schemas.market import MarketReadStateResponse


router = APIRouter(prefix="/api/v1/market", tags=["market"])


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
async def market_websocket(
    websocket: WebSocket,
    session: Session = Depends(get_db),
) -> None:
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

    read_service = build_market_read_service(session)
    initial_state = read_service.state(identity, datetime.now(UTC))
    redis = get_async_redis_connection()
    pubsub = redis.pubsub()
    channels = (live_bar_channel(identity.symbol, identity.frequency), LIVE_STATE_CHANNEL)
    try:
        await pubsub.subscribe(*channels)
        await websocket.accept()
        await _send_state(websocket, initial_state)

        cutoff = _later(after, initial_state.canonical_end)
        snapshot = read_service.live_snapshot(identity, cutoff, datetime.now(UTC))
        snapshot = _newer_bars(snapshot, canonical_end=initial_state.canonical_end, after=cutoff)
        await websocket.send_json(
            {
                "type": "snapshot",
                "bars": [_bar_response(bar) for bar in snapshot],
            }
        )
        last_sent = snapshot[-1].bar_end if snapshot else cutoff
        current_state = initial_state

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                await asyncio.sleep(0.01)
                continue
            channel = _text(message.get("channel"))
            if channel == LIVE_STATE_CHANNEL:
                next_state = read_service.state(identity, datetime.now(UTC))
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
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()
        await redis.aclose()


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
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(field="after", reason="rfc3339_required") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(field="after", reason="timezone_required")
    return parsed.astimezone(UTC)


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
