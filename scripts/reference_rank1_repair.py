#!/usr/bin/env python3
"""Repair only the missing 2026-09-24 rank-1 facts from one frozen source.

The normal after-market writer remains the authority for future days. This
one-time entry point uses its Catalog writer, with a read-only plan and an
exact-hash, lease-bound apply. It never calls a market data provider.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from sqlalchemy import select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.market_data.catalog import MaintenanceLease, MarketCatalog
from app.market_data.closeout_binding import runtime_dependency_settings
from app.market_data.operational_universe import load_operational_products
from app.models import Contract, Instrument, MainContractMap, TradingCalendar, TradingSession


ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 9, 24)
SOURCE_COMMIT = "120c5c9490b9909bb64b2e55a5fb5893e57a04c0"
SOURCE_SHA256 = "b15453c3c4bc07c4ba031876b1e5ebd7354937168708d471bcc3bab8b97f2ae8"
MAX_SOURCE_BYTES = 4 * 1024 * 1024


class RepairBlocked(ValueError):
    """Safe public failure identity; no database or credential details."""


def _digest(value: object) -> str:
    return sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def _endpoint_digest(db_url: URL) -> str:
    if db_url.get_backend_name() != "postgresql" or db_url.query:
        raise RepairBlocked("DATABASE_ENDPOINT_INVALID")
    return _digest({
        "driver": db_url.drivername, "host": db_url.host, "port": db_url.port,
        "database": db_url.database, "username": db_url.username,
    })


def _read_source(path: Path, expected_sha: str) -> dict[str, object]:
    if expected_sha != SOURCE_SHA256 or not path.is_absolute():
        raise RepairBlocked("SOURCE_IDENTITY_INVALID")
    try:
        if path.resolve(strict=True) != path:
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_SOURCE_BYTES:
                raise ValueError
            content = handle.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(handle.fileno())
            if (
                len(content) != before.st_size
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or sha256(content).hexdigest() != expected_sha
            ):
                raise ValueError
        source = json.loads(content)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RepairBlocked("SOURCE_IDENTITY_INVALID") from exc
    if (
        not isinstance(source, dict)
        or source.get("schema_version") != 1
        or source.get("status") != "source_captured"
        or source.get("trading_day") != DAY.isoformat()
        or source.get("runtime_commit") != SOURCE_COMMIT
        or source.get("production_writes") != 0
        or source.get("provider_call_count") != 64
        or not isinstance(source.get("source_dominants"), dict)
    ):
        raise RepairBlocked("SOURCE_CONTRACT_INVALID")
    return source


def _contracts(source: dict[str, object], products: tuple[str, ...]) -> dict[str, str]:
    dominants = source["source_dominants"]
    if not isinstance(dominants, dict):
        raise RepairBlocked("SOURCE_CONTRACT_INVALID")
    if set(dominants) != {symbol.upper() for symbol in products}:
        raise RepairBlocked("SOURCE_SCOPE_INVALID")
    result: dict[str, str] = {}
    for symbol in products:
        values = dominants[symbol.upper()]
        if not isinstance(values, list):
            raise RepairBlocked("SOURCE_DOMINANT_INVALID")
        matching = [
            item.get("dominant")
            for item in values
            if isinstance(item, dict) and item.get("date") == "2026-09-24 00:00:00"
        ]
        if len(matching) != 1 or not isinstance(matching[0], str):
            raise RepairBlocked("SOURCE_DOMINANT_INVALID")
        contract = matching[0]
        if re.fullmatch(r"[A-Z]{1,4}[0-9]{4}", contract) is None:
            raise RepairBlocked("SOURCE_DOMINANT_INVALID")
        result[symbol] = contract
    return result


def _exact_checkout(expected_sha: str) -> None:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-c", "core.fsmonitor=false", "status", "--porcelain=v1"],
        cwd=ROOT, text=True,
    ).strip()
    if commit != expected_sha or len(commit) != 40 or dirty:
        raise RepairBlocked("CODE_IDENTITY_DRIFT")


def _plan(
    session: Session, contracts: dict[str, str], *, source_sha: str,
    code_sha: str, universe_sha: str, database: str, endpoint_sha: str,
    subscriptions: dict[str, str] | None,
) -> dict[str, object]:
    if subscriptions != contracts:
        raise RepairBlocked("SUBSCRIPTION_SNAPSHOT_DRIFT")
    if session.execute(text("SELECT current_database()")).scalar_one() != database:
        raise RepairBlocked("DATABASE_IDENTITY_DRIFT")
    if session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != "20260919_0047":
        raise RepairBlocked("SCHEMA_IDENTITY_DRIFT")
    rows: list[dict[str, str]] = []
    for symbol, contract_code in sorted(contracts.items()):
        instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
        if instrument is None:
            raise RepairBlocked("INSTRUMENT_MISSING")
        calendar = session.scalar(select(TradingCalendar).where(
            TradingCalendar.exchange_code == instrument.exchange_code,
            TradingCalendar.trade_date == DAY,
        ))
        if calendar is None or not calendar.is_trading_day or calendar.provider != "rqdata":
            raise RepairBlocked("CALENDAR_IDENTITY_DRIFT")
        has_session = session.scalar(select(TradingSession.id).where(
            TradingSession.instrument_symbol == symbol,
            TradingSession.exchange_code == instrument.exchange_code,
            TradingSession.effective_from <= DAY,
            (TradingSession.effective_to.is_(None) | (TradingSession.effective_to >= DAY)),
            TradingSession.is_active.is_(True),
            TradingSession.provider == "rqdata",
        ).limit(1))
        if has_session is None:
            raise RepairBlocked("SESSION_IDENTITY_DRIFT")
        contract = session.scalar(select(Contract).where(
            Contract.contract_code == contract_code,
        ))
        if (
            contract is None or contract.instrument_symbol != symbol
            or contract.exchange_code != instrument.exchange_code
            or (contract.provider or "").strip().lower() != "rqdata"
            or contract.listed_date is None or contract.listed_date > DAY
            or contract.expired_date is None or contract.expired_date <= DAY
        ):
            raise RepairBlocked("CONTRACT_IDENTITY_DRIFT")
        existing = session.scalar(select(MainContractMap).where(
            MainContractMap.symbol == symbol, MainContractMap.trade_date == DAY,
        ))
        if existing is not None and (
            existing.contract_code != contract_code
            or existing.rank != 1 or existing.rule != "volume_open_interest"
        ):
            raise RepairBlocked("RANK1_CONFLICT")
        rows.append({
            "symbol": symbol, "trade_date": DAY.isoformat(),
            "contract_code": contract_code,
            "state": "equal" if existing is not None else "insert",
        })
    payload: dict[str, object] = {
        "schema_version": 1, "operation": "reference_rank1_gap_repair_20260924",
        "readonly": True, "code_sha": code_sha, "source_sha256": source_sha,
        "universe_sha256": universe_sha, "database": database,
        "endpoint_sha256": endpoint_sha,
        "alembic_version": "20260919_0047", "trading_day": DAY.isoformat(),
        "counts": {
            "total": len(rows),
            "insert": sum(row["state"] == "insert" for row in rows),
            "equal": sum(row["state"] == "equal" for row in rows),
        },
        "rows": rows, "provider_requests": 0, "canonical_writes": 0,
    }
    if len(rows) != 60:
        raise RepairBlocked("UNIVERSE_SCOPE_DRIFT")
    return {**payload, "plan_sha256": _digest(payload)}


def _write_plan(path: Path, plan: dict[str, object]) -> None:
    if not path.is_absolute() or not path.parent.resolve(strict=True).is_relative_to(
        Path(tempfile.gettempdir()).resolve()
    ):
        raise RepairBlocked("OUTPUT_PATH_INVALID")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, sort_keys=True, indent=2)
            handle.write("\n")
    except OSError as exc:
        raise RepairBlocked("OUTPUT_PATH_INVALID") from exc


def _run_under_lease(
    session: Session, lease: MaintenanceLease, write: Callable[[], None],
) -> None:
    """Keep a failed commit outcome unknown even when cleanup also fails."""
    commit_attempted = False
    try:
        write()
        commit_attempted = True
        try:
            session.commit()
        except Exception as exc:
            try:
                session.rollback()
            except Exception:
                pass
            raise RepairBlocked("COMMIT_OUTCOME_UNKNOWN") from exc
    finally:
        try:
            lease.release()
        except Exception as exc:
            raise RepairBlocked(
                "COMMIT_OUTCOME_UNKNOWN" if commit_attempted
                else "MAINTENANCE_RELEASE_FAILED"
            ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("plan", "apply"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-code-sha", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if (
            args.phase == "plan" and (args.apply or args.expected_plan_sha256 or args.output is None)
            or args.phase == "apply" and (
                not args.apply or args.output is not None
                or re.fullmatch(r"[0-9a-f]{64}", args.expected_plan_sha256 or "") is None
            )
        ):
            raise RepairBlocked("PHASE_ARGUMENT_INVALID")
        _exact_checkout(args.expected_code_sha)
        source = _read_source(args.source, args.expected_source_sha256)
        products = load_operational_products()
        contracts = _contracts(source, products)
        universe_sha = sha256((ROOT / "data/universe/operational_products.txt").read_bytes()).hexdigest()

        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        from redis import Redis
        from app.db.url import normalize_database_url
        from app.market_data.closeout_binding import _redis_url
        from app.market_data.live_market import RedisLiveStore
        settings = runtime_dependency_settings(
            (Path.home() / "Library/Application Support/GuiyiQuant/project.env").read_bytes()
        )
        if any(key.startswith("PG") for key in os.environ):
            raise RepairBlocked("AMBIENT_PG_CONFIG")
        db_url = make_url(normalize_database_url(settings["DATABASE_URL"]))
        endpoint_sha = _endpoint_digest(db_url)
        engine = create_engine(normalize_database_url(settings["DATABASE_URL"]))
        redis = Redis.from_url(_redis_url(settings))
        try:
            with Session(engine, autoflush=False) as session:
                if args.phase == "plan":
                    session.execute(text("SET TRANSACTION READ ONLY"))
                    plan = _plan(
                        session, contracts, source_sha=args.expected_source_sha256,
                        code_sha=args.expected_code_sha, universe_sha=universe_sha,
                        database=args.expected_database_name, endpoint_sha=endpoint_sha,
                        subscriptions=RedisLiveStore(redis).subscriptions(DAY),
                    )
                    _write_plan(args.output, plan)
                    session.rollback()
                    print(json.dumps({
                        "status": "planned", "readonly": True,
                        "plan_sha256": plan["plan_sha256"], "counts": plan["counts"],
                        "output": str(args.output),
                    }, sort_keys=True))
                else:
                    catalog = MarketCatalog(
                        session, Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
                    )
                    lease = catalog.acquire_maintenance_lock()
                    if lease is None:
                        raise RepairBlocked("MAINTENANCE_LOCKED")
                    fresh: dict[str, object] = {}

                    def write() -> None:
                        nonlocal fresh
                        _exact_checkout(args.expected_code_sha)
                        fresh = _plan(
                            session, contracts, source_sha=args.expected_source_sha256,
                            code_sha=args.expected_code_sha, universe_sha=universe_sha,
                            database=args.expected_database_name, endpoint_sha=endpoint_sha,
                            subscriptions=RedisLiveStore(redis).subscriptions(DAY),
                        )
                        if fresh["plan_sha256"] != args.expected_plan_sha256:
                            raise RepairBlocked("PLAN_DRIFT")
                        inserts = {
                            row["symbol"] for row in fresh["rows"] if row["state"] == "insert"
                        }
                        if inserts:
                            session.add_all(MainContractMap(
                                symbol=symbol, trade_date=DAY,
                                contract_code=contracts[symbol], rank=1,
                                rule="volume_open_interest",
                            ) for symbol in sorted(inserts))
                            session.flush()

                    _run_under_lease(session, lease, write)
                    print(json.dumps({
                        "status": "applied", "readonly": False,
                        "plan_sha256": fresh["plan_sha256"],
                        "writes": fresh["counts"]["insert"],
                    }, sort_keys=True))
        finally:
            redis.close()
            engine.dispose()
    except RepairBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 1
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "REPAIR_INTERNAL_ERROR"}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
