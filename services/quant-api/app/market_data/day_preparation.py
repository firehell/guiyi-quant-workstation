"""Normal Market Fact day admission; no recovery-status or Redis authority.

One durable source attempt per authoritative Session trading day. Unknown outcomes
and process interruptions require independent readback, never an automatic retry.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re

VERSION = "market_day_metadata_preparation_v1"


class MetadataArchiveError(ValueError):
    """Missing or altered retained source evidence requires readback."""


class DayMetadataPreparation:
    def __init__(self, *, state_path, select_day, is_ready, capture, apply, acquire_lease, plan, binding_id, archive_cache=None):
        self.path = Path(state_path)
        self.binding_id = binding_id
        self.archive_root = self.path.with_name(self.path.name + ".archives")
        self._archive_cache = archive_cache if archive_cache is not None else {}
        self.select_day = select_day
        self.is_ready = is_ready
        self.capture = capture
        self.apply = apply
        self.plan = plan
        self.acquire_lease = acquire_lease

    def read_state(self):
        if not self.path.exists():
            return {}
        if self.path.is_symlink() or self.path.stat().st_size > 16_000_000:
            raise ValueError("METADATA_PREPARATION_STATE_INVALID")
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or set(value) != {"version", "days", "binding_id"}
                or value["version"] != VERSION or value["binding_id"] != self.binding_id
                or not isinstance(value["days"], dict)
                or len(value["days"]) > 4096):
            raise ValueError("METADATA_PREPARATION_STATE_INVALID")
        from datetime import date
        for key, item in value["days"].items():
            if (date.fromisoformat(key).isoformat() != key or not isinstance(item, dict)
                    or item.get("status") not in {"inflight", "prepared", "passed", "blocked"}):
                raise ValueError("METADATA_PREPARATION_STATE_INVALID")
        return value["days"]

    @staticmethod
    def _summary(record):
        summary = {key: record[key] for key in ("status", "started_at", "reason", "receipt")
                   if key in record}
        for field, digest in (("snapshot", "snapshot_sha256"), ("plan", "plan_sha256")):
            if field in record:
                summary[digest] = record[field][digest]
        return summary

    def _read_archive(self, day, item):
        try:
            proof = item["archive"]
            digest = proof["sha256"]
            name = f"{day}.{digest}.json"
            if (not isinstance(proof, dict) or set(proof) != {"file", "sha256", "size_bytes"}
                    or not re.fullmatch(r"[0-9a-f]{64}", digest) or proof["file"] != name
                    or self.archive_root.is_symlink()):
                raise MetadataArchiveError("METADATA_PREPARATION_ARCHIVE_INVALID")
            path = self.archive_root / name
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                stat = os.fstat(fd)
                identity = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                if stat.st_size > 16_000_000 or stat.st_size != proof["size_bytes"]:
                    raise MetadataArchiveError("METADATA_PREPARATION_ARCHIVE_INVALID")
                cached = self._archive_cache.get(name)
                if cached is not None and cached[0] == identity:
                    record = cached[1]
                else:
                    with os.fdopen(os.dup(fd), "rb") as file:
                        raw = file.read(16_000_001)
                    if hashlib.sha256(raw).hexdigest() != digest:
                        raise MetadataArchiveError("METADATA_PREPARATION_ARCHIVE_INVALID")
                    payload = json.loads(raw)
                    if (set(payload) != {"version", "binding_id", "trading_day", "record"}
                            or payload["version"] != VERSION or payload["binding_id"] != self.binding_id
                            or payload["trading_day"] != day):
                        raise MetadataArchiveError("METADATA_PREPARATION_ARCHIVE_INVALID")
                    record = payload["record"]
                    self._archive_cache.clear()  # Only the selected proof is retained in memory.
                    self._archive_cache[name] = (identity, record)
                if self._summary(record) != {key: value for key, value in item.items() if key != "archive"}:
                    raise MetadataArchiveError("METADATA_PREPARATION_ARCHIVE_INVALID")
                return record
            finally:
                os.close(fd)
        except MetadataArchiveError:
            raise
        except Exception:
            raise MetadataArchiveError("METADATA_PREPARATION_ARCHIVE_INVALID") from None

    def read_selected_day(self, day):
        key = day.isoformat()
        item = self.read_state().get(key)
        if item is None:
            return None
        from copy import deepcopy
        return deepcopy(self._read_archive(key, item)) if "archive" in item else item

    def _archive_terminal(self, day, record):
        """Fsync immutable content before atomically replacing the index with its proof."""
        try:
            if self.archive_root.is_symlink():
                raise MetadataArchiveError("METADATA_PREPARATION_ARCHIVE_INVALID")
            self.archive_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            payload = {"version": VERSION, "binding_id": self.binding_id,
                       "trading_day": day, "record": record}
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            if len(raw) > 16_000_000:
                raise MetadataArchiveError("METADATA_PREPARATION_ARCHIVE_INVALID")
            digest = hashlib.sha256(raw).hexdigest()
            name = f"{day}.{digest}.json"
            item = {**self._summary(record), "archive": {"file": name, "sha256": digest, "size_bytes": len(raw)}}
            path = self.archive_root / name
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
            except FileExistsError:
                self._read_archive(day, item)  # Never overwrite a partial or corrupt evidence file.
            else:
                with os.fdopen(fd, "wb") as file:
                    file.write(raw)
                    file.flush()
                    os.fsync(file.fileno())
            directory = os.open(self.archive_root, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return item
        except MetadataArchiveError:
            raise
        except Exception:
            raise MetadataArchiveError("METADATA_PREPARATION_ARCHIVE_INVALID") from None

    def _compact_legacy_terminals(self, days):
        changed = False
        for day, record in tuple(days.items()):
            if record["status"] in {"passed", "blocked"} and "archive" not in record:
                days[day] = self._archive_terminal(day, record)
                changed = True
        if changed:
            self._write(days)

    def _write(self, days):
        if self.path.is_symlink():
            raise ValueError("METADATA_PREPARATION_STATE_INVALID")
        data = json.dumps({"version": VERSION, "days": days, "binding_id": self.binding_id}, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode()
        if len(data) > 16_000_000 or len(days) > 4096:
            raise ValueError("METADATA_PREPARATION_STATE_INVALID")
        temporary = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def _exclusive(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            yield True
        finally:
            os.close(fd)

    def tick(self, now: datetime, *, phase="auto", expected_snapshot_sha256=None,
             expected_plan_sha256=None):
        if phase not in {"auto", "plan", "apply"}:
            return "METADATA_PREPARATION_PHASE_INVALID"
        if now.tzinfo is None or now.utcoffset() is None:
            return "METADATA_PREPARATION_CLOCK_INVALID"
        try:
            with self._exclusive() as locked:
                if not locked:
                    return "METADATA_PREPARATION_SOURCE_BUSY"
                day = self.select_day(now)
                if day is None:
                    return None
                days = self.read_state()
                self._compact_legacy_terminals(days)
                key = day.isoformat()
                prior = days.get(key)
                if prior is not None and "archive" in prior:
                    self._read_archive(key, prior)
                if prior is not None and prior["status"] in {"blocked", "inflight"}:
                    return "METADATA_PREPARATION_READBACK_REQUIRED"
                if prior is None or prior["status"] == "passed":
                    if self.is_ready(day):
                        return None
                    if prior is not None:
                        return "METADATA_PREPARATION_CATALOG_DRIFT"
                if phase == "apply":
                    if prior is None or prior["status"] != "prepared":
                        return "METADATA_PREPARATION_NOT_PREPARED"
                    if (expected_snapshot_sha256 != prior["snapshot"]["snapshot_sha256"]
                            or expected_plan_sha256 != prior["plan"]["plan_sha256"]):
                        return "METADATA_PREPARATION_PLAN_DRIFT"
                lease = self.acquire_lease()
                if lease is None:
                    return "METADATA_PREPARATION_SOURCE_BUSY"
                attempt_record = None
                try:
                    if prior is None:
                        if self.is_ready(day):
                            return None
                        days[key] = {"status": "inflight", "started_at": now.isoformat()}
                        attempt_record = days[key]
                        self._write(days)  # Crash before capture is still a consumed attempt.
                        snapshot = self.capture(day)
                        days[key]["snapshot"] = snapshot
                        self._write(days)
                        plan = self.plan(day, snapshot)
                        days[key].update(status="prepared", plan=plan)
                        self._write(days)  # Exact diff is durable before the first DB write.
                    if phase == "plan":
                        return None
                    item = days[key]
                    attempt_record = item
                    item["status"] = "inflight"
                    self._write(days)  # Unknown apply never resumes automatically.
                    receipt = self.apply(day, item["snapshot"], item["plan"])
                    item.update(status="passed", receipt=receipt)
                    days[key] = self._archive_terminal(key, item)
                    self._write(days)
                    return None
                except Exception as error:
                    reason = getattr(error, "code", str(error))
                    if not isinstance(reason, str) or not re.fullmatch(r"[A-Z_]{1,100}", reason):
                        reason = "METADATA_PREPARATION_FAILED"
                    record = attempt_record if attempt_record is not None else days[key]
                    record.update(status="blocked", reason=reason)
                    days[key] = self._archive_terminal(key, record)
                    self._write(days)
                    return "METADATA_PREPARATION_READBACK_REQUIRED"
                finally:
                    lease.release()
        except MetadataArchiveError:
            return "METADATA_PREPARATION_READBACK_REQUIRED"
        except Exception:
            return "METADATA_PREPARATION_AUTHORITY_UNAVAILABLE"


def select_preparation_day(resolver, products, now):
    """Reuse the sole Calendar/Session phase resolver, including its night-day identity."""
    from app.market_data.market_phase import MarketPhase
    days = set()
    for instant in (now, now + timedelta(minutes=30)):
        for product in products:
            phase = resolver.resolve(product, instant)
            if phase.phase is MarketPhase.UNKNOWN:
                raise ValueError("METADATA_PREPARATION_AUTHORITY_UNAVAILABLE")
            if phase.phase in {MarketPhase.TRADING, MarketPhase.BREAK}:
                if phase.trading_day is None:
                    raise ValueError("METADATA_PREPARATION_AUTHORITY_UNAVAILABLE")
                days.add(phase.trading_day)
    if len(days) > 1:
        raise ValueError("METADATA_PREPARATION_DAY_CONFLICT")
    return next(iter(days), None)


def catalog_day_ready(session, products, day):
    """Existing complete rank1 and Session facts need no new provider snapshot."""
    from sqlalchemy import select
    from app.models import Contract, Instrument, MainContractMap, TradingCalendar
    from app.market_data.session_clock import resolved_session_windows_for_trading_day
    maps = tuple(session.scalars(select(MainContractMap).where(
        MainContractMap.symbol.in_(products), MainContractMap.trade_date == day,
    )))
    if len(maps) != len(products) or {item.symbol for item in maps} != set(products):
        return False
    contracts = {item.contract_code: item for item in session.scalars(select(Contract).where(
        Contract.contract_code.in_([item.contract_code for item in maps]),
    ))}
    exchanges = dict(session.execute(select(Instrument.symbol, Instrument.exchange_code).where(
        Instrument.symbol.in_(products), Instrument.is_active.is_(True),
    )).all())
    for item in maps:
        contract = contracts.get(item.contract_code)
        exchange = exchanges.get(item.symbol)
        if (item.rank != 1 or item.rule != "volume_open_interest" or contract is None
                or contract.provider != "rqdata" or exchange is None
                or contract.instrument_symbol != item.symbol or contract.exchange_code != exchange
                or contract.listed_date is None or contract.expired_date is None
                or not contract.listed_date <= day < contract.expired_date):
            return False
        calendar = session.scalar(select(TradingCalendar).where(
            TradingCalendar.exchange_code == exchange, TradingCalendar.trade_date == day,
        ))
        if calendar is None or not calendar.is_trading_day:
            return False
        try:
            windows = resolved_session_windows_for_trading_day(
                session, exchange=exchange, symbol=item.symbol, trading_day=day,
            )
        except ValueError:
            return False
        if not windows:
            return False
    return True


def catalog_day_fingerprint(session, products, day):
    """Batch proof identity; cache only verified readiness, invalidate on any fact drift."""
    import hashlib
    from sqlalchemy import select, or_, func
    from sqlalchemy.orm import aliased
    from app.models import Contract, Instrument, MainContractMap, TradingCalendar, TradingSession
    maps = tuple(session.execute(select(MainContractMap, Contract, Instrument).outerjoin(
        Contract, Contract.contract_code == MainContractMap.contract_code,
    ).outerjoin(Instrument, Instrument.symbol == MainContractMap.symbol).where(
        MainContractMap.symbol.in_(products), MainContractMap.trade_date == day,
    )))
    exchanges = {row[2].exchange_code for row in maps if row[2] is not None}
    previous_calendar = aliased(TradingCalendar)
    prior_day = select(func.max(previous_calendar.trade_date)).where(
        previous_calendar.exchange_code == TradingCalendar.exchange_code,
        previous_calendar.trade_date < day, previous_calendar.is_trading_day.is_(True),
    ).correlate(TradingCalendar).scalar_subquery()
    calendars = tuple(session.scalars(select(TradingCalendar).where(
        TradingCalendar.exchange_code.in_(exchanges),
        or_(TradingCalendar.trade_date == day, TradingCalendar.trade_date == prior_day),
    )))
    sessions = tuple(session.scalars(select(TradingSession).where(
        TradingSession.exchange_code.in_(exchanges),
        or_(TradingSession.instrument_symbol.in_(products), TradingSession.instrument_symbol.is_(None)),
        TradingSession.effective_from <= day,
        or_(TradingSession.effective_to.is_(None), TradingSession.effective_to >= day),
    )))
    def values(row):
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}
    facts = [values(item) if item is not None else {"missing_identity": True}
             for row in maps for item in row]
    facts += [values(item) for item in (*calendars, *sessions)]
    encoded = sorted(json.dumps(item, sort_keys=True, default=str) for item in facts)
    return hashlib.sha256(json.dumps(encoded).encode()).hexdigest()

def build_day_metadata_preparation(session_factory, *, state_path, products, canonical_root):
    """Independent short Catalog session per Live reconcile, lazy provider on a missing day."""
    from app.market_data.catalog import MarketCatalog
    from app.market_data.current_day_metadata_recovery import (
        encode_current_day_snapshot, plan_current_day_metadata,
    )
    from app.market_data.market_phase import MarketPhaseResolver
    from app.market_data.metadata import MetadataSynchronizer
    from app.market_data.rqdata_adapter import RQDataMarketAdapter

    products = tuple(products)
    if len(products) != 60 or len(set(products)) != 60:
        raise ValueError("METADATA_PREPARATION_SCOPE_INVALID")

    verified_days = {}
    archive_cache = {}

    def tick(now, **phase_args):
        with session_factory() as session:
            catalog = MarketCatalog(session, canonical_root)
            import hashlib
            binding_id = hashlib.sha256(json.dumps({
                "catalog": session.get_bind().url.render_as_string(hide_password=True),
                "canonical_root": str(Path(canonical_root).resolve()),
                "products": sorted(products),
            }, sort_keys=True).encode()).hexdigest()
            def ready(day):
                session.rollback()
                fingerprint = catalog_day_fingerprint(session, products, day)
                if verified_days.get(day) == fingerprint:
                    return True
                result = catalog_day_ready(session, products, day)
                if result:
                    verified_days.clear()
                    verified_days[day] = fingerprint
                return result
            def capture(day):
                synchronizer = MetadataSynchronizer(RQDataMarketAdapter(session=session), catalog)
                return encode_current_day_snapshot(
                    synchronizer.capture_current_day(products, day), products=products,
                    trading_day=day,
                )
            def plan(day, snapshot):
                return plan_current_day_metadata(
                    catalog, snapshot, expected_snapshot_sha256=snapshot["snapshot_sha256"],
                    products=products, trading_day=day,
                )
            def apply(day, snapshot, frozen_plan):
                synchronizer = MetadataSynchronizer(None, catalog)
                digest = snapshot["snapshot_sha256"]
                plan = plan_current_day_metadata(
                    catalog, snapshot, expected_snapshot_sha256=digest,
                    products=products, trading_day=day,
                )
                # Lease is already held; do not acquire a nested lock or call failed recovery binding.
                from app.market_data.current_day_metadata_recovery import decode_current_day_snapshot
                prepared = synchronizer.prepare_current_day_snapshot(
                    decode_current_day_snapshot(snapshot, expected_snapshot_sha256=digest,
                                                products=products, trading_day=day), products, day,
                )
                fresh = plan_current_day_metadata(
                    catalog, snapshot, expected_snapshot_sha256=digest,
                    products=products, trading_day=day,
                )
                if fresh["plan_sha256"] != frozen_plan["plan_sha256"]:
                    raise ValueError("METADATA_PREPARATION_PLAN_DRIFT")
                synchronizer.write_prepared_current_day(prepared, preserve_equal=True)
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    raise ValueError("METADATA_PREPARATION_COMMIT_OUTCOME_UNKNOWN") from None
                if not catalog_day_ready(session, products, day):
                    raise ValueError("METADATA_PREPARATION_READBACK_FAILED")
                return {"status": "applied", "plan_sha256": plan["plan_sha256"],
                        "counts": plan["counts"], "trading_day": day.isoformat()}
            return DayMetadataPreparation(
                state_path=state_path,
                select_day=lambda value: select_preparation_day(MarketPhaseResolver(session), products, value),
                is_ready=ready, capture=capture, apply=apply, plan=plan,
                acquire_lease=catalog.acquire_maintenance_lock, binding_id=binding_id,
                archive_cache=archive_cache,
            ).tick(now, **phase_args)
    return tick
