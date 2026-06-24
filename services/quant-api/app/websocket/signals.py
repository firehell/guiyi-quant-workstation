from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis import asyncio as aioredis
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.signal import StrategySignal
from app.queue import REDIS_URL
from app.services.signal_scanner import signal_payload

router = APIRouter(tags=["signal-websocket"])


@router.websocket("/ws/signals")
async def watch_signals(websocket: WebSocket) -> None:
    await websocket.accept()
    await _send_latest_snapshot(websocket)
    redis = aioredis.from_url(REDIS_URL)
    pubsub = redis.pubsub()
    await pubsub.subscribe("signals")
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("data"):
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await websocket.send_text(data)
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        return
    finally:
        await pubsub.unsubscribe("signals")
        await pubsub.close()
        await redis.aclose()


async def _send_latest_snapshot(websocket: WebSocket) -> None:
    with SessionLocal() as session:
        rows = session.scalars(select(StrategySignal).where(StrategySignal.is_active.is_(True)).order_by(StrategySignal.signal_time.desc()).limit(20))
        await websocket.send_text(
            json.dumps({"type": "snapshot", "data": [signal_payload(row) for row in rows]}, ensure_ascii=False, default=str)
        )
