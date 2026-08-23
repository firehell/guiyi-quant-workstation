#!/usr/bin/env python3
"""Read-only, digest-only snapshot for the separately gated real backtest smoke."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any

from sqlalchemy import text

from app.db.session import engine
from app.redis_connections import get_redis_connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _database_snapshot() -> str:
    rows: list[tuple[str, int, int]] = []
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            table_names = connection.execute(
                text(
                    "SELECT tablename FROM pg_catalog.pg_tables "
                    "WHERE schemaname = 'public' ORDER BY tablename"
                )
            ).scalars()
            preparer = engine.dialect.identifier_preparer
            for table_name in table_names:
                if not isinstance(table_name, str):
                    raise RuntimeError
                quoted = preparer.quote_identifier(table_name)
                count, max_xmin = connection.exec_driver_sql(
                    f"SELECT count(*), coalesce(max(xmin::text::bigint), 0) FROM {quoted}"
                ).one()
                rows.append((table_name, int(count), int(max_xmin)))
        finally:
            transaction.rollback()
    return _digest(rows)


def _redis_snapshot() -> str:
    client = get_redis_connection()
    entries: list[tuple[str, str]] = []
    try:
        client.ping()
        for raw_key in client.scan_iter(match="*", count=500):
            key = bytes(raw_key)
            dumped = client.dump(key)
            if dumped is None:
                raise RuntimeError
            entries.append((sha256(key).hexdigest(), sha256(bytes(dumped)).hexdigest()))
    finally:
        client.close()
    entries.sort()
    return _digest(entries)


def _canonical_snapshot() -> str:
    configured = os.environ.get("GUIYI_CANONICAL_DATA_ROOT", "").strip()
    if not configured:
        raise RuntimeError
    root = Path(configured)
    if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
        raise RuntimeError
    entries: list[tuple[str, str, int, int, int]] = []
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError
        kind = "d" if stat.S_ISDIR(metadata.st_mode) else "f"
        if kind == "f" and not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError
        entries.append(
            (
                path.relative_to(root).as_posix(),
                kind,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ino,
            )
        )
    return _digest(entries)


def _runtime_snapshot() -> str:
    completed = subprocess.run(
        [str(PROJECT_ROOT / "scripts/ops/macos/local-services-status.sh")],
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise RuntimeError
    return sha256(completed.stdout).hexdigest()


def _notification_config_snapshot() -> str:
    plist = (
        Path.home()
        / "Library/LaunchAgents/com.guiyi.quant-api.plist"
    )
    completed = subprocess.run(
        [
            "/usr/bin/plutil",
            "-extract",
            "EnvironmentVariables.GUIYI_ALERT_NOTIFICATION_CONFIG_PATH",
            "raw",
            "-o",
            "-",
            str(plist),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=5,
    )
    if completed.returncode != 0:
        raise RuntimeError
    path = Path(completed.stdout.decode("utf-8").strip())
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise RuntimeError
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError
    return _digest(
        {
            "mode": stat.S_IMODE(metadata.st_mode),
            "size": metadata.st_size,
            "mtime_ns": metadata.st_mtime_ns,
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
    )


def _order_boundary_snapshot() -> str:
    market_schema = PROJECT_ROOT / "services/quant-api/app/schemas/market.py"
    local_app = PROJECT_ROOT / "services/quant-api/app/backtest/local_app.py"
    sources = {
        "market_schema": market_schema.read_bytes(),
        "backtest_local_app": local_app.read_bytes(),
    }
    if b"auto_order: Literal[False]" not in sources["market_schema"]:
        raise RuntimeError
    if b"app.main" in sources["backtest_local_app"]:
        raise RuntimeError
    return _digest(
        {name: sha256(content).hexdigest() for name, content in sources.items()}
    )


def snapshot() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "VERIFIED",
        "database_alert_execution_review_catalog": _database_snapshot(),
        "redis": _redis_snapshot(),
        "canonical": _canonical_snapshot(),
        "notification_config": _notification_config_snapshot(),
        "runtime": _runtime_snapshot(),
        "order_boundary": _order_boundary_snapshot(),
    }


def main() -> int:
    try:
        payload = snapshot()
    except Exception:
        print(
            json.dumps(
                {"schema_version": 1, "status": "NOT_VERIFIED"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
