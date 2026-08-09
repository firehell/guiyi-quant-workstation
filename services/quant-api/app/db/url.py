"""数据库连接 URL 规范化工具。"""

from __future__ import annotations


def normalize_database_url(url: str) -> str:
    """将通用 PostgreSQL URL 转为 SQLAlchemy psycopg v3 驱动格式。

    ``postgresql://`` 与 ``postgres://`` 前缀统一替换为 ``postgresql+psycopg://``，
    避免默认回落到 psycopg2。
    """
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url
