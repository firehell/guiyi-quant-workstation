from __future__ import annotations

import os

from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")


def get_redis_connection() -> Redis:
    return Redis.from_url(REDIS_URL)
