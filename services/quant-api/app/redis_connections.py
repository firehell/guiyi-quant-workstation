"""Market Runtime 使用的同步/异步 Redis 连接工厂。"""

from __future__ import annotations

import os

from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")


def get_redis_connection() -> Redis:
    """根据 REDIS_URL 创建 Redis 客户端（每次调用新建连接实例）。"""
    return Redis.from_url(REDIS_URL)


def get_async_redis_connection():
    """为 WebSocket 路径新建异步 Redis 客户端。"""
    from redis.asyncio import Redis as AsyncRedis

    return AsyncRedis.from_url(REDIS_URL, decode_responses=True)
