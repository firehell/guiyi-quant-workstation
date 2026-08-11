"""Alembic/迁移测试用数据库隔离安全校验。

防止迁移测试误连生产或运行时 DATABASE_URL 指向的同一 PostgreSQL 数据库（OID 级
比对）。不满足隔离条件时 fail-closed 抛出 ``MigrationTestDatabaseSafetyError``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


class MigrationTestDatabaseSafetyError(RuntimeError):
    """迁移测试目标库未通过隔离校验时抛出。"""

    pass


@dataclass(frozen=True)
class DatabaseIdentity:
    """PostgreSQL 数据库逻辑名与 OID，用于跨 URL 比对是否同一物理库。"""

    database: str
    oid: int


def probe_database_identity(database_url: str) -> DatabaseIdentity:
    """连接目标 URL 并查询 current_database() 与 pg_database.oid。"""
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT current_database(), oid
                    FROM pg_database
                    WHERE datname = current_database()
                    """
                )
            ).one()
        return DatabaseIdentity(database=str(row[0]), oid=int(row[1]))
    finally:
        engine.dispose()


def _is_isolated_name(database: str) -> bool:
    """库名须包含 test 或 isolated 子串，作为命名层隔离启发式。"""
    lowered = database.lower()
    return "test" in lowered or "isolated" in lowered


def require_isolated_migration_database_url(
    environment: Mapping[str, str],
    *,
    identity_probe: Callable[[str], DatabaseIdentity],
) -> str:
    """校验并返回 GUIYI_ISOLATED_MIGRATION_DATABASE_URL。

    校验链（任一失败即 fail-closed）：
    1. 环境变量必须存在且为 PostgreSQL；
    2. 库名须为 isolated/test；
    3. 不得与 DATABASE_URL 字符串相同；
    4. 实际连接后的库名仍须为 isolated/test；
    5. OID 与 DATABASE_URL 指向库不得相同（防别名/重定向误连生产）。
    """
    target_url = environment.get("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip()
    if not target_url:
        raise MigrationTestDatabaseSafetyError(
            "GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required"
        )

    parsed_target = make_url(target_url)
    if not parsed_target.drivername.startswith("postgresql"):
        raise MigrationTestDatabaseSafetyError(
            "GUIYI_ISOLATED_MIGRATION_DATABASE_URL must use PostgreSQL"
        )
    target_name = parsed_target.database or ""
    if not _is_isolated_name(target_name):
        raise MigrationTestDatabaseSafetyError(
            "GUIYI_ISOLATED_MIGRATION_DATABASE_URL must name an isolated/test database"
        )

    runtime_url = environment.get("DATABASE_URL", "").strip()
    # URL 字符串级比对：禁止与运行时库配置完全相同
    if runtime_url and make_url(runtime_url) == parsed_target:
        raise MigrationTestDatabaseSafetyError(
            "isolated migration URL must not equal DATABASE_URL"
        )

    target_identity = identity_probe(target_url)
    if not _is_isolated_name(target_identity.database):
        raise MigrationTestDatabaseSafetyError(
            "connected database must be an isolated/test database"
        )

    if runtime_url:
        runtime_identity = identity_probe(runtime_url)
        # OID 级比对：即使 URL 不同也可能指向同一物理库
        if target_identity.oid == runtime_identity.oid:
            raise MigrationTestDatabaseSafetyError(
                "isolated migration target has the same PostgreSQL database OID as DATABASE_URL"
            )
        if target_identity.database == runtime_identity.database:
            raise MigrationTestDatabaseSafetyError(
                "isolated migration target resolves to the DATABASE_URL database"
            )

    return target_url
