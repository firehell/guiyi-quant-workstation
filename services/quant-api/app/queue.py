from __future__ import annotations

import os

from redis import Redis
from rq import Queue

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
BACKTEST_QUEUE_NAME = "guiyi-backtests"
SIGNAL_QUEUE_NAME = "guiyi-signals"
NOTIFICATION_QUEUE_NAME = "guiyi-notifications"


def get_redis_connection() -> Redis:
    return Redis.from_url(REDIS_URL)


def get_backtest_queue() -> Queue:
    return Queue(BACKTEST_QUEUE_NAME, connection=get_redis_connection())


def get_signal_queue() -> Queue:
    return Queue(SIGNAL_QUEUE_NAME, connection=get_redis_connection())


def get_notification_queue() -> Queue:
    return Queue(NOTIFICATION_QUEUE_NAME, connection=get_redis_connection())
