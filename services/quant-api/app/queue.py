"""Redis 连接工厂，供 RQ 健康探测与（历史）队列基础设施复用。

当前无活跃业务队列；``RUNTIME_QUEUE_NAMES`` 为空时 RQ 健康仅报告 worker 列表。
"""

from __future__ import annotations

import os

from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")


def get_redis_connection() -> Redis:
    """根据 REDIS_URL 创建 Redis 客户端（每次调用新建连接实例）。"""
    return Redis.from_url(REDIS_URL)
