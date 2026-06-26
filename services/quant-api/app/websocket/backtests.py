from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis import asyncio as aioredis
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.backtest import BacktestTask
from app.queue import REDIS_URL
from app.services.batch_backtest import task_snapshot

router = APIRouter(tags=["backtest-websocket"])


@router.websocket("/ws/backtests/{task_no}")
async def watch_backtest_task(websocket: WebSocket, task_no: str) -> None:
    await websocket.accept()
    await _send_current_snapshot(websocket, task_no)

    redis = aioredis.from_url(REDIS_URL)
    pubsub = redis.pubsub()
    channel = f"backtests:{task_no}"
    await pubsub.subscribe(channel)
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
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis.aclose()


async def _send_current_snapshot(websocket: WebSocket, task_no: str) -> None:
    with SessionLocal() as session:
        task = session.scalar(select(BacktestTask).where(BacktestTask.task_no == task_no))
        if task is None:
            await websocket.send_text(json.dumps({"type": "not_found", "data": {"task_no": task_no}}, ensure_ascii=False))
            return
        await websocket.send_text(json.dumps({"type": "snapshot", "data": task_snapshot(task)}, ensure_ascii=False))
