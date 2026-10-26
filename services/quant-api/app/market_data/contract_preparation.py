"""Durable, bounded normal-rollover historical admission.

Consumer requests are hints only. Sole Catalog discovery determines the admitted
physical identity and enabled frequency scope. The executor must call ``reserve``
inside the native maintenance lease, after exact-plan verification and before any
source call. A crash after that point consumes the attempt and reserved budget.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from time import monotonic as system_monotonic

VERSION = "contract_preparation_v1"
FREQUENCIES = ("1m", "5m", "15m", "30m", "60m", "1d", "1w")
RETRYABLE = {"RQDATA_NOT_READY", "NEXT_TRADING_SESSION_NOT_READY"}
STATES = {"PENDING", "WAITING_LEASE", "WAITING_SOURCE", "INFLIGHT", "READY",
          "READBACK_REQUIRED", "BUDGET_EXCEEDED", "ADMISSION_TIME_EXCEEDED", "WAITING_DEPENDENCY"}


class PreparationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str, allow_nan=False).encode()).hexdigest()


def _safe_code(error):
    code = getattr(error, "code", "")
    if not code and isinstance(error, ValueError) and error.args:
        code = error.args[0]
    return code if isinstance(code, str) and re.fullmatch(r"[A-Z_]{1,100}", code) else "CONTRACT_PREPARATION_FAILED"


@dataclass(frozen=True)
class PreparationDemand:
    product: str
    contract: str
    trading_day: date
    listed_date: date
    expired_date: date
    through: date
    frequencies: tuple[str, ...]
    scope_fingerprint: str

    def __post_init__(self):
        if (not re.fullmatch(r"[a-z]{1,4}", self.product)
                or not re.fullmatch(r"[A-Z]{1,4}[0-9]{3,4}", self.contract)
                or not self.listed_date <= self.through < self.expired_date
                or not self.listed_date <= self.trading_day < self.expired_date
                or self.through >= self.trading_day or not self.frequencies
                or len(set(self.frequencies)) != len(self.frequencies)
                or any(item not in FREQUENCIES for item in self.frequencies)
                or not self.scope_fingerprint):
            raise ValueError("CONTRACT_PREPARATION_DEMAND_INVALID")

    @property
    def key(self):
        # Trading day budgets are independent of deduplicated completed cutoff.
        return _digest({key: value for key, value in asdict(self).items() if key != "trading_day"})

    @property
    def contract_key(self):
        return _digest((self.product, self.contract, self.listed_date, self.expired_date))


@dataclass(frozen=True)
class PreparationPlan:
    plan_sha256: str
    provider_requests: int
    expected_bars: int

    def __post_init__(self):
        if (not re.fullmatch(r"[a-f0-9]{64}", self.plan_sha256)
                or any(type(value) is not int or value < 0
                       for value in (self.provider_requests, self.expected_bars))):
            raise ValueError("CONTRACT_PREPARATION_PLAN_INVALID")


def enqueue_request(state_path, product, contract, trading_day, frequencies):
    """Cross-process inbox; no Catalog, provider, Canonical or consumer mutation."""
    from app.market_data.domain import normalize_contract_for_symbol
    product = product.strip().lower()
    contract = normalize_contract_for_symbol(product, contract)
    selected = tuple(frequencies)
    if any(item not in FREQUENCIES for item in selected):
        raise ValueError("CONTRACT_PREPARATION_REQUEST_INVALID")
    frequencies = tuple(item for item in FREQUENCIES if item in selected)
    if (contract is None or type(trading_day) is not date or not frequencies
            or not re.fullmatch(r"[a-z]{1,4}", product)):
        raise ValueError("CONTRACT_PREPARATION_REQUEST_INVALID")
    payload = {"product": product, "contract": contract, "trading_day": trading_day.isoformat(),
               "frequencies": frequencies}
    inbox = Path(str(state_path) + ".inbox")
    if inbox.is_symlink():
        raise ValueError("CONTRACT_PREPARATION_STATE_INVALID")
    inbox.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = inbox / (_digest(payload) + ".json")
    # A hint is idempotent. Interrupted writes cannot grant mutation authority.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as file:
        json.dump(payload, file, sort_keys=True)
        file.flush()
        os.fsync(file.fileno())
    return True


class ContractPreparation:
    def __init__(self, *, state_path, binding_id, discover, plan, apply, readback, monotonic=None, on_write=None):
        self.path = Path(state_path)
        self.binding_id = binding_id
        self.archive_root = Path(str(self.path) + ".archives")
        self.discover, self.plan, self.apply, self.readback = discover, plan, apply, readback
        self.monotonic = monotonic or system_monotonic
        self.on_write = on_write

    def request(self, product, contract, trading_day, frequencies):
        return enqueue_request(self.path, product, contract, trading_day, frequencies)

    def _hints(self):
        inbox = Path(str(self.path) + ".inbox")
        if inbox.is_symlink():
            raise ValueError("CONTRACT_PREPARATION_INBOX_INVALID")
        if not inbox.exists():
            return {}
        paths = tuple(inbox.iterdir())
        if len(paths) > 4096 or stat.S_IMODE(inbox.stat().st_mode) & 0o022:
            raise ValueError("CONTRACT_PREPARATION_INBOX_INVALID")
        hints = {}
        try:
            for path in paths:
                if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
                    raise ValueError
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as file:
                    info = os.fstat(file.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_size > 4096
                            or stat.S_IMODE(info.st_mode) & 0o022):
                        raise ValueError
                    value = json.loads(file.read(4097))
                if (set(value) != {"product", "contract", "trading_day", "frequencies"}
                        or _digest(value) + ".json" != path.name
                        or not isinstance(value["frequencies"], list) or not value["frequencies"]
                        or any(freq not in FREQUENCIES for freq in value["frequencies"])
                        or not re.fullmatch(r"[a-z]{1,4}", value["product"])
                        or not re.fullmatch(r"[A-Z]{1,4}[0-9]{3,4}", value["contract"])):
                    raise ValueError
                date.fromisoformat(value["trading_day"])
                hints[path] = value
            return hints
        except Exception:
            raise ValueError("CONTRACT_PREPARATION_INBOX_INVALID") from None

    def _consume_hints(self, paths):
        for path in paths:
            path.unlink(missing_ok=True)
        if paths:
            directory = os.open(Path(str(self.path) + ".inbox"), os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def _empty(self):
        return {"version": VERSION, "binding_id": self.binding_id, "requests": {}, "budgets": {}, "archives": {}}

    def snapshot(self):
        if not self.path.exists():
            return self._empty()
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "r") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 16_000_000:
                    raise ValueError
                value = json.loads(file.read(16_000_001))
            if (set(value) != {"version", "binding_id", "requests", "budgets", "archives"}
                    or value["version"] != VERSION or value["binding_id"] != self.binding_id
                    or not isinstance(value["requests"], dict) or len(value["requests"]) > 4096
                    or not isinstance(value["budgets"], dict) or not isinstance(value["archives"], dict)):
                raise ValueError
            for key, record in value["requests"].items():
                if (not re.fullmatch(r"[0-9a-f]{64}", key) or not isinstance(record, dict)
                        or not isinstance(record.get("units"), dict)
                        or any(freq not in FREQUENCIES or item.get("status") not in STATES
                               or type(item.get("attempts")) is not int or item["attempts"] not in {0, 1, 2}
                               for freq, item in record["units"].items())):
                    raise ValueError
                identity = record["identity"]
                restored = PreparationDemand(**{**identity,
                    **{field: date.fromisoformat(identity[field]) for field in
                       ("trading_day", "listed_date", "expired_date", "through")},
                    "frequencies": tuple(identity["frequencies"])})
                if restored.key != key or set(record["units"]) - set(restored.frequencies):
                    raise ValueError
            for day, budget in value["budgets"].items():
                date.fromisoformat(day)
                for cost in (budget, *budget["contracts"].values()):
                    if any(type(cost[key]) is not int or cost[key] < 0 for key in ("requests", "bars")):
                        raise ValueError
            for scope_key, proof in value["archives"].items():
                self._read_archive(scope_key, proof)
            return value
        except Exception:
            raise ValueError("CONTRACT_PREPARATION_STATE_INVALID") from None

    @staticmethod
    def _scope_key(record):
        return _digest({field: record["identity"][field] for field in
                        ("product", "contract", "listed_date", "expired_date", "frequencies", "scope_fingerprint")})

    def _read_archive(self, scope_key, proof):
        try:
            digest = proof["sha256"]
            if (set(proof) != {"sha256", "file", "size_bytes"}
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or proof["file"] != digest + ".json" or self.archive_root.is_symlink()
                    or type(proof["size_bytes"]) is not int or not 0 < proof["size_bytes"] <= 16_000_000):
                raise ValueError
            fd = os.open(self.archive_root / proof["file"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as file:
                info = os.fstat(file.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_size != proof["size_bytes"]
                        or stat.S_IMODE(info.st_mode) & 0o022):
                    raise ValueError
                raw = file.read(16_000_001)
            payload = json.loads(raw)
            if (hashlib.sha256(raw).hexdigest() != digest
                    or set(payload) != {"version", "binding_id", "scope_key", "request_key", "record", "previous"}
                    or payload["version"] != VERSION or payload["binding_id"] != self.binding_id
                    or payload["scope_key"] != scope_key or self._scope_key(payload["record"]) != scope_key
                    or not all(unit["status"] == "READY" for unit in payload["record"]["units"].values())):
                raise ValueError
            return payload
        except Exception:
            raise ValueError("CONTRACT_PREPARATION_ARCHIVE_INVALID") from None

    def _archive(self, scope_key, key, record, previous):
        if self.archive_root.is_symlink():
            raise ValueError("CONTRACT_PREPARATION_ARCHIVE_INVALID")
        self.archive_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if stat.S_IMODE(self.archive_root.stat().st_mode) & 0o022:
            raise ValueError("CONTRACT_PREPARATION_ARCHIVE_INVALID")
        if previous is not None:
            self._read_archive(scope_key, previous)
        payload = {"version": VERSION, "binding_id": self.binding_id, "scope_key": scope_key,
                   "request_key": key, "record": record, "previous": previous}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > 16_000_000:
            raise ValueError("CONTRACT_PREPARATION_ARCHIVE_INVALID")
        digest = hashlib.sha256(raw).hexdigest()
        proof = {"sha256": digest, "file": digest + ".json", "size_bytes": len(raw)}
        try:
            fd = os.open(self.archive_root / proof["file"], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        except FileExistsError:
            self._read_archive(scope_key, proof)
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
        return proof

    def _compact(self, state, now):
        groups = {}
        for key, record in state["requests"].items():
            if record["units"] and all(unit["status"] == "READY" for unit in record["units"].values()):
                groups.setdefault(self._scope_key(record), []).append((key, record))
        for scope_key, records in groups.items():
            records.sort(key=lambda pair: pair[1]["identity"]["through"])
            # Keep the newest exact cutoff online. Never compact unresolved work.
            for key, record in records[:-1]:
                proof = self._archive(scope_key, key, record, state["archives"].get(scope_key))
                state["archives"][scope_key] = proof
                del state["requests"][key]
                self._write(state)  # Immutable proof is durable before index removal.
        # Current/future reservations never disappear. Historical authority cannot
        # rediscover an old trading day, so completed old daily ledgers may expire.
        threshold = (now.date() - timedelta(days=2)).isoformat()
        state["budgets"] = {day: budget for day, budget in state["budgets"].items() if day >= threshold}
        self._write(state)

    def _write(self, value):
        if self.path.is_symlink():
            raise ValueError("CONTRACT_PREPARATION_STATE_INVALID")
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > 16_000_000 or len(value["requests"]) > 4096:
            raise ValueError("CONTRACT_PREPARATION_STATE_INVALID")
        temporary = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.path)
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if self.on_write is not None:
            self.on_write(value)

    @contextmanager
    def _exclusive(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            yield True
        finally:
            os.close(fd)

    def _budget(self, state, demand, plan, *, reserve=False):
        day = state["budgets"].get(demand.trading_day.isoformat(), {"requests": 0, "bars": 0, "contracts": {}})
        contract = day["contracts"].get(demand.contract_key, {"requests": 0, "bars": 0})
        if (contract["requests"] + plan.provider_requests > 64 or contract["bars"] + plan.expected_bars > 2_000_000
                or day["requests"] + plan.provider_requests > 256 or day["bars"] + plan.expected_bars > 8_000_000):
            raise ValueError("CONTRACT_PREPARATION_BUDGET_EXCEEDED")
        if reserve:
            for cost in (day, contract):
                cost["requests"] += plan.provider_requests
                cost["bars"] += plan.expected_bars
            day["contracts"][demand.contract_key] = contract
            state["budgets"][demand.trading_day.isoformat()] = day

    def tick(self, now):
        if now.tzinfo is None or now.utcoffset() is None:
            return "CONTRACT_PREPARATION_CLOCK_INVALID"
        try:
            with self._exclusive() as locked:
                if not locked:
                    return "CONTRACT_PREPARATION_BUSY"
                state = self.snapshot()
                hints = self._hints()
                consumed = set()
                for demand in self.discover(now):
                    if not isinstance(demand, PreparationDemand):
                        raise ValueError("CONTRACT_PREPARATION_AUTHORITY_INVALID")
                    record = state["requests"].setdefault(demand.key, {"identity": json.loads(json.dumps(asdict(demand), default=str)), "units": {}})
                    matched_hints = {path: hint for path, hint in hints.items()
                        if hint["product"] == demand.product and hint["contract"] == demand.contract
                        and hint["trading_day"] == demand.trading_day.isoformat()
                        and set(hint["frequencies"]).issubset(demand.frequencies)}
                    consumed.update(matched_hints)
                    started = self.monotonic()
                    def check():
                        if self.monotonic() - started >= 1200:
                            raise PreparationError("CONTRACT_PREPARATION_ADMISSION_TIME_EXCEEDED")
                    for frequency in demand.frequencies:
                        unit = record["units"].setdefault(frequency, {"status": "PENDING", "attempts": 0})
                        if unit["status"] == "INFLIGHT":
                            unit.update(status="READBACK_REQUIRED", reason="PROCESS_INTERRUPTED")
                            self._write(state)
                        if unit["status"] == "READY" and any(frequency in hint["frequencies"] for hint in matched_hints.values()):
                            # A consumer reporting a missing prefix invalidates cached
                            # readiness only. It cannot authorize provider retry.
                            try:
                                if not self.readback(demand, frequency):
                                    raise ValueError("CONTRACT_PREPARATION_READY_INPUT_DRIFT")
                                unit["validated_at"] = now.isoformat()
                            except Exception:
                                unit.update(status="READBACK_REQUIRED", reason="CONTRACT_PREPARATION_READY_INPUT_DRIFT")
                            self._write(state)
                        if unit["status"] in {"READY", "READBACK_REQUIRED", "BUDGET_EXCEEDED", "ADMISSION_TIME_EXCEEDED"}:
                            continue
                        if unit["status"] == "WAITING_SOURCE" and now < datetime.fromisoformat(unit["retry_at"]):
                            continue
                        # An advancing cutoff/scope cannot hide an unresolved prior attempt.
                        family = set(FREQUENCIES[:5]) if frequency in FREQUENCIES[:5] else {"1d", "1w"}
                        unresolved = any(other["identity"]["contract"] == demand.contract
                                         and any((other is not record or prior_frequency != frequency)
                                                 and prior_frequency in family
                                                 and prior_unit["status"] in {"INFLIGHT", "READBACK_REQUIRED", "WAITING_SOURCE"}
                                                 for prior_frequency, prior_unit in other["units"].items())
                                         for other in state["requests"].values())
                        if unresolved:
                            unit.update(status="WAITING_DEPENDENCY", reason="PRIOR_ATTEMPT_UNRESOLVED")
                            self._write(state)
                            continue
                        reserved = False
                        try:
                            check()
                            frozen = self.plan(demand, frequency, check)
                            self._budget(state, demand, frozen)
                            def reserve():
                                nonlocal reserved
                                if reserved:
                                    raise ValueError("CONTRACT_PREPARATION_DUPLICATE_RESERVATION")
                                check()
                                self._budget(state, demand, frozen, reserve=True)
                                for stale in ("reason", "retry_at", "validated_at"):
                                    unit.pop(stale, None)
                                unit.update(status="INFLIGHT", attempts=unit["attempts"] + 1,
                                            started_at=now.isoformat(), plan_sha256=frozen.plan_sha256,
                                            reserved_requests=frozen.provider_requests, reserved_bars=frozen.expected_bars)
                                unit.setdefault("history", []).append({
                                    "status": "INFLIGHT", "started_at": now.isoformat(),
                                    "plan_sha256": frozen.plan_sha256,
                                    "reserved_requests": frozen.provider_requests, "reserved_bars": frozen.expected_bars,
                                })
                                self._write(state)
                                reserved = True
                            result = self.apply(demand, frequency, frozen, reserve, check)
                            if result.get("status") == "busy" and not reserved:
                                unit.update(status="WAITING_LEASE")
                            elif not reserved:
                                raise ValueError("CONTRACT_PREPARATION_RESERVATION_MISSING")
                            elif result.get("status") in {"passed", "noop"}:
                                # Executor's transaction has ended. readback opens a fresh one.
                                if not self.readback(demand, frequency):
                                    raise ValueError("CONTRACT_PREPARATION_READBACK_FAILED")
                                unit.update(status="READY", validated_at=now.isoformat())
                            elif (result.get("reason") in RETRYABLE and result.get("applied") == 0
                                  and type(result.get("applied")) is int and unit["attempts"] == 1):
                                unit.update(status="WAITING_SOURCE", reason=result["reason"],
                                            retry_at=(now + timedelta(hours=1)).isoformat())
                            else:
                                unit.update(status="READBACK_REQUIRED", reason=(result.get("reason")
                                            if isinstance(result.get("reason"), str) and re.fullmatch(r"[A-Z_]{1,100}", result["reason"])
                                            else "CONTRACT_PREPARATION_APPLY_FAILED"))
                        except Exception as error:
                            reason = _safe_code(error)
                            status = {"CONTRACT_PREPARATION_BUDGET_EXCEEDED": "BUDGET_EXCEEDED",
                                      "CONTRACT_PREPARATION_ADMISSION_TIME_EXCEEDED": "ADMISSION_TIME_EXCEEDED"}.get(reason, "READBACK_REQUIRED")
                            unit.update(status="READBACK_REQUIRED" if reserved else status, reason=reason)
                        if reserved:
                            unit["history"][-1].update({field: unit[field] for field in
                                ("status", "reason", "retry_at", "validated_at") if field in unit})
                        self._write(state)
                self._compact(state, now)
                self._consume_hints(consumed)
                return None
        except Exception as error:
            return _safe_code(error)
